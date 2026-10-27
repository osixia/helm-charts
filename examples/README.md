# LDAP application examples

| Example | Components |
| --- | --- |
| [ldap-stack-authelia](ldap-stack-authelia/README.md) | OpenLDAP, phpLDAPadmin and the official Authelia chart |
| [ldap-stack-keycloak](ldap-stack-keycloak/README.md) | OpenLDAP, phpLDAPadmin, the community keycloakx chart using the official Keycloak image, and PostgreSQL |

Each example uses its own namespace, generated credentials and CA, with mandatory
StartTLS between LDAP clients and OpenLDAP. Install one example independently;
its README includes instructions and a reproducible kind integration test.
