# Automatic subscriber provisioning (chart 1.2.10)

The combined chart enables `ueransim.provisioning.enabled` by default. The
standalone subchart leaves `provisioning.enabled=false` to avoid unexpectedly
changing an existing core. Enable it explicitly when installing standalone.

An ordinary UE init container waits for MongoDB, then upserts the configured
subscriber. Kubernetes starts `nr-ue` only after this container succeeds. This
works with Helm/OSM `--atomic --wait`: no post-install hook waits on an unready UE,
no Job polling, Kubernetes API access, or extra RBAC is needed.

## One source for credentials and subscription

Supply `ue.auth.key`, `ue.auth.op` and `ue.config` as before (prefix with
`ueransim.` under the parent chart). Both init and main containers reference the
same Secret, including in external-Secret mode. The init container uses the UE's
SUPI, MCC/MNC, AMF authentication field, slices and requested sessions to create:

- `subscriptionData.authenticationData.authenticationSubscription`
- `subscriptionData.provisionedData.amData`
- `subscriptionData.provisionedData.smData`
- `subscriptionData.provisionedData.smfSelectionSubscriptionData`
- `policyData.ues.amData`
- `policyData.ues.smData`

The legacy schema follows free5GC v3.3.0 / webconsole v1.2.0. The 1.2.10 umbrella chart selects the modern schema for the patched lab. OP input is converted to OPc
using AES-128 as specified by Milenage; OPC input is used directly. The same
original value and `opType` are still supplied to UERANSIM.

Credentials are not generated automatically. Choose them once at installation;
Helm creates the Secret and the init container provisions the core. Network
configuration in AMF/SMF/NSSF must support the UE's PLMN, slice and DNN.

## Connection and compatibility

Defaults use `docker.io/library/mongo:6.0.26` with `mongosh`, connecting to the
`mongodb` service in the release namespace, database `free5gc`. Override these
under `ueransim.provisioning` for a different image mirror or database.

For authenticated MongoDB, set `existingMongoSecret` to a Secret in the release
namespace containing the full connection URI under `mongoSecretKey` (default
`uri`). Avoid embedding passwords in `mongoUri`. The database identity needs
read and write privileges for the six collections above. Keep connection and
server-selection timeouts bounded in custom URIs.

`authenticationSchema: legacy` writes `permanentKey` and `opc` objects.
`authenticationSchema: modern` writes `encPermanentKey` and `encOpcKey` strings
and requires `sequenceNumberFormat: object`. Select this for the patched UDM/UDR
in the lab; a version banner alone does not identify its model schema.

`sequenceNumberFormat: string` stores a hex string; `object` stores
`{sqn, sqnScheme}`. For a fresh UERANSIM lab subscriber, the patched profile uses
`initialSqn: "000000000020"`, ahead of the simulator's zero counter. Existing
SQN is never reset by provisioning.

Set `migrateAuthentication: true` to convert a matching existing record's schema
while preserving its SQN and existing object metadata. Every stored credential
representation must match the shared UE Secret. Conflicts fail before writes;
migration never rotates credentials. An invalid SQN also fails without writes.
The update compares the existing record so concurrent changes cause a retry
instead of overwriting newer data. Back up the subscriber before a migration.

The legacy WebUI writes the old fields and cannot maintain modern authentication
records correctly. Use the provisioner for this subscriber. The generic error
in chart 1.2.8 did not imply that a migration switch existed in that version.

Automatic provisioning supports IPv4 sessions with simple DNN names (letters,
digits, hyphens); other session types or dotted DNNs fail clearly. For those
profiles, disable provisioning and use the core's provisioning interface.

## Repeated installs, retries and upgrades

The authentication record is created if missing or explicitly migrated. Existing key, OPc, method
and authentication management field must match; a conflict stops initialization
without rotating the existing credentials. An existing OP-only record must be
migrated to the equivalent OPc form before enabling this provisioner.

Existing authentication SQN is preserved. Subscription and policy fields for the
configured SUPI/PLMN/slices are updated from chart values. Other SUPIs and stale
session records for other slices are not deleted. Run one owning release per
subscriber: simultaneous independent releases for the same SUPI are unsupported.

An interrupted run can leave partial records; a retry completes them before the
UE starts. MongoDB standalone does not offer multi-document transactions. A
failed Helm release or uninstall does not erase subscriber database records.
Use the core's subscriber management tools for intentional deletion or rotation.

Database connection attempts are bounded by `waitSeconds` (default 300) and URI
timeouts; Kubernetes retries a failed init container, while Helm's timeout bounds
the installation. Read its logs with:

```bash
kubectl -n <namespace> logs deployment/<release>-ueransim-ue -c provision-subscriber
```

The init container runs without root or extra capabilities. It does not log keys,
OP/OPc or connection URIs. Check the gNB/UE logs for successful registration and
PDU session establishment afterward; successful provisioning alone cannot prove
network connectivity or a working data plane.

Schema reference:
https://github.com/free5gc/webconsole/blob/v1.2.0/backend/WebUI/api_webui.go
