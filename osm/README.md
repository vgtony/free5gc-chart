# Reusable OSM instantiation configuration

`instantiate.yaml` is a template for NSD `free5gc_ueransim_5` and KDU `free5gc`.
It uses VNF profile ID `free5gc`. It contains placeholders, not usable credentials.
It does not fix a Kubernetes namespace, node hostname or VIM account.

For each future cluster, supply that cluster's Helm values and the subscriber
credentials. The same template and helper can be reused; one unchanged values
file cannot describe clusters with different network interfaces, IPs and registries.

## Generate the installation file

Use Python 3 with PyYAML installed. Prepare a Helm values file for the destination
cluster using `PORTABLE-INSTALL.md` and `NEXT-CLUSTER-OSM.md`. Include the UERANSIM
image repository and reserved gNB IP explicitly, plus all applicable core image,
network, placement, and storage overrides. These are ordinary chart values:
`ueransim`, `global`, `free5gc-upf`, etc. Do not put an OSM wrapper in this file.

```bash
python3 osm/create-instantiation.py \
  --values /path/to/cluster-values.yaml \
  --output /path/to/instantiate.private.yaml
```

The helper prompts for SUPI, OP/OPc type, key and OP/OPc. It hides credential input,
validates it, retains the supplied cluster values and creates a new file readable
only by its owner. It always selects Helm-managed UE credentials with a
release-specific Secret name. No Kubernetes changes are made.

With chart 1.2.7, the combined chart provisions the subscriber automatically
before starting the UE. Existing subscriber credentials must match. The helper
itself only generates a file; it does not publish images, install Multus,
configure nodes, or validate live connectivity. For MCC/MNC values different from
the lab defaults, also align the UE, gNB and core configuration in cluster values.

Run OSM on the machine with your configured OSM client:

```bash
osm ns-create \
  --ns_name <unique-service-name> \
  --nsd_name free5gc_ueransim_5 \
  --vim_account <destination-VIM-account> \
  --config_file /path/to/instantiate.private.yaml
```

If you also need OSM-level `vld` network mappings, add them at the top level of the
generated file, alongside `additionalParamsForVnf`. They are not Helm values.

The checked-in template is reusable. Keep generated files containing actual
credentials outside version control and chart packages. Helm/OSM also receive and
store the supplied credentials as part of installation.

You may instead fill `instantiate.yaml` manually and merge all cluster Helm
values under `additionalParams`. Never submit its literal placeholders.

[OSM KDU instantiation parameter documentation](https://osm.etsi.org/docs/user-guide/develop/vnf-onboarding/05-quickstarts.html)
