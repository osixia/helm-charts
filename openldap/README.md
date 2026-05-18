# OpenLDAP Helm Chart

Helm chart for the `osixia/openldap` container image.

## Install

```bash
helm install openldap ./openldap
```

## Common values

```yaml
openldap:
  nofile: "8192"
  debugLevel: "256"
  urls: "ldap://:3890 ldaps://:6360 ldapi:///"

upgrade:
  force: false
  migrationLevel: minor

bootstrap:
  organization: "Example Org"
  suffix: "dc=example,dc=org"
  config:
    rootPasswordHashed: "{ARGON2}..."
  database:
    rootDn: "cn=admin,dc=example,dc=org"
    rootPasswordHashed: "{ARGON2}..."
```

If password hash values are empty, the container generates passwords during bootstrap and prints them in logs.

## Custom modules and schemas

Custom OpenLDAP modules and schemas can be mounted from any Kubernetes volume source. The mount paths are fixed to the container defaults:

- modules: `/container/services/openldap/assets/module`
- schemas: `/container/services/openldap/assets/schema`

```yaml
openldap:
  customModules:
    enabled: true
    volume:
      configMap:
        name: openldap-custom-modules
  customSchemas:
    enabled: true
    volume:
      configMap:
        name: openldap-custom-schemas

bootstrap:
  schemas:
    - core.ldif
    - cosine.ldif
    - inetorgperson.ldif
    - custom.ldif
```

## Startup flow

The chart separates bootstrap variables from the long-running OpenLDAP container.

```text
initContainer openldap-bootstrap:
  runtime env + bootstrap env

initContainer openldap-pre-upgrade:
  runtime env only

container openldap:
  runtime env only
```

During an image upgrade, set `preUpgrade.image.tag` to the previously deployed image tag. The pre-upgrade initContainer runs after Kubernetes stops the old pod and before the new OpenLDAP container starts, so the backup is created with the old image against the mounted data:

```yaml
image:
  tag: 2.6.11

preUpgrade:
  image:
    tag: 2.6.10
```

## TLS

Create or reference a Kubernetes Secret containing `cert.crt`, `cert.key`, and `ca.crt`, then enable TLS:

```yaml
bootstrap:
  tls:
    enabled: true
    existingSecret: openldap-tls
```

TLS bootstrap environment variables are generated from `bootstrap.tls:`. The mounted files are exposed to OpenLDAP as `cert.crt`, `cert.key`, and `ca.crt` under `/container/services/openldap/assets/certs`.

## Replication

Replication is controlled by `bootstrap.replication.mode`.

- `auto`: enabled when `replicaCount > 1`, disabled when `replicaCount = 1`
- `enabled`: always enabled
- `disabled`: always disabled

The chart generates stable StatefulSet peer hostnames and injects `OPENLDAP_URLS` dynamically for each pod.

```yaml
replicaCount: 2

bootstrap:
  replication:
    mode: auto
    dataReadonlyPassword: "change-me"
```

Generated replication hosts use this form:

```text
ldap://openldap-0.openldap-headless.<namespace>.svc.cluster.local:3890
ldap://openldap-1.openldap-headless.<namespace>.svc.cluster.local:3890
```

For custom topologies, set `bootstrap.replication.hosts` explicitly.

When replication is enabled, the chart adds pod anti-affinity by default so replicas prefer different Kubernetes nodes:

```yaml
podAntiAffinity:
  enabled: true
  type: preferred
  topologyKey: kubernetes.io/hostname
```

Use `type: required` to make node spreading mandatory, or set `podAntiAffinity.enabled=false` to disable this behavior. If you set the top-level `affinity` value yourself, your custom affinity fully replaces the chart default.

## Persistence

The chart creates separate PVCs for:

- OpenLDAP config: `/etc/openldap/slapd.d`
- OpenLDAP data: `/var/lib/openldap/openldap-data`
- Backups: `/var/lib/openldap/openldap-backups`

Bootstrap only runs when the config and data volumes are empty.
