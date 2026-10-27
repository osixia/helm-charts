#!/usr/bin/env python3
"""Exercise the actual web applications and LDAP ACLs in the example namespace."""

import argparse
import base64
import hashlib
from html import unescape
from html.parser import HTMLParser
from contextlib import contextmanager
from http.client import HTTPConnection
from http.cookies import SimpleCookie
import json
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
import time
from urllib.parse import urlencode, urlsplit, parse_qs


class Browser:
    """HTTP client for the local example; keep each session's cookies."""

    def __init__(self, port, host):
        self.port, self.host, self.cookies = port, host, {}

    def request(self, method, path, data=None, form=False, headers=None):
        request_headers = {
            "Host": self.host, "X-Forwarded-Host": self.host,
            "X-Forwarded-Proto": "http", "Origin": f"http://{self.host}",
            "Referer": f"http://{self.host}/", "Accept": "application/json",
            "Cookie": "; ".join(f"{key}={value}" for key, value in self.cookies.items()),
        }
        if headers:
            request_headers.update(headers)
        body = None
        if data is not None:
            body = urlencode(data) if form else json.dumps(data)
            request_headers["Content-Type"] = (
                "application/x-www-form-urlencoded" if form else "application/json"
            )
        connection = HTTPConnection("127.0.0.1", self.port, timeout=20)
        try:
            connection.request(method, path, body, request_headers)
            response = connection.getresponse()
            content = response.read().decode()
            for key, value in response.getheaders():
                if key.lower() == "set-cookie":
                    cookie = SimpleCookie()
                    cookie.load(value)
                    self.cookies.update({key: item.value for key, item in cookie.items()})
            return response.status, dict(response.getheaders()), content
        finally:
            connection.close()

    def ok(self, path, data):
        status, _, content = self.request("POST", path, data)
        assert status == 200 and (not content or json.loads(content)["status"] == "OK"), (path, status, content)
        return json.loads(content) if content else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", default="ldap-stack-keycloak-test")
    parser.add_argument("--credentials", required=True, type=Path)
    args = parser.parse_args()
    credentials = json.loads(args.credentials.read_text())
    kubectl = ["kubectl", "-n", args.namespace]

    def kube(*arguments, input=None, check=True):
        return subprocess.run(kubectl + list(arguments), input=input, text=True,
                              capture_output=True, check=check)

    @contextmanager
    def forward(service):
        with tempfile.TemporaryFile(mode="w+") as log:
            process = subprocess.Popen(kubectl + ["port-forward", f"svc/{service}", "0:80"],
                                       stdout=log, stderr=log, text=True)
            try:
                for _ in range(150):
                    log.seek(0)
                    output = log.read()
                    match = re.search(r"Forwarding from 127\.0\.0\.1:(\d+)", output)
                    if match:
                        yield int(match[1])
                        return
                    if process.poll() is not None:
                        raise RuntimeError(f"port-forward {service} failed: {output}")
                    time.sleep(0.2)
                raise RuntimeError(f"port-forward {service} timed out")
            finally:
                process.terminate()
                process.wait(timeout=10)

    def ldap(user, password, tool, *arguments, ldif="", code=0, tls=True,
             ca_file="/container/services/openldap/assets/certs/ca.crt"):
        # Passwords travel over stdin and never appear in process arguments.
        script = '''set -eu
umask 077
secret_file=$(mktemp)
trap 'rm -f "${secret_file}"' EXIT
IFS= read -r secret
printf '%s' "${secret}" > "${secret_file}"
tool=$1
shift
"${tool}" -y "${secret_file}" "$@"
'''
        tls_arguments = ["-ZZ"] if tls else []
        result = kube("exec", "-i", "openldap-0", "-c", "openldap", "--", "env",
                      f"LDAPTLS_CACERT={ca_file}", "LDAPTLS_REQCERT=demand",
                      "sh", "-c", script, "ldap-check", tool, "-x", "-H", "ldap://openldap:389",
                      *tls_arguments,
                      "-D", user, *arguments, input=password + "\n" + ldif, check=False)
        assert result.returncode == code, (tool, code, result.returncode, result.stderr)
        return result.stdout

    admin = credentials["admin_dn"]
    management = "cn=keycloak,ou=services,dc=example,dc=org"
    alice = "uid=alice,ou=users,dc=example,dc=org"
    ldap(admin, credentials["admin"], "ldapwhoami")
    ldap(admin, credentials["admin"], "ldapwhoami", ca_file="/dev/null", code=1)
    # TLS is mandatory; root is not an application login.
    ldap(admin, credentials["admin"], "ldapwhoami", code=13, tls=False)
    data = ldap(management, credentials["management"], "ldapsearch", "-LLL",
                "-b", alice, "-s", "base", "displayName", "userPassword", "pwdHistory")
    assert "displayName: Alice Example" in data
    assert not re.search(r"^(userPassword|pwdHistory):", data, re.M)
    ldap(management, credentials["management"], "ldapmodify", code=50, ldif=f"""dn: {alice}
changetype: modify
replace: mail
mail: forbidden@example.org
""")
    ldap(admin, credentials["admin"], "ldapsearch", "-b", "cn=config", "-s", "base", code=32)
    print("PASS: mandatory StartTLS, untrusted CA/plaintext rejection, management privacy/write limits, admin config isolation")

    temporary_user = "uid=chart-test,ou=users,dc=example,dc=org"
    ldap(admin, credentials["admin"], "ldapadd", ldif=f"""dn: {temporary_user}
objectClass: inetOrgPerson
uid: chart-test
cn: Chart Test
sn: Test
""")
    ldap(admin, credentials["admin"], "ldapmodify", ldif=f"""dn: {temporary_user}
changetype: modify
replace: description
description: Updated by directory admin
""")
    data = ldap(management, credentials["management"], "ldapsearch", "-LLL", "-b",
                temporary_user, "-s", "base", "description")
    assert "description: Updated by directory admin" in data
    ldap(admin, credentials["admin"], "ldapdelete", temporary_user)
    print("PASS: directory admin user creation, update and deletion")

    with forward("phpldapadmin") as port:
        browser = Browser(port, "admin.ldap.example.test")
        status, _, content = browser.request("GET", "/login", headers={"Accept": "text/html"})
        assert status == 200, ("phpLDAPadmin login page", status)
        match = re.search(r'name="_token"\s+value="([^"]+)"', content)
        if not match:
            match = re.search(r'name="csrf-token"\s+content="([^"]+)"', content)
        assert match, "phpLDAPadmin CSRF token missing"
        status, _, content = browser.request("POST", "/login", {
            "_token": match[1], "dn": admin, "password": credentials["admin"],
        }, form=True)
        assert status in (200, 204, 302), ("phpLDAPadmin login", status, content[:500])
        status, _, content = browser.request("GET", "/", headers={"Accept": "text/html"})
        assert status == 200, ("phpLDAPadmin authenticated page", status)
        assert "logout" in content.lower(), "phpLDAPadmin did not establish an authenticated session"
        print("PASS: phpLDAPadmin real administrator login and authenticated page")

    def api(browser, method, path, data=None, token=None, form=False, status=200):
        headers = {"Authorization": "Bearer " + token} if token else None
        actual, response_headers, body = browser.request(method, path, data, form, headers)
        assert actual == status, (method, path, actual, body[:500])
        return json.loads(body) if body else None

    def request_path(url):
        parsed = urlsplit(unescape(url))
        return parsed.path + ("?" + parsed.query if parsed.query else "")

    class Forms(HTMLParser):
        def __init__(self, content):
            super().__init__()
            self.forms, self.current = [], None
            self.feed(content)

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == "form":
                self.current = {"action": attrs.get("action", ""), "id": attrs.get("id"), "fields": {}}
                self.forms.append(self.current)
            elif tag == "input" and self.current is not None and "name" in attrs:
                self.current["fields"][attrs["name"]] = attrs.get("value", "")

        def handle_endtag(self, tag):
            if tag == "form":
                self.current = None

    def login(port, password, success=True):
        browser = Browser(port, f"localhost:{port}")
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(24)
        path = "/realms/ldap-example/protocol/openid-connect/auth?" + urlencode({
            "client_id": "ldap-example", "redirect_uri": "http://localhost:18080/callback",
            "response_type": "code", "scope": "openid profile email", "state": state,
            "code_challenge": challenge, "code_challenge_method": "S256",
        })
        status, _, content = browser.request("GET", path, headers={"Accept": "text/html"})
        assert status == 200, ("Keycloak login page", status, content[:500])
        form = next(form for form in Forms(content).forms if form["id"] == "kc-form-login")
        form["fields"].update({"username": "alice", "password": password})
        status, headers, content = browser.request("POST", request_path(form["action"]), form["fields"], form=True)
        if not success:
            assert status == 200 and any(form['id'] == 'kc-form-login' for form in Forms(content).forms), ("old password accepted", status)
            return None
        assert status == 302, ("Keycloak OIDC login", status, content[:500])
        location = headers.get("Location", headers.get("location", ""))
        query = parse_qs(urlsplit(location).query)
        assert query.get("state") == [state] and "code" in query, ("OIDC callback missing code/state", location)
        token = api(browser, "POST", "/realms/ldap-example/protocol/openid-connect/token", {
            "grant_type": "authorization_code", "client_id": "ldap-example", "code": query["code"][0],
            "redirect_uri": "http://localhost:18080/callback", "code_verifier": verifier,
        }, form=True)
        info = api(browser, "GET", "/realms/ldap-example/protocol/openid-connect/userinfo", token=token["access_token"])
        assert info["preferred_username"] == "alice" and info["email"] == "alice@example.org", info
        assert "users" in info.get("groups", []), info
        return browser

    with forward("keycloak-http") as port:
        admin_browser = Browser(port, f"localhost:{port}")
        admin_token = api(admin_browser, "POST", "/realms/master/protocol/openid-connect/token", {
            "grant_type": "password", "client_id": "admin-cli", "username": "admin",
            "password": credentials["keycloak_admin"],
        }, form=True)["access_token"]
        login(port, credentials["alice"])
        print("PASS: Keycloak authorization-code login with PKCE, LDAP profile and group claims")

        users = api(admin_browser, "GET", "/admin/realms/ldap-example/users?username=alice&exact=true", token=admin_token)
        assert len(users) == 1 and users[0].get("federationLink") == "openldap-provider", users
        user_path = "/admin/realms/ldap-example/users/" + users[0]["id"]
        replacement = secrets.token_urlsafe(24)
        api(admin_browser, "PUT", user_path + "/reset-password", {
            "type": "password", "value": replacement, "temporary": False,
        }, token=admin_token, status=204)
        ldap(alice, replacement, "ldapwhoami")
        login(port, credentials["alice"], success=False)
        login(port, replacement)
        print("PASS: Keycloak administrative password reset reaches LDAP through the scoped management account")

        # The next browser login requires a user password change.
        api(admin_browser, "PUT", user_path, {"requiredActions": ["UPDATE_PASSWORD"]}, token=admin_token, status=204)
        browser = Browser(port, f"localhost:{port}")
        path = "/realms/ldap-example/protocol/openid-connect/auth?" + urlencode({
            "client_id": "ldap-example", "redirect_uri": "http://localhost:18080/callback",
            "response_type": "code", "scope": "openid", "code_challenge": secrets.token_urlsafe(32),
            "code_challenge_method": "S256",
        })
        status, _, content = browser.request("GET", path, headers={"Accept": "text/html"})
        form = next(form for form in Forms(content).forms if form["id"] == "kc-form-login")
        form["fields"].update({"username": "alice", "password": replacement})
        status, headers, content = browser.request("POST", request_path(form["action"]), form["fields"], form=True)
        if status == 302:
            status, _, content = browser.request("GET", request_path(headers.get("Location", headers.get("location", ""))), headers={"Accept": "text/html"})
        assert status == 200 and 'name="password-new"' in content, ("password change form", status, content[:300])
        form = next(form for form in Forms(content).forms if "password-new" in form["fields"])
        changed = secrets.token_urlsafe(24)
        form["fields"].update({"password-new": changed, "password-confirm": changed})
        status, _, content = browser.request("POST", request_path(form["action"]), form["fields"], form=True)
        assert status == 302, ("Keycloak user password change", status, content[:300])
        ldap(alice, changed, "ldapwhoami")
        login(port, replacement, success=False)
        login(port, changed)
        data = ldap(management, credentials["management"], "ldapsearch", "-LLL", "-b", alice,
                    "-s", "base", "mail", "userPassword", "pwdHistory")
        assert not re.search(r"^(userPassword|pwdHistory):", data, re.M)
        print("PASS: Keycloak browser password change updates LDAP; hashes/history remain hidden")


if __name__ == "__main__":
    main()
