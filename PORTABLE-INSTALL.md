# Installing on a prepared Kubernetes cluster

Version 1.2.6 fixes the implicit dependency on a manually created UE Secret.
Helm creates the Secret in its release namespace from supplied subscriber
credentials. Without valid credentials, rendering fails with a clear error.
This prevents the missing-Secret failure; it does not automatically provision a
subscriber or make an arbitrary cluster compatible with free5GC.

## Installation inputs

Provide protected values to Helm or OSM (do not commit real credentials):

```yaml
ueransim:
  ue:
    existingAuthSecret: ""
    auth:
      create: true
      key: "<subscriber-key: exactly 32 hexadecimal characters>"
      op: "<subscriber-OP-or-OPc: exactly 32 hexadecimal characters>"
    config:
      supi: "<subscriber SUPI, including imsi- prefix>"
      opType: OPC # Use OP when supplying OP instead of OPc.
```

These are placeholders, not working credentials. Supply the same subscriber
identity and authentication material that you provision in free5GC; also align
MCC/MNC, slice, DNN and authentication parameters. The bundled dbpython pod only
sleeps: it does not automatically insert subscribers. Creating the UE Secret
alone cannot make a new, empty core database authenticate a UE.

```bash
helm upgrade --install free5gc-ueransim . \
  --namespace <namespace> --create-namespace \
  -f <cluster-values.yaml> -f <protected-subscriber-values.yaml> \
  --wait --timeout 10m
```

For OSM, supply the same values as protected KDU installation parameters and
onboard the new `free5gc-1.2.6.tgz` artifact. A manual Secret-creation step is no
longer required in managed mode, including in a newly generated namespace.
Helm stores the supplied values in its release data.

For an externally provisioned Secret, set `ueransim.ue.auth.create=false` and
`ueransim.ue.existingAuthSecret=<name>`. It must exist in the release namespace
with `key` and `op`. Offline rendering cannot verify its existence. Setting a
name while leaving `create=true` means Helm manages that named Secret, preserving
the earlier chart behavior. The included church examples explicitly use external
mode. To switch those examples to managed mode, override both fields as above.
Existing installations using an external Secret must explicitly retain external
mode when upgrading to 1.2.6. Credentials are never generated or rotated silently.

## Cluster-specific requirements

The repository still contains lab network and registry defaults. Supply an
appropriate values file for each cluster:

| Concern | Required configuration |
| --- | --- |
| Images | Build and publish the included UERANSIM image to a reachable HTTPS registry, then set `ueransim.image.repository` and `tag`. Provide `ueransim.imagePullSecrets` for private registry authentication. Also publish/override the patched AMF, AUSF and SMF images used by the parent chart. |
| Placement | Map the RAN and UPF role selectors to prepared nodes, or override the selectors. Set `ueransim.nodeSelector: {}` only when every eligible worker supports its network and privileges. |
| Networking | Install Multus and the required CNI binaries. Configure the physical interface, reserved gNB IP, AMF address, and all core N2/N3/N4/N6/N9 addresses consistently for the target network. `network.create=false` selects a supplied NAD; it does not disable Multus. |
| UE TUN | The node/runtime and admission policy must permit the configured UE capabilities and `/dev/net/tun` creation/use. |
| Core | Provide compatible SCTP support, the required UPF kernel module, routing, and persistent storage. See `NEXT-CLUSTER-OSM.md`. |

Using HTTPS with a trusted certificate removes the HTTP registry runtime change
that was needed on patrick. `imagePullSecrets` supplies credentials; it does not
change HTTP/HTTPS behavior or certificate trust. For an intentional HTTP registry,
configure containerd on every eligible node during cluster preparation. The
application chart does not modify node runtime configuration or restart it.

References: [containerd registry configuration](https://github.com/containerd/containerd/blob/main/docs/hosts.md),
[UERANSIM configuration](https://github.com/aligungr/UERANSIM/wiki/Configuration).

## Verify deployment and registration separately

Check that gNB and UE reach `1/1 Running`, then inspect their logs for successful
NG setup, UE registration and PDU session establishment. Finally check the UE TUN
address and data-plane connectivity. A running process alone does not prove that
a subscriber authenticated or that traffic reaches its destination.

Run the credential rendering regression checks before packaging:

```bash
HELM=/path/to/helm python3 tests/test_ueransim_auth.py
helm package . --destination dist
```
