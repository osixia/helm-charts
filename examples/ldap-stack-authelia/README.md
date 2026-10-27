# OpenLDAP, phpLDAPadmin and Authelia

Three independent Helm releases in the same namespace: the local OpenLDAP and
phpLDAPadmin charts, and the [official Authelia chart](https://www.authelia.com/integration/kubernetes/chart/)
pinned to **0.11.22** (Authelia **4.39.24**).

The example creates `ou=users`, `ou=groups` and `ou=services` under
`dc=example,dc=org`. phpLDAPadmin uses a real directory administrator;
Authelia uses the scoped management account. Both verify the OpenLDAP certificate
and require StartTLS on `ldap://openldap:389` before binding. Plain LDAP binds
are refused, and the separate LDAPS listener is disabled.

| Identity | Purpose |
| --- | --- |
| `cn=admin,dc=example,dc=org` | Data root: recovery and maintenance; bypasses data ACLs |
| `cn=admin,cn=config` | Config root: server configuration, ACLs and root passwords |
| `cn=admin,ou=services,dc=example,dc=org` | phpLDAPadmin login: administer users and groups; cannot access config or manage service accounts |
| `cn=management,ou=services,dc=example,dc=org` | Authelia: read users/groups and reset user passwords; cannot read password hashes/history |
| `uid=alice,ou=users,dc=example,dc=org` | Example user, member of `cn=users,ou=groups,dc=example,dc=org` |

## Install

Requires Helm 3, kubectl, Python 3, OpenSSL and a Kubernetes cluster with dynamic
volume provisioning. Run from this directory against an **empty installation**.
The image `osixia/openldap:2.6.15-rc` must be published or loaded into your cluster;
its build requires `osixia/baseimage:alpine-2.1.0`.

```bash
python3 prepare.py
kubectl create namespace ldap-stack-authelia
kubectl -n ldap-stack-authelia apply -f generated/resources.json

helm install openldap ../../openldap -n ldap-stack-authelia -f openldap.yaml --wait
helm install phpldapadmin ../../phpldapadmin -n ldap-stack-authelia -f phpldapadmin.yaml --wait

source versions.env
helm install authelia authelia --repo https://charts.authelia.com \
  --version "${AUTHELIA_CHART_VERSION}" -n ldap-stack-authelia -f authelia.yaml --wait
```

`generated/` is ignored by Git and created with private permissions. It contains
random credentials, Kubernetes Secrets, the sample user/group LDIF and a local CA
valid for 30 days. Read `generated/credentials.json` for the administrator and
Alice passwords. Keep this directory safe; the generator refuses to overwrite it.
Recreating Secrets does **not** rotate passwords in an existing LDAP database:
bootstrap only runs on empty config/data volumes.

The bootstrap hashes are distinct from the plaintext passwords applications need
for binds. phpLDAPadmin stores the directory administrator's search credentials
in its Secret because that identity can read its own real entry; management
cannot read the services branch. This phpLDAPadmin instance is for directory
administrators. Root DNs do not have real entries and cannot log in to phpLDAPadmin 2.

For local phpLDAPadmin access:

```bash
kubectl -n ldap-stack-authelia port-forward svc/phpldapadmin 8080:80
```

Open `http://localhost:8080` and log in with the full directory administrator DN
and its generated password. HTTP here is a local port-forward; LDAP stays on
verified StartTLS.

## Expose Authelia and use real notifications

Configure your HTTPS ingress/proxy for `auth.ldap.example.test`, with a browser
trusted certificate. The cookie domain is `ldap.example.test`. Change these
names in `authelia.yaml` to your domain and enable the ingress supported by your
cluster. Also expose phpLDAPadmin over HTTPS when accessing it remotely.
The chart's `ingress.enabled` can enable the standard Kubernetes Ingress.

The example keeps Authelia's SQLite database and filesystem notifications on a
PVC. Reset links and session-elevation codes can be read for local testing with:

```bash
kubectl -n ldap-stack-authelia exec deploy/authelia -- cat /config/notification.txt
```

For real users, replace `configMap.notifier.filesystem` with SMTP. Authelia sends
verification messages to the user's LDAP `mail` attribute. Keep the Authelia
storage encryption key stable and back up its database alongside OpenLDAP.

The sample policy permits group `users` to access `app.ldap.example.test` with
one-factor authentication. Connect that application's reverse proxy to Authelia
using the [official proxy integration](https://www.authelia.com/integration/proxies/introduction/).
The policy alone does not protect an application. Change it to `two_factor` and
enrol a second factor when you want MFA. phpLDAPadmin keeps its own LDAP login.

Replace the local CA with your certificates and remove the sample Alice/group
LDIF when adapting this to your directory. For a different LDAP service name,
also update its certificate SAN and both clients' hosts. Privileged accounts
belong in `ou=services`, outside the user/group branches the admin can write.
Management/admin password operations bypass LDAP password quality/history checks.
Authelia therefore enforces a minimum password length of 12 in this example;
configure its application password policy to match your requirements. Direct
user password changes remain subject to LDAP ppolicy.

## Repeatable integration test

Requires Docker, kind and the installation tools above. The test requires a
disposable kind context, creates a fresh namespace and removes it afterwards.
It never uses the current context of another cluster.

```bash
kind create cluster --name ldap-stack-authelia-test --image kindest/node:v1.34.0 \
  --kubeconfig /tmp/ldap-stack-authelia-test.kubeconfig
KUBECONFIG=/tmp/ldap-stack-authelia-test.kubeconfig bash ../../tests/ldap-stack-authelia/run.sh
kind delete cluster --name ldap-stack-authelia-test
```

For an unpublished local OpenLDAP build, set
`OPENLDAP_TEST_IMAGE=openldap-review:baseimage-2.1.0` (or your own local tag).
`KIND_CLUSTER` and `TEST_NAMESPACE` can select another disposable kind cluster
and a fresh namespace. The test loads the images into kind, installs these
values and checks real phpLDAPadmin/Authelia HTTP sessions, LDAP group
authorization, password changes and verified password resets. It also checks
mandatory StartTLS, rejection of untrusted certificates/plaintext binds and the
admin/management ACL restrictions.

The HTTP tests simulate an HTTPS proxy through localhost port-forwards. They
verify the application flows and LDAP TLS, not a particular ingress controller,
public certificate, SMTP delivery or a protected downstream application.
