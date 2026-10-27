#!/usr/bin/env python3
"""Generate private, disposable credentials and a local CA for the example."""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess


def password_hash(password):
    salt = secrets.token_bytes(16)
    return "{SSHA}" + base64.b64encode(
        hashlib.sha1(password.encode() + salt).digest() + salt
    ).decode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "generated")
    args = parser.parse_args()
    os.umask(0o077)
    # Refuse to overwrite credentials for an already bootstrapped directory.
    args.output.mkdir(parents=True, exist_ok=False)
    output = args.output.resolve()

    def openssl(*arguments):
        subprocess.run(["openssl", *arguments], cwd=output, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    openssl("req", "-x509", "-newkey", "rsa:3072", "-nodes", "-sha256",
            "-days", "30", "-subj", "/CN=LDAP Example CA",
            "-addext", "basicConstraints=critical,CA:TRUE",
            "-keyout", "ca.key", "-out", "ca.crt")
    openssl("req", "-new", "-newkey", "rsa:3072", "-nodes",
            "-subj", "/CN=openldap", "-keyout", "tls.key", "-out", "tls.csr")
    (output / "tls.ext").write_text(
        "subjectAltName=DNS:openldap,DNS:localhost\n"
        "basicConstraints=critical,CA:FALSE\n"
        "keyUsage=critical,digitalSignature,keyEncipherment\n"
        "extendedKeyUsage=serverAuth\n"
    )
    openssl("x509", "-req", "-in", "tls.csr", "-CA", "ca.crt", "-CAkey",
            "ca.key", "-CAcreateserial", "-days", "30", "-sha256", "-extfile",
            "tls.ext", "-out", "tls.crt")

    credentials = {name: secrets.token_urlsafe(24) for name in
                   ("data_root", "config_root", "admin", "management", "alice")}
    credentials["admin_dn"] = "cn=admin,ou=services,dc=example,dc=org"
    items = []

    def secret(name, data, kind="Opaque"):
        items.append({"apiVersion": "v1", "kind": "Secret", "metadata": {"name": name},
                      "type": kind, "stringData": data})

    secret("ldap-tls", {name: (output / name).read_text()
                        for name in ("tls.crt", "tls.key", "ca.crt")}, "kubernetes.io/tls")
    secret("ldap-ca", {"ca.crt": (output / "ca.crt").read_text()})
    secret("ldap-bootstrap", {
        "OPENLDAP_BOOTSTRAP_DATA_ROOT_PASSWORD_HASHED": password_hash(credentials["data_root"]),
        "OPENLDAP_BOOTSTRAP_CONFIG_ROOT_PASSWORD_HASHED": password_hash(credentials["config_root"]),
        "OPENLDAP_BOOTSTRAP_DATA_ADMIN_PASSWORD_HASHED": password_hash(credentials["admin"]),
        "OPENLDAP_BOOTSTRAP_DATA_MANAGEMENT_PASSWORD_HASHED": password_hash(credentials["management"]),
    })
    # DN login still needs a search bind which can read the administrator's entry.
    # Management deliberately cannot read the services branch.
    secret("phpldapadmin-credentials", {
        "APP_KEY": "base64:" + base64.b64encode(secrets.token_bytes(32)).decode(),
        "LDAP_USERNAME": credentials["admin_dn"], "LDAP_PASSWORD": credentials["admin"],
    })
    credentials["keycloak_admin"] = secrets.token_urlsafe(24)
    credentials["postgres"] = secrets.token_urlsafe(24)
    (output / "credentials.json").write_text(json.dumps(credentials, indent=2) + "\n")
    secret("keycloak-credentials", {
        "KC_BOOTSTRAP_ADMIN_USERNAME": "admin",
        "KC_BOOTSTRAP_ADMIN_PASSWORD": credentials["keycloak_admin"],
        "LDAP_BIND_PASSWORD": credentials["management"],
    })
    secret("keycloak-postgres", {"password": credentials["postgres"]})
    items.append({"apiVersion": "v1", "kind": "ConfigMap",
                  "metadata": {"name": "keycloak-realm"},
                  "data": {"ldap-example-realm.json":
                           (Path(__file__).parent / "realm.json").read_text()}})
    ldif = f"""dn: uid=alice,ou=users,dc=example,dc=org
objectClass: inetOrgPerson
uid: alice
cn: Alice Example
sn: Example
givenName: Alice
displayName: Alice Example
mail: alice@example.org
userPassword: {password_hash(credentials['alice'])}

dn: cn=users,ou=groups,dc=example,dc=org
objectClass: groupOfNames
cn: users
member: uid=alice,ou=users,dc=example,dc=org
"""
    items.append({"apiVersion": "v1", "kind": "ConfigMap",
                  "metadata": {"name": "ldap-example-users"},
                  "data": {"90-example-users.ldif": ldif}})
    (output / "resources.json").write_text(json.dumps(
        {"apiVersion": "v1", "kind": "List", "items": items}, indent=2) + "\n")
    print(f"Example resources and credentials written to {output}")


if __name__ == "__main__":
    main()
