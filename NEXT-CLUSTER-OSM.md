# Deploying free5GC 1.1.10 through OSM on a new Kubernetes cluster

This is the required preparation and validation runbook for `free5gc-1.1.10.tgz`.
OSM installs only Kubernetes resources. It does not install kernel modules, CNI
plugins, storage provisioners, configure node interfaces, reserve addresses, or
configure containerd registries.

## Tested baseline

- Ubuntu 24.04 amd64 nodes
- Kubernetes 1.36 with containerd and Flannel
- Helm 3.21.3
- Multus thick plugin
- free5GC v3.3.0
- gtp5g v0.8.10

Other combinations may work, but validate them before OSM onboarding.

## 1. Worker topology and kernel preparation

The default chart is a three-UPF ULCL deployment. Provide at least three Ready,
schedulable workers with distinct `kubernetes.io/hostname` values. Required pod
anti-affinity schedules one UPF per worker.

Every node eligible to run a UPF requires:

- `gtp5g` exactly v0.8.10, installed and loaded;
- `gtp5g` in `/etc/modules-load.d/gtp5g.conf` for reboot persistence;
- `net.ipv4.ip_forward=1`;
- matching kernel headers; and
- enough capacity for a UPF request of 500m CPU and 512 MiB memory.

Install gtp5g on every UPF worker:

```bash
sudo apt-get update
sudo apt-get install -y gcc make git linux-headers-"$(uname -r)"
git clone --branch v0.8.10 --depth 1 https://github.com/free5gc/gtp5g.git /tmp/gtp5g
make -C /tmp/gtp5g
sudo make -C /tmp/gtp5g install
sudo depmod -a
sudo modprobe gtp5g
echo gtp5g | sudo tee /etc/modules-load.d/gtp5g.conf
modinfo -F version gtp5g
```

The final command must report `0.8.10`. Versions 0.9.x and newer are rejected by
the bundled free5GC v3.3.0 UPF.

## 2. Primary Kubernetes networking

Install and validate a primary pod CNI such as Flannel. Cluster DNS and pod-to-pod
routing must work across nodes before Multus is added:

```bash
kubectl get nodes
kubectl get pods -n kube-system -o wide
kubectl get pods -n kube-flannel -o wide
```

All nodes and CoreDNS pods must be Ready. The tested pod CIDR is `10.244.0.0/16`.
Do not overlap the pod CIDR, Service CIDR, UE subnet, or secondary network.

## 3. Multus and CNI executables

Install Multus on every node and ensure its DaemonSet is Ready:

```bash
kubectl apply -f https://raw.githubusercontent.com/k8snetworkplumbingwg/multus-cni/6386911021ffb0715b930a2d372f2aa16084e78f/deployments/multus-daemonset-thick.yml
kubectl rollout status -n kube-system daemonset/kube-multus-ds --timeout=3m
kubectl get crd network-attachment-definitions.k8s.cni.cncf.io
```

Every worker must have executable `macvlan`, `ipvlan`, `static`, and `tuning`
plugins under `/opt/cni/bin`:

```bash
for f in macvlan ipvlan static tuning; do
  test -x "/opt/cni/bin/$f" || echo "missing $f"
done
```

## 4. Secondary network and reserved addresses

The default chart expects `eth0` on every worker, connected to the same
`10.160.101.0/24` layer-2 network. The N6 gateway is `10.160.101.1`.

Reserve these addresses outside DHCP/IPAM and confirm no existing device owns
them:

| Address | Purpose |
| --- | --- |
| `10.160.101.100` | AMF N2/NGAP |
| `10.160.101.101` | SMF N4/PFCP |
| `10.160.101.202` | Branching UPF N3 |
| `10.160.101.203` | Branching UPF N4 |
| `10.160.101.204` | Branching UPF N9 |
| `10.160.101.205` | Anchor UPF 1 N4 |
| `10.160.101.206` | Anchor UPF 1 N9 |
| `10.160.101.207` | Anchor UPF 1 N6 |
| `10.160.101.209` | Anchor UPF 2 N4 |
| `10.160.101.210` | Anchor UPF 2 N9 |
| `10.160.101.212` | Anchor UPF 2 N6 |
| `10.160.101.218` | Branching UPF N6 |

A missing ping response does not prove an address is reserved. Exclude the entire
set in DHCP and use ARP inspection from the same layer-2 network.

If a future cluster uses another master interface or subnet, override all N2, N3,
N4, N6, N9, AMF, SMF, and UPF interface values consistently. Do not configure a
secondary default route on N2, N3, N4, or N9. Kubernetes service and DNS traffic
must retain the primary pod interface. Version 1.1.10 removes the erroneous Multus
default routes; UPF N6 traffic uses a dedicated `n6if` policy-routing table.

## 5. Persistent storage

Install a dynamic provisioner and mark one StorageClass as default. The chart
requests one 6 GiB `ReadWriteOnce` claim for MongoDB.

```bash
kubectl get storageclass
kubectl get storageclass -o jsonpath='{range .items[*]}{.metadata.name}{" default="}{.metadata.annotations.storageclass\.kubernetes\.io/is-default-class}{"\n"}{end}'
```

