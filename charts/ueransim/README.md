# UERANSIM on the Church worker

This subchart runs UERANSIM v3.3.0 as two Kubernetes Deployments pinned to the
`church` worker:

- `gnb`: attaches to the physical `10.160.101.0/24` network through Multus and
  uses one fixed address for both N2/NGAP and N3/GTP-U.
- `ue`: reaches the gNB radio simulator through a ClusterIP UDP Service and
  creates `uesimtun0` in the UE pod network namespace.

The default Church gNB address is `10.160.101.231`. The AMF remains at
`10.160.101.100`. The SMF learns the gNB N3 endpoint during session setup, so no
SMF topology address needs to be changed.

## Prerequisites

- The worker is joined to Kubernetes and its hostname label is `church`.
- Multus and the `macvlan`, `static`, and `tuning` CNI binaries are installed on
  Church.
- Church's physical interface connected to `10.160.101.0/24` is named `eth0`, or
  `global.n2network.masterIf` is overridden.
- The free5GC subscriber matches `ue.config.supi`, slice `1/010203`, and DNN
  `internet`.
- `10.160.101.231` is reserved and unused. Check again from a node on the same
  L2 network before installation:

  ```bash
  sudo arping -D -c 3 -w 3 -I eth0 10.160.101.231
  ```

  `100% packet loss (0 extra)` means no duplicate ARP reply was received.

## Build and publish UERANSIM v3.3.0

The upstream UERANSIM repository does not publish a v3.3.0 runtime image. Build
the included multi-stage image and push it to the lab registry:

```bash
docker build -t 10.160.101.91:32000/ueransim:3.3.0 images/ueransim
docker push 10.160.101.91:32000/ueransim:3.3.0
```

Override `image.repository` if another registry is used.

## Create the UE authentication Secret

The permanent subscriber key and OP/OPc are intentionally not stored in chart
values. Create the Secret in the target namespace using the same values that
were provisioned in free5GC:

```bash
read -rsp 'UE permanent key: ' UE_KEY; echo
read -rsp 'UE OP or OPc: ' UE_OP; echo
kubectl -n <namespace> create secret generic ueransim-ue-auth \
  --from-literal=key="$UE_KEY" \
  --from-literal=op="$UE_OP"
unset UE_KEY UE_OP
```

If the Secret is rotated, restart the UE Deployment so its environment is
reloaded.

## Install beside the existing free5GC release

Use the standalone subchart in the namespace already containing free5GC. This
does not modify or duplicate any core workload:

```bash
helm upgrade --install church-ueransim ./charts/ueransim \
  -n <namespace> \
  -f charts/ueransim/church-values.yaml
```

Before doing this, stop the bare `nr-ue` and `nr-gnb` processes on Church. In
particular, running two UEs with the same SUPI produces competing registrations.
The old `church-ueransim-n3-neighbor` diagnostic pod is not part of this chart;
the podized gNB uses its own macvlan address and does not rely on Church's host
network neighbor entry.

## Install as one combined release

For a fresh deployment, enable the optional dependency in the umbrella chart:

```bash
helm upgrade --install free5gc-ueransim . \
  -n <namespace> --create-namespace \
  -f church-ueransim-values.yaml \
  --timeout 10m --wait
```

Do not run this combined command in a namespace where OSM or another Helm
release already owns the free5GC resources. Use the standalone command above in
that case.

## Verify

```bash
kubectl -n <namespace> get pods -l app.kubernetes.io/name=ueransim -o wide
kubectl -n <namespace> logs deployment/church-ueransim-gnb
kubectl -n <namespace> logs deployment/church-ueransim-ue
kubectl -n <namespace> exec deployment/church-ueransim-ue -- ip address show uesimtun0
kubectl -n <namespace> exec deployment/church-ueransim-ue -- ping -I uesimtun0 -c 4 8.8.8.8
```

Resource names include the Helm release name. Adjust `church-ueransim` in the
commands if a different release name is chosen.
