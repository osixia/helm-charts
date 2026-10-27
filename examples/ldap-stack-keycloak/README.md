# OpenLDAP, phpLDAPadmin and Keycloak

The local OpenLDAP and phpLDAPadmin charts, plus the community
[Codecentric keycloakx chart](https://github.com/codecentric/helm-charts/tree/master/charts/keycloakx)
**7.4.0**, using the official Keycloak **26.8.1** image. A small PostgreSQL
**17.11** deployment with a PVC stores Keycloak's realms, clients and sessions.
This example does not require an operator or a custom Keycloak chart.

Both LDAP clients require StartTLS on `ldap://openldap:389` and verify the CA.
OpenLDAP rejects unencrypted binds; its separate LDAPS listener is disabled.

| Identity | Purpose |
| --- | --- |
| `cn=admin,dc=example,dc=org` | LDAP data root; bypasses data ACLs, reserved for maintenance |
| `cn=admin,cn=config` | LDAP config root; can change server configuration and ACLs |
| `cn=admin,ou=services,dc=example,dc=org` | phpLDAPadmin login; manages users/groups, without config or service-account access |
| `cn=keycloak,ou=services,dc=example,dc=org` | Keycloak bind; reads users/groups and changes user passwords, without hash/history reads or profile/group writes |
| `uid=alice,ou=users,dc=example,dc=org` | Example LDAP user and member of group `users` |
| Keycloak `admin` in realm `master` | Keycloak bootstrap administrator; separate from every LDAP identity |

## Install

Requires Helm 3, kubectl, Python 3, OpenSSL and dynamic volume provisioning.
Run from this directory for a new installation. Publish
`osixia/openldap:2.6.15-rc` first, or load your local image into the cluster.
Its build requires `osixia/baseimage:alpine-2.1.0`.

```bash
python3 prepare.py
kubectl create namespace ldap-stack-keycloak
kubectl -n ldap-stack-keycloak apply -f generated/resources.json

helm install openldap ../../openldap -n ldap-stack-keycloak -f openldap.yaml --wait
helm install phpldapadmin ../../phpldapadmin -n ldap-stack-keycloak -f phpldapadmin.yaml --wait
kubectl -n ldap-stack-keycloak apply -f postgres.yaml
kubectl -n ldap-stack-keycloak rollout status deploy/keycloak-postgres

source versions.env
helm install keycloak keycloakx --repo https://codecentric.github.io/helm-charts \
  --version "${KEYCLOAK_CHART_VERSION}" -n ldap-stack-keycloak -f keycloak.yaml --wait --timeout 5m
```

`generated/credentials.json` contains distinct random passwords for LDAP roots,
directory admin, the Keycloak LDAP bind, Alice, PostgreSQL and the Keycloak
bootstrap administrator. The directory is private, ignored by Git and cannot
be overwritten by the generator. It also contains a local CA valid for 30 days.
The `management` password is for Keycloak's LDAP bind; `keycloak_admin` is for
the separate Keycloak administration console.
Bootstrap only applies to empty LDAP volumes. Changing the generated Secret
does not rotate passwords already stored in LDAP or PostgreSQL.

## Try the applications

In separate terminals:

```bash
kubectl -n ldap-stack-keycloak port-forward svc/phpldapadmin 8080:80
kubectl -n ldap-stack-keycloak port-forward svc/keycloak-http 18080:80
```

- phpLDAPadmin: <http://localhost:8080>, full directory admin DN and the `admin`
  password from the credentials file.
- Keycloak admin console: <http://localhost:18080/admin/>, username `admin` and
  the generated `keycloak_admin` password.
- Keycloak account console: <http://localhost:18080/realms/ldap-example/account/>,
  username `alice` and the generated `alice` password.

The realm `ldap-example` imports automatically on first start. Its LDAP provider
uses `entryUUID` for identity, `uid` for login, `givenName`/`sn`/`mail` for the
profile and `groupOfNames`/`member` for group membership. LDAP passwords are
checked by LDAP and are not imported into Keycloak.

User/group administration stays in phpLDAPadmin. LDAP federation is `WRITABLE`
so Keycloak can change passwords, while profile and group mappers are read-only
and LDAP ACLs reject other writes. Registration is disabled. Keycloak's realm
policy requires at least 12 password characters because the management bind's
privileged password operations bypass LDAP quality/history checks.

A public sample OIDC client, `ldap-example`, requires authorization code flow
with PKCE S256 and accepts the local callback `http://localhost:18080/callback`.
It adds LDAP groups to tokens and UserInfo. No application is installed at that
callback; it is used by the automated test. Add your own client/redirect URIs
when connecting an application.

`realm.json` contains an environment placeholder for the LDAP password; the
actual password comes from a Secret. Existing realms are skipped on restart:
editing the JSON does not update an existing realm. Use the admin console/API
for subsequent changes. Keep the PostgreSQL volume and its credentials stable.

## Adapt to production

HTTP endpoints and dynamic hostname handling are for localhost port-forwards.
Before exposing Keycloak, configure its public HTTPS hostname and trusted proxy
headers, or terminate TLS directly in Keycloak; expose phpLDAPadmin over HTTPS
with restricted access too. LDAP stays on verified StartTLS in either case.

Replace the local CA with your managed certificates and remove the sample Alice
LDIF. Back up PostgreSQL as well as LDAP. The included PostgreSQL deployment is
a single-instance example; use your managed database or your usual database
operator for production. Its connection uses the internal cluster network;
configure PostgreSQL TLS for your production database connection.

MFA and email delivery are not enabled in this example. Configure Keycloak SMTP
before enabling forgot-password emails, and enrol a second factor as required.
The bootstrap Keycloak admin is temporary: create your named administrator and
remove it afterwards, following the Keycloak administration guide.

## Repeatable integration test

Requires Docker and kind in addition to the installation tools:

```bash
kind create cluster --name ldap-stack-keycloak-test --image kindest/node:v1.34.0 \
  --kubeconfig /tmp/ldap-stack-keycloak-test.kubeconfig
KUBECONFIG=/tmp/ldap-stack-keycloak-test.kubeconfig bash ../../tests/ldap-stack-keycloak/run.sh
kind delete cluster --name ldap-stack-keycloak-test
```

For a local image, also set `OPENLDAP_TEST_IMAGE=openldap-review:baseimage-2.1.0`
or your own built tag. `KIND_CLUSTER` and `TEST_NAMESPACE` can select another
disposable kind cluster and a fresh namespace. The test installs this example
and removes its namespace afterwards.

Checks cover mandatory StartTLS and certificate validation, LDAP ACL isolation,
phpLDAPadmin login, OIDC code flow with PKCE, LDAP profiles/groups and both
administrative password resets and browser password changes reaching LDAP.
The test uses localhost HTTP port-forwards; it does not validate an ingress,
public HTTPS certificate, SMTP delivery, MFA or a downstream application.
