# Local free5GC chart changes

Reference repository: <https://github.com/Costasgk/free5gc-chart>  
Reference commit: `f3a246e` (`main`)  
Release: `free5gc`, namespace `free5gc`

## What Codex changed

### 1. MongoDB probes

File: `my-values.yaml`

The bundled MongoDB chart uses the removed `mongo` shell in its default probes, while
the configured `mongo:6.0` image provides `mongosh`. This kept MongoDB unready and
blocked every network function in its `wait-mongo` init container.

The existing custom TCP probes were enabled by disabling the legacy probes:

```yaml
mongodb:
  livenessProbe:
    enabled: false
  readinessProbe:
    enabled: false
```

No MongoDB data was deleted. `mongodb-0` was restarted and reused its PVC.

### 2. AMF T3555 timer

File: `my-values.yaml`

The locally configured patched AMF image validates `T3555`, but the old chart config
did not include it. The following was added to the AMF configuration:

```yaml
t3555:
  enable: true
  expireTime: 6s
  maxRetryTimes: 4
```

Without it, AMF exited with `invalid T3555: non zero value required`.

### 3. ULCL SMF topology

File: `my-ulcl-values.yaml`

This file contained two top-level `free5gc-smf` keys. YAML keeps the later duplicate,
so the later image-only block silently replaced the earlier ULCL topology. The
duplicate image-only block was deleted because the same patched image is already set
in `my-values.yaml`.

This allowed the intended topology to render:

| UPF | N4/PFCP | N3/N9 |
| --- | --- | --- |
| `BranchingUPF` | `10.160.101.203` | N3 `.202`, N9 `.204` |
| `AnchorUPF1` | `10.160.101.205` | N9 `.206` |
| `AnchorUPF2` | `10.160.101.209` | N9 `.210` |

The SMF deployment was restarted because this old chart does not put a ConfigMap
checksum in the pod template and therefore does not restart automatically when its
configuration changes.

### 4. UPF-B N6 restoration

Files:

- `charts/free5gc-upf/templates/upfb/upfb-deployment.yaml`
- `charts/free5gc-upf/templates/upfb/upfb-configmap.yaml`
- `my-values.yaml`

The repository-compatible UPF-B N6 attachment and masquerade rule were restored.
UPF-B now uses unique interface addresses: N3 `10.160.101.202`, N4
`10.160.101.203`, N9 `10.160.101.204`, and N6 `10.160.101.218`.

### 5. gtp5g compatibility

The bundled free5GC v3.3.0 UPF accepts `gtp5g` versions from 0.8.1 through the
0.8.x series and rejects current 0.9.x/0.10.x releases. Fresh installations must
pin `gtp5g` v0.8.10 on every UPF node. This requirement is documented in
`README.md`.

### 6. Startup readiness and installation path

NRF and WebUI readiness probes now wait five seconds before their first HTTP
request, preventing harmless startup warnings observed during clean installs. The
root `README.md` was reduced to one tested, pinned Ubuntu/kubeadm installation
path covering containerd, Kubernetes, Flannel, Helm, storage, Multus, gtp5g, and
the chart.

## Changes that were already present

These tracked changes existed before Codex investigated the deployment and were
preserved:

- Earlier versions of the local branch removed UPF-B's N6 attachment and
  masquerade rule. Section 4 documents their subsequent restoration.
- The local `*.backup`, `my-*.yaml`, custom registry/image, node labels, addresses,
  and subnet configuration also predated this repair except for the specific changes
  documented above.

## Reapply

From the chart directory:

```bash
helm lint . -f my-values.yaml -f my-ulcl-values.yaml
helm upgrade --install free5gc . \
  --namespace free5gc \
  --create-namespace \
  -f my-values.yaml \
  -f my-ulcl-values.yaml \
  --timeout 10m \
  --wait
```

If SMF already exists and its ConfigMap changed:

```bash
kubectl -n free5gc rollout restart deployment/free5gc-free5gc-smf-smf
kubectl -n free5gc rollout status deployment/free5gc-free5gc-smf-smf --timeout=3m
```

## Verify

All pods should show `1/1 Running`:

```bash
kubectl -n free5gc get pods
```

Check AMF N2:

```bash
kubectl -n free5gc logs deployment/free5gc-free5gc-amf-amf |
  grep 'Listen on .*:38412'
```

Check all three PFCP associations:

```bash
kubectl -n free5gc logs deployment/free5gc-free5gc-smf-smf |
  grep 'setup association'
```

Expected UPF addresses are `10.160.101.203`, `10.160.101.205`, and
`10.160.101.209`.

Check Helm:

```bash
helm status free5gc -n free5gc
```

## Important cautions

- Do not add a second `free5gc-smf:` key to the same YAML file.
- Keep Multus `masterIf`, subnets, gateways, and static addresses aligned with the
  physical interfaces on every node.
- Static Multus addresses must be unique.
- Restart workloads after ConfigMap-only changes unless the chart gains pod-template
  checksum annotations.
- Do not delete the MongoDB PVC during a routine upgrade.
