# Osixia Helm charts

Helm charts for deploying OpenLDAP and phpLDAPadmin on Kubernetes.

| Chart | Description |
| --- | --- |
| [openldap](openldap/README.md) | OpenLDAP with persistence, TLS, replication and scheduled backups |
| [phpldapadmin](phpldapadmin/README.md) | phpLDAPadmin 2 web interface for LDAP administration |

## Install

Add the chart repository:

```bash
helm repo add osixia https://charts.opensource.osixia.net
helm repo update osixia
helm search repo osixia
```

Prepare `my-values.yaml` using the selected chart's README, then install it:

```bash
helm install my-ldap osixia/openldap -f my-values.yaml
```

To use the chart from this checkout, including unreleased changes, use `./openldap`
instead of `osixia/openldap`. See each chart's README for configuration details.

## Examples

See [application examples](examples/README.md) for OpenLDAP and phpLDAPadmin
with Authelia or Keycloak, including generated credentials, verified StartTLS
and integration tests.

## License

[MIT](LICENSE).