Version 1.1.10 uses `docker.io/mongo:6.0` and mounts the claim at `/data/db`.
This exact path is required for subscriber data to survive pod recreation. The
older `/bitnami/mongodb/data/db/` path was unused by the official Mongo image.

For a clean final test, remove an old PVC only after backing up wanted data. For a
persistence test, insert a subscriber, recreate `mongodb-0`, and confirm the record
remains.

## 6. Image registry access

Every worker must reach Docker Hub and `10.160.101.91:32000`. The private registry
contains:

```text
10.160.101.91:32000/free5gc-amf:patched
10.160.101.91:32000/free5gc-ausf:patched
10.160.101.91:32000/free5gc-smf:patched
```

The current private registry uses HTTP. Configure containerd on every node:

```bash
sudo mkdir -p /etc/containerd/certs.d/10.160.101.91:32000
cat <<'EOF_REGISTRY' | sudo tee /etc/containerd/certs.d/10.160.101.91:32000/hosts.toml
server = "http://10.160.101.91:32000"

[host."http://10.160.101.91:32000"]
  capabilities = ["pull", "resolve"]
EOF_REGISTRY
sudo systemctl restart containerd
curl -fsS http://10.160.101.91:32000/v2/
```

If the next cluster cannot route to this registry, publish the patched images to a
reachable registry and override the chart image values.

## 7. OSM kubeconfig and RBAC

The Kubernetes API address in OSM's kubeconfig must be reachable from the OSM LCM
containers. The identity must be allowed to create/use the target namespace and
create, get, list, watch, patch, update, and delete:

- Pods, Services, ConfigMaps, Secrets and PVCs;
- Deployments, ReplicaSets and StatefulSets; and
- `network-attachment-definitions.k8s.cni.cncf.io`.

Test using the actual OSM identity rather than only an admin shell:

```bash
kubectl auth can-i create namespaces
kubectl auth can-i create deployments.apps -n osm-preflight
kubectl auth can-i create statefulsets.apps -n osm-preflight
kubectl auth can-i create persistentvolumeclaims -n osm-preflight
kubectl auth can-i create network-attachment-definitions.k8s.cni.cncf.io -n osm-preflight
```

## 8. Port and capacity checks

The default WebUI Service reserves NodePort `30500`. Confirm it is free:

```bash
kubectl get services -A \
  -o custom-columns=NS:.metadata.namespace,NAME:.metadata.name,NODEPORT:.spec.ports[*].nodePort |
  grep 30500 || true
```

Also confirm three workers remain schedulable and have no pressure conditions:

```bash
kubectl get nodes
kubectl describe nodes | grep -E 'Name:|Taints:|Pressure|Allocated resources' -A6
```

## 9. Package, publish, and onboard

Build only after all source changes are present:

```bash
helm lint .
helm template preflight . -n preflight >/tmp/free5gc-1.1.10.yaml
helm package . --destination dist
sha256sum dist/free5gc-1.1.10.tgz
```

Publish the archive and update the VNFD/KDU URL to:

```text
https://vgtony.github.io/free5gc-chart/dist/free5gc-1.1.10.tgz
```

Rebuild and re-onboard the VNFD/NSD in OSM. Verify the operation output explicitly
references `free5gc-1.1.10.tgz`. If it references 1.1.8 or 1.1.9, OSM is using an
old descriptor or cached artifact.

OSM invokes Helm with `--atomic --wait`. Watch the generated namespace while it
installs; after a timeout Helm removes the failed release and much of the evidence:

```bash
NS=<osm-generated-namespace>
kubectl get pods -n "$NS" -w
kubectl get events -n "$NS" --sort-by=.lastTimestamp
helm list -n "$NS" --all
```

## 10. Success criteria

All application pods must reach `1/1 Running`. Then verify:

```bash
NS=<osm-generated-namespace>
kubectl get pods -n "$NS" -o wide
helm list -n "$NS"

AMF=$(kubectl get pods -n "$NS" -l nf=amf -o jsonpath='{.items[0].metadata.name}')
SMF=$(kubectl get pods -n "$NS" -l nf=smf -o jsonpath='{.items[0].metadata.name}')

kubectl logs -n "$NS" "$AMF" | grep 'Listen on .*:38412'
kubectl logs -n "$NS" "$SMF" | grep 'setup association'
kubectl exec -n "$NS" "$AMF" -- ip route
kubectl exec -n "$NS" "$SMF" -- ip route
```

Expected results:

- Helm status `deployed`;
- AMF listening on `10.160.101.100:38412`;
- SMF associated with UPFs `10.160.101.203`, `.205`, and `.209`;
- no default route through AMF `n2` or SMF `n4`;
- MongoDB PVC Bound and mounted at `/data/db`; and
- subscriber data survives a MongoDB pod recreation.

## 11. Failure triage

If AMF or SMF stays at `Init:0/1`:

```bash
kubectl logs -n "$NS" <pod> -c wait-nrf
kubectl exec -n "$NS" <pod> -c wait-nrf -- cat /proc/net/route
kubectl get svc,endpoints,endpointslices -n "$NS"
```

HTTP code `000` from `wait-nrf` usually means DNS/routing failure. Version 1.1.10
must not have a secondary default route. If UPFs remain Pending, check that three
eligible workers exist. If UPFs crash, verify gtp5g on the exact scheduled nodes.
