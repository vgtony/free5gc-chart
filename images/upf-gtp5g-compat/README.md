# UPFb compatibility with gtp5g v0.8.10

The deployed upstream go-upf is v1.2.0, commit
`4474dc86cf7f9851283d4c1895f0b61356b7711e`. The old kernel matches the inner
source IP on incoming GTP packets. For N9 downlink packets the UE address is the
destination, so a PDR containing that address cannot match.

This patch omits only the kernel UE-address attribute when all three conditions
hold: Source Interface is Core, a valid F-TEID is present, and the PFCP UE IP
Address is marked as a destination. The F-TEID continues to select the tunnel.
N3 uplink and anchor N6 downlink retain their address checks. The patch scans
all IEs first, so their order does not affect the result. It does not add full
source-interface support to the old kernel; use it only for this compatibility
profile. SDF-filter behavior is unchanged and additional ULCL flows need their
own validation.

Build from this directory with Docker or a compatible builder:

```sh
docker build -t 10.160.101.91:32000/free5gc-upf:n9-compat-1.2.0 .
docker push 10.160.101.91:32000/free5gc-upf:n9-compat-1.2.0
```

The Dockerfile pins the original source commit and deployed runtime image digest,
runs forwarder unit tests (including four direction/tunnel cases), and builds a
static binary. The `osm/lab-patched-values.yaml` profile selects this image only
for UPFb. It also selects modern subscriber provisioning and the patched core
NF images needed by the existing lab.
