# openldap Helm Chart

Helm chart for the [osixia/openldap](https://hub.docker.com/r/osixia/openldap) container image
([source](https://github.com/osixia/container-openldap)).

- [Quick start — 2 minutes](#-quick-start--2-minutes)
- [DN conventions](#dn-conventions)
- [Passwords](#passwords)
- [Protocols](#protocols)
- [TLS](#tls)
- [Persistence](#persistence)
- [Replication](#replication)
- [Overlays](#overlays)
- [Custom volumes](#custom-volumes)
- [Extra environment variables and secrets](#extra-environment-variables-and-secrets)
- [Backup CronJob](#backup-cronjob)
- [Upgrading](#upgrading)
- [Values reference](#values-reference)

---

## ⚡ Quick start — 2 minutes

The only values you **must** change to have a working server:

```yaml
openldap:
  bootstrap:
    organization: "My Org"
    suffix: "dc=my-org,dc=com"
    database:
      rootPasswordHashed: "{ARGON2}..."   # see Passwords section
    config:
      rootPasswordHashed: "{ARGON2}..."
```

Install:

```bash
helm install my-ldap ./openldap -f my-values.yaml
```

Connect from inside the cluster:

```
ldap://my-ldap.<namespace>.svc.cluster.local:389
```

Root DN: `cn=admin,dc=my-org,dc=com` — password: whatever you hashed above.

> On first start, if a `rootPasswordHashed` is empty, the image generates a random
> password and prints it in the pod logs. That password is **not persisted** across
> restarts unless persistence is enabled.

---

## DN conventions

All DN fields in this chart use a **prefix** pattern. You only set the RDN part
(everything before the suffix); the chart appends the suffix automatically.

| Value | Assembled DN |
|---|---|
| `bootstrap.suffix: dc=my-org,dc=com` | *(the base suffix)* |
| `database.rootDnPrefix: cn=admin` | `cn=admin,dc=my-org,dc=com` |
| `database.readonly.dnPrefix: cn=readonly` | `cn=readonly,dc=my-org,dc=com` |
| `config.rootDnPrefix: cn=admin` | `cn=admin,cn=config` |
| `ppolicy.groupDnPrefix: ou=Policies` | `ou=Policies,dc=my-org,dc=com` |
| `ppolicy.default.policyDnPrefix: cn=default` | `cn=default,ou=Policies,dc=my-org,dc=com` |
| `replication.dataReadonlyDnPrefix: cn=replicator` | `cn=replicator,dc=my-org,dc=com` |

---

## Passwords

Passwords are stored as **hashed values**. Generate them with the image:

```bash
# hash a specific password
docker run --rm osixia/openldap run -- openldap-ctl password hash passw0rd

# generate a random password + hash
docker run --rm osixia/openldap run -- openldap-ctl password generate
```

Use the resulting `{ARGON2}...` string in `rootPasswordHashed` fields.

If a `rootPasswordHashed` is left empty, the image generates a random password at
bootstrap time and logs it. **With persistence enabled** the hash is written to the
database and survives restarts; without persistence it is lost on every restart.

---

## Protocols

By default both LDAP (port 3890 internal / 389 service) and LDAPS (port 6360 / 636)
are enabled, along with `ldapi:///`.

```yaml
service:
  ldapPort: 389      # service port → container port 3890
  ldapsPort: 636     # service port → container port 6360

openldap:
  protocols:
    ldap:
      enabled: true
      port: 3890
    ldaps:
      enabled: true
      port: 6360
    ldapi:
      enabled: true
```

Disable LDAPS (plain LDAP only):

```yaml
openldap:
  protocols:
    ldaps:
      enabled: false
```

---

## TLS

1. Create a Kubernetes secret with your certificates:

```bash
kubectl create secret generic my-ldap-tls \
  --from-file=tls.crt=server.crt \
  --from-file=tls.key=server.key \
  --from-file=ca.crt=ca.crt
```

2. Enable TLS in values:

```yaml
tlsSecret:
  existingSecret: my-ldap-tls
  keys:
    cert: tls.crt   # key name inside the secret
    key: tls.key
    ca: ca.crt

openldap:
  bootstrap:
    tls:
      enabled: true
      required: false        # true = reject non-TLS connections
      verifyClient: allow    # allow | demand | never
      protocolMin: "3.4"     # TLS 1.3 = "3.4"
```

The secret is mounted at `/container/services/openldap/assets/certs/` in every
container (init, pre-upgrade, main).

---

## Persistence

Persistence is enabled by default. Three PVCs are created per pod:

| PVC prefix | Mount path | Default size |
|---|---|---|
| `conf-<release>-0` | `/etc/openldap/slapd.d` | 1 Gi |
| `data-<release>-0` | `/var/lib/openldap/openldap-data` | 8 Gi |
| `backups-<release>-0` | `/var/lib/openldap/openldap-backups` | 8 Gi |

```yaml
persistence:
  enabled: true
  storageClass: ""       # leave empty for default StorageClass
  accessModes:
    - ReadWriteOnce
  conf:
    size: 1Gi
  data:
    size: 8Gi
  backups:
    size: 8Gi
```

Disable persistence (all data lost on restart — for testing only):

```yaml
persistence:
  enabled: false
```

---

## Replication

Replication is **automatic** when `replicaCount > 1` (mode `auto`).

Minimal multi-replica setup:

```yaml
replicaCount: 2

openldap:
  bootstrap:
    replication:
      mode: auto          # auto | enabled | disabled
      protocol: ldap      # ldap | ldaps
      dataReadonlyDnPrefix: cn=replicator
      dataReadonlyPassword: "changeme"   # plain text, used internally only
```

The chart builds the replication host list automatically from pod FQDNs:

```
ldap://<release>-0.<release>-headless.<namespace>.svc.cluster.local:3890
ldap://<release>-1.<release>-headless.<namespace>.svc.cluster.local:3890
```

Override the host list if your cluster domain differs or you need custom endpoints:

```yaml
openldap:
  bootstrap:
    replication:
      hosts:
        - ldap://ldap1.example.com:3890
        - ldap://ldap2.example.com:3890

clusterDomain: cluster.local   # used for auto-generated FQDNs
```

**Replication with TLS:**

```yaml
openldap:
  bootstrap:
    replication:
      protocol: ldaps
      tls:
        enabled: true
        syncRepl: "starttls=critical tls_reqcert=demand"
```

**Pod scheduling:** with `replicaCount > 1`, `podAntiAffinity` spreads pods across
nodes by default:

```yaml
podAntiAffinity:
  enabled: true
  type: preferred   # preferred | required
  weight: 100
  topologyKey: kubernetes.io/hostname
```

---

## Overlays

All overlays are disabled by default. Enable them under `openldap.bootstrap`.

### Password Policy (ppolicy)

```yaml
openldap:
  bootstrap:
    ppolicy:
      enabled: true
      hashClearText: true
      useLockout: true
      groupDnPrefix: "ou=Policies"
      default:
        policyDnPrefix: "cn=default"
        minLength: 12
        maxAge: 7776000        # seconds (~90 days)
        maxFailure: 5
        lockoutDuration: 900   # seconds (15 min)
```

### Referential Integrity (refint)

```yaml
openldap:
  bootstrap:
    refint:
      enabled: true
      attributes: "member uniqueMember manager owner"
```

### MemberOf

```yaml
openldap:
  bootstrap:
    memberof:
      enabled: true
      groupObjectClass: groupOfNames
      memberAttribute: member
      memberOfAttribute: memberOf
```

### Unique attribute enforcement

```yaml
openldap:
  bootstrap:
    unique:
      enabled: true
      uris: "ldap:///?uid?sub ldap:///?mail?sub"
```

### Monitor backend

```yaml
openldap:
  bootstrap:
    monitor:
      enabled: true
      readonly:
        enabled: true
        dnPrefix: "cn=readonly-monitor"
        passwordHashed: "{ARGON2}..."
```

---

## Custom volumes

All custom volume values default to `{}` (disabled). Define any valid Kubernetes
volume spec to enable mounting.

### Custom modules

Mounted at `/container/services/openldap/assets/module` in **all** containers
(init, pre-upgrade, main).

```yaml
customModulesVolume:
  configMap:
    name: my-ldap-modules
```

### Custom schemas

Mounted at `/container/services/openldap/assets/schema` in **all** containers.

```yaml
customSchemasVolume:
  configMap:
    name: my-ldap-schemas
```

### Bootstrap LDIF — config

Mounted at `/container/services/openldap-bootstrap/assets/ldif/config/custom`
in the **bootstrap init container only**.

```yaml
bootstrapCustomConfigLdifVolume:
  configMap:
    name: my-ldap-config-ldif
```

### Bootstrap LDIF — data

Mounted at `/container/services/openldap-bootstrap/assets/ldif/data/custom`
in the **bootstrap init container only**.

```yaml
bootstrapCustomDataLdifVolume:
  configMap:
    name: my-ldap-data-ldif
```

### Extra volumes

`extraVolumes` / `extraVolumeMounts` are added to **all** containers.

```yaml
extraVolumes:
  - name: my-volume
    configMap:
      name: my-config

extraVolumeMounts:
  - name: my-volume
    mountPath: /my/path
    readOnly: true
```

---

## Extra environment variables and secrets

### Bootstrap secret

The chart always generates a `<release>-bootstrap-secret` Secret containing all
`OPENLDAP_BOOTSTRAP_*` variables. It is loaded only by the bootstrap init container —
the main container never sees it.

To override specific bootstrap variables, use `bootstrapEnvSecret.env` to set them
directly in values (the chart generates a second secret from them):

```yaml
bootstrapEnvSecret:
  env:
    OPENLDAP_BOOTSTRAP_DATA_ROOT_PASSWORD_HASHED: "{ARGON2}..."
```

Or reference an existing secret (e.g. from External Secrets Operator, Vault, or
Sealed Secrets) with `bootstrapEnvSecret.existingSecret`. `env` and `existingSecret`
are mutually exclusive — `existingSecret` takes priority. Either way, the override
secret is loaded **after** the auto-generated one so its values win:

```yaml
bootstrapEnvSecret:
  existingSecret: my-ldap-bootstrap-overrides
```

### Plain environment variables

```yaml
extraEnv:
  - name: MY_VAR
    value: "my-value"
```

### Secret environment variables

`extraEnvSecret` is loaded into **all** containers (init, pre-upgrade, main). Use it
for runtime secrets unrelated to bootstrap (e.g. custom application credentials).

Create a secret:

```bash
kubectl create secret generic my-ldap-env \
  --from-literal=MY_VAR=my-value
```

Reference it:

```yaml
extraEnvSecret:
  existingSecret: my-ldap-env
```

If `existingSecret` is empty no secret is mounted. The secret is loaded with
`optional: true` so a missing secret does not block startup.

---

## Backup CronJob

The backup CronJob is disabled by default. It mounts the same PVCs as the
StatefulSet (requires `persistence.enabled: true`) and runs `openldap-ctl backup`
on a schedule.

```yaml
backupCronJob:
  enabled: true
  schedule: "15 2 * * *"    # 02:15 UTC daily
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  command:
    - /bin/sh
    - -ec
    - container run -- openldap-ctl backup "$(date -I)-${OPENLDAP_VERSION}-openldap-cron" --clean 15
  resources: {}
```

`--clean 15` removes backup files older than 15 days. Adjust or remove as needed.

Restore a backup manually:

```bash
kubectl exec -it <pod> -- container run -- openldap-ctl restore <backup-name> --force
```

---

## Upgrading

### Patch / minor upgrades (v2.x → v2.y)

The chart runs an **openldap-pre-upgrade** init container before the main container
starts. It uses the *previous* image version to perform any required migration.

You **must** set `previousImage.tag` during upgrades:

```yaml
image:
  tag: 2.6.11

previousImage:
  tag: 2.6.10   # the version currently running
```

Control how aggressively migrations are applied:

```yaml
openldap:
  upgrade:
    migrationLevel: minor   # patch | minor | major
    force: false
```

Remove `previousImage.tag` after the upgrade completes.

### v1 → v2 (breaking change)

> ⚠️ v2 is a **breaking release**. There is no automatic migration from v1. A manual
> migration is required. See the
> [container-openldap documentation](https://github.com/osixia/container-openldap)
> for the migration procedure.

---

## Values reference

### Top-level

| Key | Default | Description |
|---|---|---|
| `replicaCount` | `1` | Number of replicas |
| `clusterDomain` | `cluster.local` | Kubernetes cluster domain, used to build pod FQDNs |
| `image.repository` | `osixia/openldap` | Container image |
| `image.tag` | `2.6.10-alpha` | Image tag |
| `image.pullPolicy` | `IfNotPresent` | Pull policy |
| `previousImage.repository` | `""` | Previous image repository (defaults to `image.repository`) |
| `previousImage.tag` | `""` | Previous image tag — **required during upgrades** |
| `previousImage.pullPolicy` | `IfNotPresent` | Previous image pull policy |
| `imagePullSecrets` | `[]` | Image pull secrets |
| `nameOverride` | `""` | Override chart name |
| `fullnameOverride` | `""` | Override full release name |

### Service account

| Key | Default | Description |
|---|---|---|
| `serviceAccount.create` | `true` | Create a ServiceAccount |
| `serviceAccount.annotations` | `{}` | Annotations for the ServiceAccount |
| `serviceAccount.name` | `""` | Name override (defaults to release fullname) |

### Pod

| Key | Default | Description |
|---|---|---|
| `podAnnotations` | `{}` | Pod annotations |
| `podLabels` | `{}` | Extra pod labels |
| `podSecurityContext.fsGroup` | `911` | Pod fsGroup |
| `securityContext.runAsUser` | `911` | Container user |
| `securityContext.runAsGroup` | `911` | Container group |
| `securityContext.runAsNonRoot` | `true` | Enforce non-root |
| `resources` | `{}` | CPU / memory requests and limits |
| `nodeSelector` | `{}` | Node selector |
| `tolerations` | `[]` | Tolerations |
| `affinity` | `{}` | Affinity (overrides podAntiAffinity) |
| `terminationGracePeriodSeconds` | `60` | Grace period |
| `updateStrategy.type` | `RollingUpdate` | StatefulSet update strategy |

### Services

| Key | Default | Description |
|---|---|---|
| `service.type` | `ClusterIP` | Service type |
| `service.annotations` | `{}` | Service annotations |
| `service.ldapPort` | `389` | Service LDAP port |
| `service.ldapsPort` | `636` | Service LDAPS port |
| `headlessService.annotations` | `{}` | Headless service annotations |

### Pod anti-affinity

| Key | Default | Description |
|---|---|---|
| `podAntiAffinity.enabled` | `true` | Enable automatic anti-affinity (multi-replica) |
| `podAntiAffinity.type` | `preferred` | `preferred` or `required` |
| `podAntiAffinity.weight` | `100` | Weight for preferred anti-affinity |
| `podAntiAffinity.topologyKey` | `kubernetes.io/hostname` | Topology key |

### TLS secret

| Key | Default | Description |
|---|---|---|
| `tlsSecret.existingSecret` | `""` | Secret name containing TLS certificates |
| `tlsSecret.keys.cert` | `tls.crt` | Key name for the certificate |
| `tlsSecret.keys.key` | `tls.key` | Key name for the private key |
| `tlsSecret.keys.ca` | `ca.crt` | Key name for the CA certificate |

### Bootstrap secret

| Key | Default | Description |
|---|---|---|
| `bootstrapEnvSecret.existingSecret` | `""` | Existing secret loaded after the auto-generated bootstrap secret (overrides its values) |
| `bootstrapEnvSecret.env` | `{}` | Env vars rendered into a generated override secret (ignored if `existingSecret` is set) |

### Extra env / secrets

| Key | Default | Description |
|---|---|---|
| `extraEnv` | `[]` | Extra environment variables (all containers) |
| `extraEnvSecret.existingSecret` | `""` | Secret name loaded as `envFrom` (all containers) |
| `extraEnvSecret.env` | `{}` | Env vars written into a generated secret (not used if `existingSecret` is set) |

### Probes

| Key | Default | Description |
|---|---|---|
| `livenessProbe.enabled` | `true` | Enable liveness probe |
| `livenessProbe.*` | tcpSocket on `ldap` port | Standard Kubernetes probe fields |
| `readinessProbe.enabled` | `true` | Enable readiness probe |
| `readinessProbe.*` | tcpSocket on `ldap` port | Standard Kubernetes probe fields |

### Persistence

| Key | Default | Description |
|---|---|---|
| `persistence.enabled` | `true` | Enable PVC-backed storage |
| `persistence.storageClass` | `""` | StorageClass (empty = default) |
| `persistence.accessModes` | `[ReadWriteOnce]` | Access modes |
| `persistence.conf.size` | `1Gi` | Config PVC size |
| `persistence.data.size` | `8Gi` | Data PVC size |
| `persistence.backups.size` | `8Gi` | Backups PVC size |

### OpenLDAP

| Key | Default | Description |
|---|---|---|
| `openldap.nofile` | `8192` | `ulimit -n` for slapd |
| `openldap.debugLevel` | `256` | slapd debug level |
| `openldap.protocols.ldap.enabled` | `true` | Enable LDAP listener |
| `openldap.protocols.ldap.port` | `3890` | Internal LDAP port |
| `openldap.protocols.ldaps.enabled` | `true` | Enable LDAPS listener |
| `openldap.protocols.ldaps.port` | `6360` | Internal LDAPS port |
| `openldap.protocols.ldapi.enabled` | `true` | Enable LDAPI socket |
| `openldap.preUpgrade.enabled` | `true` | Run pre-upgrade init container |
| `openldap.upgrade.force` | `false` | Force upgrade (allow downgrades) |
| `openldap.upgrade.migrationLevel` | `minor` | `patch` / `minor` / `major` |

### Bootstrap

| Key | Default | Description |
|---|---|---|
| `openldap.bootstrap.organization` | `Example Org` | Organization name |
| `openldap.bootstrap.suffix` | `dc=example,dc=org` | Base DN suffix |
| `openldap.bootstrap.modules` | see values.yaml | OpenLDAP modules loaded |
| `openldap.bootstrap.schemas` | see values.yaml | LDIF schemas imported |
| `openldap.bootstrap.global.sizeLimit` | `500` | Global size limit |
| `openldap.bootstrap.global.timeLimit` | `120` | Global time limit |
| `openldap.bootstrap.global.idleTimeout` | `3600` | Global idle timeout |
| `openldap.bootstrap.frontend.passwordHash` | `{ARGON2}` | Default password hash scheme |
| `openldap.bootstrap.config.rootDnPrefix` | `cn=admin` | Config root DN prefix (assembled: `<prefix>,cn=config`) |
| `openldap.bootstrap.config.rootPasswordHashed` | `""` | Config root password hash |
| `openldap.bootstrap.database.maxSize` | `10737418240` | MDB max size (bytes) |
| `openldap.bootstrap.database.rootDnPrefix` | `cn=admin` | Data root DN prefix |
| `openldap.bootstrap.database.rootPasswordHashed` | `""` | Data root password hash |
| `openldap.bootstrap.database.readonly.enabled` | `false` | Create read-only data account |
| `openldap.bootstrap.database.readonly.dnPrefix` | `cn=readonly` | Read-only account prefix |
| `openldap.bootstrap.database.readonly.passwordHashed` | `""` | Read-only account password hash |
| `openldap.bootstrap.monitor.enabled` | `false` | Enable monitor backend |
| `openldap.bootstrap.monitor.readonly.*` | — | Monitor read-only account |
| `openldap.bootstrap.tls.enabled` | `false` | Configure TLS during bootstrap |
| `openldap.bootstrap.tls.required` | `false` | Enforce TLS-only access |
| `openldap.bootstrap.tls.verifyClient` | `allow` | `olcTLSVerifyClient` value |
| `openldap.bootstrap.tls.protocolMin` | `3.4` | `olcTLSProtocolMin` value |
| `openldap.bootstrap.replication.mode` | `auto` | `auto` / `enabled` / `disabled` |
| `openldap.bootstrap.replication.protocol` | `ldap` | Replication protocol (`ldap` / `ldaps`) |
| `openldap.bootstrap.replication.hosts` | `[]` | Override replication host list |
| `openldap.bootstrap.replication.syncprovCheckpoint` | `100 10` | syncprov checkpoint |
| `openldap.bootstrap.replication.dataReadonlyDnPrefix` | `cn=replicator` | Replication account prefix |
| `openldap.bootstrap.replication.dataReadonlyPassword` | `""` | Replication account password (plain) |
| `openldap.bootstrap.replication.tls.enabled` | `false` | Enable TLS in replication config |
| `openldap.bootstrap.replication.tls.syncRepl` | `starttls=critical tls_reqcert=demand` | Extra syncrepl TLS options |

### Custom volumes

| Key | Default | Description |
|---|---|---|
| `customModulesVolume` | `{}` | Volume spec for custom modules (all containers) |
| `customSchemasVolume` | `{}` | Volume spec for custom schemas (all containers) |
| `bootstrapCustomConfigLdifVolume` | `{}` | Volume spec for bootstrap config LDIF (init only) |
| `bootstrapCustomDataLdifVolume` | `{}` | Volume spec for bootstrap data LDIF (init only) |
| `extraVolumes` | `[]` | Extra volumes (all containers) |
| `extraVolumeMounts` | `[]` | Extra volume mounts (all containers) |

### Backup CronJob

| Key | Default | Description |
|---|---|---|
| `backupCronJob.enabled` | `false` | Enable backup CronJob |
| `backupCronJob.schedule` | `15 2 * * *` | Cron schedule |
| `backupCronJob.successfulJobsHistoryLimit` | `3` | Successful jobs to keep |
| `backupCronJob.failedJobsHistoryLimit` | `3` | Failed jobs to keep |
| `backupCronJob.command` | see values.yaml | Command run by the backup job |
| `backupCronJob.resources` | `{}` | CPU / memory for backup job |
