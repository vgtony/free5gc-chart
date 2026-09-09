# UERANSIM on Kubernetes

This subchart runs UERANSIM v3.3.0 as two Kubernetes Deployments without naming
a worker. Kubernetes selects a node labeled `telecom.example/ran=true`:

- `gnb`: attaches to the configured physical network through Multus and uses
  one fixed address for both N2/NGAP and N3/GTP-U.
- `ue`: reaches the gNB radio simulator through a ClusterIP UDP Service and
  creates `uesimtun0` in the UE pod network namespace.

The bundled lab defaults use gNB address `10.160.101.231` and AMF address
`10.160.101.100`. Override these network values for another cluster. The SMF
learns the gNB N3 endpoint during session setup, so no SMF topology address
needs to be changed.

## Prerequisites

- Every worker eligible for the gNB has Multus plus the `macvlan`, `static`,
  and `tuning` CNI binaries.
- The configured physical interface exists on every eligible gNB worker.
  Override `global.n2network.masterIf` when it is not `eth0`.
- Label at least one prepared RAN node with
  `kubectl label node <NODE> telecom.example/ran=true`. Multiple matching nodes
  are allowed; their hostnames never enter the chart.
- The free5GC subscriber matches `ue.config.supi`, slice `1/010203`, and DNN
  `internet`.
- `10.160.101.231` is reserved and unused. Check again from a node on the same
  L2 network before installation:

  ```bash
  sudo arping -D -c 3 -w 3 -I eth0 10.160.101.231
  ```

  `100% packet loss (0 extra)` means no duplicate ARP reply was received.

## Prepare an OSM namespace (external Secret mode)

Set `ue.auth.create=false` and `ue.existingAuthSecret=ueransim-ue-auth`
(prefix both with `ueransim.` in the umbrella chart).
Run the repository helper after the OSM namespace exists. It checks the local
registry, builds and publishes UERANSIM in a temporary Kubernetes Job only when
the image is missing, and prompts invisibly for the UE key and OPc:

```bash
./prepare-ueransim-for-osm.sh --namespace <namespace>
```

The build Job deletes itself after a successful push. The image is shared by
all namespaces, while the authentication Secret is created only in the target
namespace. Run the command again for another OSM namespace; it will reuse the
published image. Use `--help` to see registry overrides and non-interactive
options.

## Build and publish UERANSIM v3.3.0 manually

The upstream UERANSIM repository does not publish a v3.3.0 runtime image. If the
helper cannot be used, build the included multi-stage image and push it to the
lab registry:

```bash
docker build -t 10.160.101.91:32000/ueransim:3.3.0 images/ueransim
docker push 10.160.101.91:32000/ueransim:3.3.0
```

Override `image.repository` if another registry is used.

## Provide UE authentication

The public chart contains no subscriber credentials. For an OSM-managed Secret,
supply protected instantiation values that match the free5GC subscriber:

```yaml
ueransim:
  ue:
    auth:
      create: true
      key: "<32-hex-permanent-key>"
      op: "<32-hex-op-or-opc>"
```

Helm creates `<ueransim-fullname>-ue-auth` in the release namespace by default.
An explicit `existingAuthSecret` overrides the generated name for compatibility.
Missing or invalid keys fail rendering; `ue.config.opType` must be `OP` or `OPC`.
Helm release data contains supplied credentials. To use an external secret
manager, explicitly set `auth.create=false`, set `existingAuthSecret`, and
provision that Secret with keys `key` and `op` in the target namespace. Changing
a Helm-managed key or OP/OPc automatically rolls the UE Deployment.

The chart does not provision the subscriber in MongoDB: matching credentials,
SUPI, slice and DNN must also exist in free5GC. See the repository
[portable installation guide](../../PORTABLE-INSTALL.md).

## Install beside the existing free5GC release

Use the standalone subchart in the namespace already containing free5GC. This
does not modify or duplicate any core workload:

```bash
helm upgrade --install ueransim ./charts/ueransim \
  -n <namespace> \
  -f <cluster-network-values.yaml>
```

Before doing this, stop any bare `nr-ue` and `nr-gnb` processes using the same
configuration. Running two UEs with the same SUPI produces competing
registrations. The old lab diagnostic pod is not part of this chart; the
podized gNB uses its own macvlan address.

## Install as one combined release

For a fresh deployment, enable the optional dependency in the umbrella chart:

```bash
helm upgrade --install free5gc-ueransim . \
  -n <namespace> --create-namespace \
  -f <cluster-network-values.yaml> \
  --timeout 10m --wait
```

Do not run this combined command in a namespace where OSM or another Helm
release already owns the free5GC resources. Use the standalone command above in
that case.

## Verify

```bash
kubectl -n <namespace> get pods -l app.kubernetes.io/name=ueransim -o wide
kubectl -n <namespace> logs deployment/ueransim-gnb
kubectl -n <namespace> logs deployment/ueransim-ue
kubectl -n <namespace> exec deployment/ueransim-ue -- ip address show uesimtun0
kubectl -n <namespace> exec deployment/ueransim-ue -- ping -I uesimtun0 -c 4 8.8.8.8
```

Resource names include the Helm release name. Adjust `ueransim` in the commands
if a different release name is chosen.
