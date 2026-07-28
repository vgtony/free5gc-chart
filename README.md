# free5GC Helm chart

This chart deploys a free5GC core with MongoDB and optional ULCL user-plane topology. It is based on [Costasgk/free5gc-chart](https://github.com/Costasgk/free5gc-chart) and includes compatibility fixes proven on a Kubernetes cluster using Multus:

- MongoDB 6 uses TCP health probes instead of the removed `mongo` shell.
- AMF configuration includes the required `T3555` timer.
- The ULCL example defines one SMF topology and three consistent PFCP peers.

The chart cannot choose valid Multus addresses for an unknown network. You must create a values file for your cluster before installing.

## Components

AMF, AUSF, NRF, NSSF, PCF, SMF, UDM, UDR, UPF, WebUI, DBPython, MongoDB, and optionally N3IWF.

## Prerequisites

- Kubernetes with working pod networking and DNS.
- Helm 3 and `kubectl`.
- Multus installed on every node that may run AMF, SMF, UPF, or N3IWF.
- The `macvlan`, `ipvlan`, `static`, and `tuning` CNI binaries on those nodes.
- The `gtp5g` kernel module on every UPF node.
- SCTP kernel support for AMF N2/NGAP.
- A default StorageClass, or a pre-created PersistentVolume for MongoDB.
- A physical parent interface with the same name on every selected node.

Check the cluster:

```bash
kubectl get nodes -o wide
kubectl get pods -n kube-system | grep multus
kubectl get storageclass
```

On every UPF node:

```bash
ip -br link
lsmod | grep gtp5g
```

## 1. Create cluster values

Copy the supplied template; do not edit `values.yaml` for each installation:

```bash
cp values.example.yaml my-values.yaml
```

Replace every `<YOUR_...>` placeholder:

```bash
grep -n '<YOUR_' my-values.yaml
```

The command must return no output before installation.

### Multus address plan

Each static address must belong to its configured subnet, be unused and unique, and be reachable at layer 2 from every node that may host the pod.

| Purpose | Value |
| --- | --- |
| Parent NIC on every relevant node | `global.n2network.masterIf` through `global.n9network.masterIf` |
| AMF N2 address | `global.amf.n2if.ipAddress` |
| SMF N4 address | `global.smf.n4if.ipAddress` |
| Single-UPF N3/N4/N6 | `free5gc-upf.upf.*if.ipAddress` |
| Branching UPF N3/N4/N9 | `free5gc-upf.upfb.*if.ipAddress` |
| Anchor UPF 1 N4/N6/N9 | `free5gc-upf.upf1.*if.ipAddress` |
| Anchor UPF 2 N4/N6/N9 | `free5gc-upf.upf2.*if.ipAddress` |
| N6 data-network gateway | `global.n6network.gatewayIP` |
| UE address pools | SMF `dnnUpfInfoList[].pools` and UPF `dnnList[].cidr` |

`subnetIP` is the network address, not a pod address. `cidr` is the prefix length. For example:

```yaml
global:
  n4network:
    masterIf: ens18
    subnetIP: 10.20.30.0
    cidr: 24
  smf:
    n4if:
      ipAddress: 10.20.30.10

free5gc-upf:
  upfb:
    n4if:
      ipAddress: 10.20.30.11
```

Do not copy sample IPs unless that subnet is routed on your nodes. Avoid a default gateway on N3, N4, or N9 unless the network design requires it; multiple default routes commonly break pod connectivity.

### macvlan versus ipvlan

Use the type supported by your network:

```yaml
global:
  n2network:
    type: macvlan
    masterIf: ens18
```

Some switches or virtualized networks reject multiple MAC addresses behind one port. In that case use `ipvlan` if the environment supports it. All scheduled nodes must have the configured `masterIf`.

### ULCL node placement

The example uses these node labels:

```bash
kubectl label node <branching-node> free5gc-node=iupf
kubectl label node <anchor-1-node> free5gc-node=psa1
kubectl label node <anchor-2-node> free5gc-node=psa2
```

Remove or change the matching `nodeSelector` entries if you use a different placement model.

The SMF topology addresses must exactly equal the corresponding UPF interfaces:

- `BranchingUPF.nodeID`/`addr` = `upfb.n4if.ipAddress`
- `AnchorUPF1.nodeID`/`addr` = `upf1.n4if.ipAddress`
- `AnchorUPF2.nodeID`/`addr` = `upf2.n4if.ipAddress`
- Every SMF N3/N9 endpoint = the matching UPF N3/N9 address.

Never define `free5gc-smf:` twice in one YAML file; duplicate YAML keys silently discard configuration in common parsers.

### Images

The example references locally patched AMF, AUSF, and SMF images. Change their `image.name` and `image.tag` to images available to your cluster. For a private registry, create an image pull secret and set `imagePullSecrets`.

## 2. Validate and install

```bash
helm lint . -f my-values.yaml
helm template free5gc . -n free5gc -f my-values.yaml >/tmp/free5gc-rendered.yaml
helm upgrade --install free5gc . \
  --namespace free5gc \
  --create-namespace \
  -f my-values.yaml \
  --timeout 10m \
  --wait
```

For the packaged chart, replace `.` with `./free5gc-1.1.8.tgz`.

## 3. Verify

```bash
kubectl get pods -n free5gc
helm status free5gc -n free5gc
kubectl get network-attachment-definitions -n free5gc
```

Every workload should show `Running` and `1/1`.

Verify Multus attachments:

```bash
kubectl get pods -n free5gc -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{.metadata.annotations.k8s\.v1\.cni\.cncf\.io/network-status}{"\n\n"}{end}'
```

Verify AMF N2:

```bash
kubectl logs -n free5gc deployment/free5gc-free5gc-amf-amf | grep 'Listen on .*:38412'
```

Verify ULCL PFCP associations:

```bash
kubectl logs -n free5gc deployment/free5gc-free5gc-smf-smf | grep 'setup association'
```

If a ConfigMap changes but its pod does not restart, restart only that deployment:

```bash
kubectl rollout restart -n free5gc deployment/<deployment-name>
kubectl rollout status -n free5gc deployment/<deployment-name>
```

## Troubleshooting

For `Init:0/1` on most control-plane pods, inspect MongoDB:

```bash
kubectl describe pod -n free5gc mongodb-0
kubectl logs -n free5gc mongodb-0
```

For `FailedCreatePodSandBox` or Multus errors:

```bash
kubectl describe pod -n free5gc <pod>
kubectl get network-attachment-definitions -n free5gc -o yaml
```

Confirm `masterIf` exists on the selected node and the static IP is unused and inside the configured subnet.

SMF PFCP retry timeouts mean its topology N4 address does not match a reachable UPF N4 address. Compare SMF logs with each pod's Multus `network-status`.

AMF `invalid T3555` means an older values file replaced the fixed AMF configuration. Add the timer shown in `values.example.yaml`.

## Upgrade and uninstall

```bash
helm upgrade free5gc . -n free5gc -f my-values.yaml --timeout 10m --wait
helm uninstall free5gc -n free5gc
```

Uninstalling does not necessarily delete MongoDB PVCs. Review them explicitly:

```bash
kubectl get pvc -n free5gc
```

See [LOCAL-CHANGES.md](./LOCAL-CHANGES.md) for the repair history.
