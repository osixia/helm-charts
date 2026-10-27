#!/usr/bin/env python3
"""Exercise the actual web applications and LDAP ACLs in the example namespace."""

import argparse
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
from urllib.parse import urlencode


class Browser:
    """HTTP client behind a simulated HTTPS proxy; keep each session's cookies."""

    def __init__(self, port, host):
        self.port, self.host, self.cookies = port, host, {}

    def request(self, method, path, data=None, form=False, headers=None):
        request_headers = {
            "Host": self.host, "X-Forwarded-Host": self.host,
            "X-Forwarded-Proto": "https", "Origin": f"https://{self.host}",
            "Referer": f"https://{self.host}/", "Accept": "application/json",
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
    parser.add_argument("--namespace", default="ldap-stack-authelia-test")
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
    management = "cn=management,ou=services,dc=example,dc=org"
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

    def login(port, password, success=True):
        browser = Browser(port, "auth.ldap.example.test")
        status, _, content = browser.request("POST", "/api/firstfactor", {
            "username": "alice", "password": password,
            "keepMeLoggedIn": False, "targetURL": "https://app.ldap.example.test/",
            "requestMethod": "GET",
        })
        if success:
            assert status == 200 and json.loads(content)["status"] == "OK", (status, content)
            status, _, content = browser.request("GET", "/api/user/info")
            assert status == 200 and "Alice Example" in content, (status, content)
        else:
            assert status == 401, ("old password still works", status, content)
        return browser

    with forward("authelia") as port:
        browser = login(port, credentials["alice"])
        status, headers, _ = browser.request("GET", "/api/authz/forward-auth", headers={
            "X-Forwarded-Host": "app.ldap.example.test", "X-Forwarded-Uri": "/",
            "X-Forwarded-Method": "GET",
        })
        assert status == 200, ("Authelia group authorization", status)
        assert "users" in {k.lower(): v for k, v in headers.items()}.get("remote-groups", "")
        print("PASS: Authelia authentication, profile and LDAP group authorization")

        changed = secrets.token_urlsafe(24)
        status, _, _ = browser.request("POST", "/api/change-password", {
            "username": "alice", "old_password": credentials["alice"], "new_password": changed,
        })
        assert status == 403, ("password change allowed without session elevation", status)
        browser.ok("/api/user/session/elevation", {})
        notification = kube("exec", "deploy/authelia", "--", "cat", "/config/notification.txt").stdout
        codes = re.findall(r"\b[A-Z0-9]{8}\b", notification)
        assert codes, "session elevation notification has no one-time code"
        status, _, content = browser.request("PUT", "/api/user/session/elevation", {"otc": codes[-1]})
        assert status == 200 and json.loads(content)["status"] == "OK", (status, content)
        status, _, _ = browser.request("POST", "/api/change-password", {
            "username": "alice", "old_password": credentials["alice"], "new_password": "short",
        })
        assert status == 400, ("Authelia accepted a password below the minimum length", status)
        status, _, _ = browser.request("POST", "/api/change-password", {
            "username": "alice", "old_password": "wrong-password", "new_password": changed,
        })
        assert status == 401, ("change accepted incorrect old password", status)
        browser.ok("/api/change-password", {
            "username": "alice", "old_password": credentials["alice"], "new_password": changed,
        })
        login(port, credentials["alice"], success=False)
        login(port, changed)
        ldap(alice, changed, "ldapwhoami")
        print("PASS: Authelia password change, incorrect old-password rejection and fresh LDAP bind")

        reset = Browser(port, "auth.ldap.example.test")
        reset.ok("/api/reset-password/identity/start", {"username": "alice"})
        notification = kube("exec", "deploy/authelia", "--", "cat", "/config/notification.txt").stdout
        tokens = re.findall(r"[?&]token=([A-Za-z0-9_.-]+)", notification)
        assert tokens, "password reset notification has no verification token"
        reset.ok("/api/reset-password/identity/finish", {"token": tokens[-1]})
        replacement = secrets.token_urlsafe(24)
        reset.ok("/api/reset-password", {"password": replacement})
        login(port, changed, success=False)
        login(port, replacement)
        ldap(alice, replacement, "ldapwhoami")
        data = ldap(management, credentials["management"], "ldapsearch", "-LLL",
                    "-b", alice, "-s", "base", "mail", "userPassword", "pwdHistory")
        assert not re.search(r"^(userPassword|pwdHistory):", data, re.M)
        print("PASS: Authelia verified password reset through management; history and hashes stay hidden")


if __name__ == "__main__":
    main()
