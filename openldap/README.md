# openldap Helm Chart

Helm chart for the [osixia/openldap](https://hub.docker.com/r/osixia/openldap) container image
([source](https://github.com/osixia/container-openldap)).

- [Quick start — 2 minutes](#-quick-start--2-minutes)
- [DN conventions](#dn-conventions)
- [Passwords](#passwords)
- [Directory tree, admin and management](#directory-tree-admin-and-management)
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

The default image is `2.6.15-beta`. Last-bind tracking, inactivity limits, progressive
lockouts, the new global request limits and TLS reload require an image containing
the subsequent `develop` changes; set `image.tag` to that release when available.

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
| `database.tree.servicesDnPrefix: ou=services` | `ou=services,dc=my-org,dc=com` |
| `database.management.dnPrefix: cn=management` | `cn=management,ou=services,dc=my-org,dc=com` |
| `database.admin.dnPrefix: cn=admin` | `cn=admin,ou=services,dc=my-org,dc=com` |
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

## Directory tree, admin and management

Enable the users/groups/services tree and the scoped management account for
applications such as Authelia:

```yaml
openldap:
  bootstrap:
    database:
      tree:
        enabled: true
      management:
        enabled: true
        passwordHashed: "{ARGON2}..."
```

The default account DN is `cn=management,ou=services,<suffix>`. Its `dnPrefix` is
combined with `tree.servicesDnPrefix` and the suffix, so changing the services
branch also moves the account. It can read the users/groups branches and reset
user passwords, with no other writes or password hash/history reads by default.
`hiddenAttributes` and `hiddenPpolicyAttributes` are comma-separated lists; the
latter is added only with ppolicy, and the combined list must not be empty.

Tree and account creation are independent and disabled by default. If custom
LDIFs create the OUs, leave `tree.enabled=false` and create the parent entries
before `80-database-management-account.ldif`. These options apply only on an
empty config/data volume. With ppolicy, management resets bypass password quality,
history-reuse and minimum-age checks: enforce these requirements in the application.

The account hash can also be supplied through `bootstrapEnvSecret` using
`OPENLDAP_BOOTSTRAP_DATA_MANAGEMENT_PASSWORD_HASHED`.

### Root versus directory admin

Root and admin are different LDAP identities, with different passwords and rights:

| Account | Default DN | Use |
|---|---|---|
| Data root | `cn=admin,<suffix>` | Data maintenance/recovery; bypasses all ACLs in the data database |
| Config root | `cn=admin,cn=config` | Server configuration; can change ACLs and root passwords |
| Directory admin | `cn=admin,ou=services,<suffix>` | Day-to-day user/group administration in phpLDAPadmin; obeys scoped ACLs |
| Management | `cn=management,ou=services,<suffix>` | Application user/group reads and password resets, for example Authelia |

Each root DN bypasses ACLs only in its own database. The data root does not
automatically have access to `cn=config`; reserve config root for server maintenance.
Neither root DN needs a real directory entry. The scoped admin has a real entry,
as required for normal login to phpLDAPadmin 2.

To create the directory administrator on a fresh installation:

```yaml
openldap:
  bootstrap:
    database:
      tree:
        enabled: true
      admin:
        enabled: true
        passwordHashed: "{ARGON2}..."
```

The admin DN uses `admin.dnPrefix`, the services branch prefix and the suffix.
It can create/edit/rename/delete users and groups and reset user passwords.
It cannot read password hashes/history, change service accounts or its own account,
or access `cn=config`. Use data root to rotate the admin password. With ppolicy,
admin resets have the same password-rule bypass as management resets described above.

Use `LDAP_LOGIN_ATTR=dn` and `LDAP_LOGIN_OBJECTCLASS=organizationalRole` in
phpLDAPadmin, with the administrator's full DN and password. Configure the
application's search credentials and TLS separately. The admin hash may also
be supplied through `bootstrapEnvSecret` as `OPENLDAP_BOOTSTRAP_DATA_ADMIN_PASSWORD_HASHED`.

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
container (init, pre-upgrade, main). Set `openldap.tlsReload.enabled=true` to add
a watcher sidecar sharing the certificates and `/run/container`; it requests a
slapd restart through the main supervisor when certificate contents change.

---

## Persistence

By default, PVCs are created per pod, plus an audit PVC when auditing is enabled:

| PVC prefix | Mount path | Default size |
|---|---|---|
| `conf-<release>-0` | `/etc/openldap/slapd.d` | 1 Gi |
| `data-<release>-0` | `/var/lib/openldap/openldap-data` | 8 Gi |
| `backups-<release>-0` | `/var/lib/openldap/openldap-backups` | 8 Gi |
| `auditlog-<release>-0` | Parent of `openldap.bootstrap.auditlog.file` | 1 Gi |

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
  auditlog:
    size: 1Gi
```

Set `persistence.<conf|data|backups|auditlog>.volume` to use a Kubernetes volume source instead of the generated PVC:

```yaml
persistence:
  data:
    volume:
      persistentVolumeClaim:
        claimName: my-ldap-data
```

An empty `volume` uses a generated PVC, or `emptyDir` when persistence is disabled.
Custom volumes are reused as given by every replica and the backup CronJob.
Audit rotation and remote collection are managed by the deployment.

Use `emptyDir` for volumes without a custom source (for testing):

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

All replicas must use the same replication password. When replication is enabled,
the chart rejects an empty password instead of letting each node generate a
different one. You can also supply it through a shared bootstrap secret:

```yaml
bootstrapEnvSecret:
  existingSecret: my-ldap-bootstrap
```

The secret must contain a non-empty
`OPENLDAP_BOOTSTRAP_REPLICATION_DATA_READONLY_PASSWORD` key. Passwords supplied
through existing secrets or `extraEnv.valueFrom` are checked at bootstrap time,
since their values are unavailable during an offline Helm render.

The chart builds the replication host list automatically from pod FQDNs:

```
ldap://<release>-0.<release>-headless.<namespace>.svc.cluster.local:3890
ldap://<release>-1.<release>-headless.<namespace>.svc.cluster.local:3890
```

With persistence enabled, the bootstrap replication topology is written into the
OpenLDAP config database on disk. Changing `replicaCount` later can leave old
pods with the previous peer list while new pods are bootstrapped with the new
one. For that reason, upgrades fail by default when `replicaCount` changes with
auto-generated replication hosts.

If you have manually migrated the OpenLDAP replication config on all existing
pods, you can opt out of this guard:

```yaml
openldap:
  bootstrap:
    replication:
      allowReplicaCountChange: true
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

**Replication over LDAP with StartTLS (optional):**

```yaml
openldap:
  bootstrap:
    replication:
      protocol: ldap
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
      nothingDnPrefix: "cn=empty-group"
```

`nothingDnPrefix` is combined with the configured LDAP suffix to create the
passwordless replacement role. An empty prefix (the default) disables it.

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

Mounted at `/container/services/openldap/assets/module` in the bootstrap,
pre-upgrade, main and backup containers. Modules are copied to the image's module
directory before bootstrapping, backing up or starting slapd.

```yaml
customModulesVolume:
  configMap:
    name: my-ldap-modules
```

### Custom schemas

Mounted at `/container/services/openldap/assets/schema` in the bootstrap,
pre-upgrade, main and backup containers.

```yaml
customSchemasVolume:
  configMap:
    name: my-ldap-schemas
```

### Bootstrap LDIF

Bootstrap LDIF volumes are mounted only in the **bootstrap init container**:

| Value | Mount path |
|---|---|
| `bootstrapCustomConfigLdifVolume` | `/container/services/openldap-bootstrap/assets/ldif/config/custom` |
| `bootstrapCustomDataLdifVolume` | `/container/services/openldap-bootstrap/assets/ldif/data/custom` |

Create ConfigMaps from local directories containing LDIF files:

```bash
kubectl create configmap my-ldap-config-ldif \
  --from-file=./ldif/config \
  -n <namespace>

kubectl create configmap my-ldap-data-ldif \
  --from-file=./ldif/data \
  -n <namespace>
```

Then mount them during bootstrap:

```yaml
bootstrapCustomConfigLdifVolume:
  configMap:
    name: my-ldap-config-ldif

bootstrapCustomDataLdifVolume:
  configMap:
    name: my-ldap-data-ldif
```

Each file directly inside the source directory becomes one ConfigMap key and is
mounted as a file. `kubectl create configmap --from-file=./dir` does not load
files recursively from nested directories.

Bootstrap LDIF files are applied only when the OpenLDAP config/data volumes are
empty. With persistence enabled, updating these ConfigMaps after the first
successful bootstrap does not automatically reapply the LDIF files.

### Extra volumes

`extraVolumes` / `extraVolumeMounts` are added to **all** containers, including
the backup CronJob.

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
secret is loaded **after** the auto-generated one and `extraEnvSecret` so its
values win. Explicit variables in `extraEnv` take precedence over all secrets:

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

Changes to the runtime ConfigMap or the secret generated from `extraEnvSecret.env`
update checksum annotations on the StatefulSet pod template. With the default
`RollingUpdate` strategy, a subsequent `helm upgrade` restarts the pods to load
the new environment. Custom `podAnnotations` are preserved; the
`checksum/runtime-config` and `checksum/runtime-secret` keys are managed by the chart.

Bootstrap secret contents are excluded from these checksums; changing their
contents does not trigger a restart or reapply bootstrap to existing data.
When using `extraEnvSecret.existingSecret`, restart the pods
explicitly after changing the external secret's contents; the chart does not
watch external secrets.

---

## Backup CronJob

The backup CronJob is disabled by default. It reuses the StatefulSet volumes
(generated PVCs or custom sources) and runs `openldap-ctl backup` on a schedule.
The default command first prepares custom modules and schemas without starting
slapd. TLS certificates and extra volumes are also available to the backup job.

Backup pods use a separate instance label (`<release>-backup`) and the component
label `backup`, so they are excluded from LDAP pod selectors and the LDAP
PodDisruptionBudget's availability count.

The backup pod is scheduled on the same node as the LDAP pod with ordinal `0`,
whose volumes it reuses, so `ReadWriteOnce` volumes remain on a single node.
It inherits `nodeSelector` and `tolerations`. Its required pod affinity targets
LDAP pod `0` in the same namespace; if that pod is absent or has no assigned node,
the backup waits until it can be scheduled alongside it.

```yaml
backupCronJob:
  enabled: true
  schedule: "15 2 * * *"    # 02:15 UTC daily
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  command:
    - /bin/sh
    - -ec
    - >-
      container --exec openldap --skip-process &&
      container run -- openldap-ctl backup "openldap-cron-$(date -I)-${OPENLDAP_VERSION}" --clean 15 --clean-prefix openldap-cron-
  resources: {}
```

`--clean 15 --clean-prefix openldap-cron-` removes only scheduled backups older
than 15 days, preserving manual and upgrade backups.

If you override `backupCronJob.command`, retain the preparation step when using
custom modules or schemas.

Restore a backup manually:

```bash
kubectl exec -it <pod> -- container run -- openldap-ctl restore <backup-name> --force
```

---

## Upgrading

The chart now targets `osixia/openldap:2.6.15-rc`. Environment overrides must use
`OPENLDAP_BOOTSTRAP_MONITOR` and `OPENLDAP_BOOTSTRAP_AUDITLOG` instead of the old
`*_ENABLED` names. The corresponding chart values remain `monitor.enabled` and
`auditlog.enabled`. Custom management LDIF overrides must use
`63-database-management-acl.ldif` and `80-database-management-account.ldif`.

### Patch / minor upgrades (v2.x → v2.y)

When enabled, the chart runs an **openldap-pre-upgrade** init container **before
the bootstrap init container**. It uses the *previous* image version to prepare
custom modules and schemas and create the migration backup. The new image then
initializes or migrates the data.

You **must** set `previousImage.tag` during upgrades when pre-upgrade is enabled:

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

To run without a pre-upgrade container or a previous image, including during
`helm upgrade`, disable pre-upgrade:

```yaml
openldap:
  preUpgrade:
    enabled: false
```

A fresh installation never requires `previousImage.tag`. If an image change
requires a data migration while pre-upgrade is disabled, provide the required
old-version backup separately before starting the new image.

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
| `image.tag` | `2.6.15-rc` | Image tag |
| `image.pullPolicy` | `IfNotPresent` | Pull policy |
| `previousImage.repository` | `""` | Previous image repository (defaults to `image.repository`) |
| `previousImage.tag` | `""` | Previous image tag — required during upgrades when pre-upgrade is enabled |
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

### Pod disruption budget

| Key | Default | Description |
|---|---|---|
| `podDisruptionBudget.enabled` | `false` | Create a PodDisruptionBudget |
| `podDisruptionBudget.minAvailable` | `1` | Minimum available pods, used when `maxUnavailable` is unset or empty |
| `podDisruptionBudget.maxUnavailable` | `""` | Maximum unavailable pods: an integer (including `0`) or a percentage such as `"50%"`; takes precedence over `minAvailable` |

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
| `persistence.auditlog.size` | `1Gi` | Audit PVC size (when auditing is enabled) |
| `persistence.<conf,data,backups,auditlog>.volume` | `{}` | Custom Kubernetes volume source; overrides generated storage |

### OpenLDAP

| Key | Default | Description |
|---|---|---|
| `openldap.nofile` | `8192` | `ulimit -n` for slapd |
| `openldap.debugLevel` | `256` | slapd debug level |
| `openldap.tlsReload.enabled` | `false` | Enable TLS watcher sidecar; requires TLS |
| `openldap.tlsReload.resources` | `{}` | TLS watcher sidecar resources |
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
| `openldap.bootstrap.modules` | `[]` | Use image defaults, or supply an ordered module list |
| `openldap.bootstrap.schemas` | see values.yaml | LDIF schemas imported |
| `openldap.bootstrap.global.sizeLimit` | `500` | Global size limit |
| `openldap.bootstrap.global.timeLimit` | `120` | Global time limit |
| `openldap.bootstrap.global.idleTimeout` | `3600` | Global idle timeout |
| `openldap.bootstrap.global.writeTimeout` | `0` | Blocked network write timeout in seconds; 0 disables it |
| `openldap.bootstrap.global.connMaxPending` | `100` | Pending requests per anonymous connection |
| `openldap.bootstrap.global.connMaxPendingAuth` | `1000` | Pending requests per authenticated connection |
| `openldap.bootstrap.global.sockbufMaxIncoming` | `262143` | Maximum anonymous LDAP message size in bytes |
| `openldap.bootstrap.global.sockbufMaxIncomingAuth` | `4194303` | Maximum authenticated LDAP message size in bytes |
| `openldap.bootstrap.frontend.passwordHash` | `{ARGON2}` | Default password hash scheme |
| `openldap.bootstrap.config.rootDnPrefix` | `cn=admin` | Config root DN prefix (assembled: `<prefix>,cn=config`) |
| `openldap.bootstrap.config.rootPasswordHashed` | `""` | Config root password hash |
| `openldap.bootstrap.database.maxSize` | `10737418240` | MDB max size (bytes) |
| `openldap.bootstrap.database.lastBind.enabled` | `false` | Track successful authentications in pwdLastSuccess |
| `openldap.bootstrap.database.lastBind.precision` | `3600` | Minimum seconds between last-bind timestamp updates |
| `openldap.bootstrap.database.rootDnPrefix` | `cn=admin` | Data root DN prefix |
| `openldap.bootstrap.database.rootPasswordHashed` | `""` | Data root password hash |
| `openldap.bootstrap.database.tree.enabled` | `false` | Create the users, groups and services OUs |
| `openldap.bootstrap.database.tree.usersDnPrefix` | `ou=users` | Users branch prefix |
| `openldap.bootstrap.database.tree.groupsDnPrefix` | `ou=groups` | Groups branch prefix |
| `openldap.bootstrap.database.tree.servicesDnPrefix` | `ou=services` | Services branch prefix |
| `openldap.bootstrap.database.management.enabled` | `false` | Create the scoped user/group reader and password-reset account |
| `openldap.bootstrap.database.management.dnPrefix` | `cn=management` | Account RDN, prepended to the services branch DN |
| `openldap.bootstrap.database.management.passwordHashed` | `""` | Account password hash; generated if empty when enabled |
| `openldap.bootstrap.database.management.hiddenAttributes` | `userPassword,shadowLastChange` | Comma-separated attributes hidden from the account |
| `openldap.bootstrap.database.management.hiddenPpolicyAttributes` | `pwdHistory` | Additional hidden attributes when ppolicy is enabled |
| `openldap.bootstrap.database.admin.enabled` | `false` | Create a scoped directory administrator for users/groups |
| `openldap.bootstrap.database.admin.dnPrefix` | `cn=admin` | Administrator RDN, prepended to the services branch DN |
| `openldap.bootstrap.database.admin.passwordHashed` | `""` | Administrator password hash; generated if empty when enabled |
| `openldap.bootstrap.database.readonly.enabled` | `false` | Create read-only data account |
| `openldap.bootstrap.database.readonly.dnPrefix` | `cn=readonly` | Read-only account prefix |
| `openldap.bootstrap.database.readonly.passwordHashed` | `""` | Read-only account password hash |
| `openldap.bootstrap.monitor.enabled` | `false` | Enable monitor backend |
| `openldap.bootstrap.monitor.readonly.*` | — | Monitor read-only account |
| `openldap.bootstrap.auditlog.enabled` | `false` | Log successful writes |
| `openldap.bootstrap.ppolicy.default.checkQuality` | `1` | Check password quality when possible |
| `openldap.bootstrap.ppolicy.default.minDelay` | `0` | Initial progressive lockout in seconds; 0 disables it |
| `openldap.bootstrap.ppolicy.default.maxDelay` | `0` | Progressive lockout cap; requires 0 < minDelay <= maxDelay and lockout=true |
| `openldap.bootstrap.ppolicy.default.maxIdle` | `0` | Maximum inactivity in seconds; requires last-bind tracking and lockout=true |
| `openldap.bootstrap.auditlog.file` | `/var/log/openldap/audit.ldif` | Audit file; its parent directory is mounted as a volume |
| `openldap.bootstrap.tls.enabled` | `false` | Configure TLS during bootstrap |
| `openldap.bootstrap.tls.required` | `false` | Enforce TLS-only access |
| `openldap.bootstrap.tls.verifyClient` | `allow` | `olcTLSVerifyClient` value |
| `openldap.bootstrap.tls.protocolMin` | `3.4` | `olcTLSProtocolMin` value |
| `openldap.bootstrap.replication.mode` | `auto` | `auto` / `enabled` / `disabled` |
| `openldap.bootstrap.replication.allowReplicaCountChange` | `false` | Allow unsafe `replicaCount` changes after bootstrap when hosts are auto-generated |
| `openldap.bootstrap.replication.protocol` | `ldap` | Replication protocol (`ldap` / `ldaps`) |
| `openldap.bootstrap.replication.hosts` | `[]` | Override replication host list |
| `openldap.bootstrap.replication.syncprovCheckpoint` | `100 10` | syncprov checkpoint |
| `openldap.bootstrap.replication.dataReadonlyDnPrefix` | `cn=replicator` | Replication account prefix |
| `openldap.bootstrap.replication.dataReadonlyPassword` | `""` | Shared replication account password (plain); required when replication is enabled, or supplied via a secret/env override |
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
