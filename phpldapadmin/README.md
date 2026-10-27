# phpLDAPadmin

phpLDAPadmin 2 with an HTTP service on port 80 forwarding to the image's port
8080. Configure `app.ldap` for the LDAP host, port and TLS mode; use `extraEnv`
and `extraEnvFrom` for additional phpLDAPadmin settings and bind credentials.

See the [Authelia](../examples/ldap-stack-authelia/README.md) and
[Keycloak](../examples/ldap-stack-keycloak/README.md) examples for a real scoped
administrator, search credentials and verified StartTLS. The
OpenLDAP root DN is a virtual identity and cannot log in to phpLDAPadmin 2.

Chart 0.2.1 fixes the container port for the default phpLDAPadmin 2.3.11 image.
