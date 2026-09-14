#!/usr/bin/env python3
"""Wrap cluster Helm values in OSM parameters and prompt for UE credentials."""
import argparse
from copy import deepcopy
from getpass import getpass
import os
from pathlib import Path
import re
import sys

import yaml


def build_parameters(values, key, op, supi, op_type):
    if not isinstance(values, dict):
        raise ValueError("The cluster values file must contain a YAML mapping")
    for name, value in (("key", key), ("op", op)):
        if not re.fullmatch(r"[0-9a-fA-F]{32}", value):
            raise ValueError(f"UE {name} must contain exactly 32 hexadecimal characters")
    if not re.fullmatch(r"imsi-[0-9]{15}", supi):
        raise ValueError("SUPI must be imsi- followed by 15 digits")
    if op_type not in ("OP", "OPC"):
        raise ValueError("opType must be OP or OPC")
    result = deepcopy(values)
    if result.get("deployUeransim") is False:
        raise ValueError("The supplied values disable UERANSIM")
    ran = result.setdefault("ueransim", {})
    repository = ran.get("image", {}).get("repository", "")
    if not repository or "<" in repository or "://" in repository:
        raise ValueError("Set ueransim.image.repository to your published image repository (without http:// or https://)")
    if not ran.get("network", {}).get("ipAddress"):
        raise ValueError("Set ueransim.network.ipAddress to the gNB address reserved for this cluster")
    ue = ran.setdefault("ue", {})
    ue["existingAuthSecret"] = ""
    ue["auth"] = {"create": True, "key": key, "op": op}
    ue.setdefault("config", {}).update({"supi": supi, "opType": op_type})
    # Catch unfilled examples, including networking values, without printing them.
    def has_placeholder(value):
        if isinstance(value, dict):
            return any(has_placeholder(item) for item in value.values())
        if isinstance(value, list):
            return any(has_placeholder(item) for item in value)
        # Embedded multi-line application configs can contain comments such as
        # <optional>; those are not deployment placeholders.
        return isinstance(value, str) and "\n" not in value and re.search(r"<[^>]+>", value)

    if has_placeholder(result):
        raise ValueError("Replace all placeholder values in the cluster configuration")
    return {"additionalParamsForVnf": [{
        "member-vnf-index": "free5gc",
        "additionalParamsForKdu": [{"kdu_name": "free5gc", "additionalParams": result}],
    }]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--values", required=True, type=Path, help="Complete Helm overrides for the destination cluster")
    parser.add_argument("--output", required=True, type=Path, help="New private OSM config file; existing files are never overwritten")
    args = parser.parse_args()
    try:
        with args.values.open() as source:
            values = yaml.safe_load(source)
        if args.output.exists():
            raise ValueError("Output already exists; choose a new filename")
        print("Choose the UE subscriber identity and credentials. Chart 1.2.7 provisions them in Free5GC when installed; existing subscriber credentials must match.")
        supi = input("Subscriber SUPI (imsi-...): ").strip()
        op_type = input("Credential type [OPC/OP] (default OPC): ").strip().upper() or "OPC"
        key = getpass("Subscriber key (32 hex): ").strip()
        op = getpass("Subscriber OP/OPc (32 hex): ").strip()
        params = build_parameters(values, key, op, supi, op_type)
        content = yaml.safe_dump(params, sort_keys=False)
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as output:
            output.write(content)
        print(f"Created {args.output} with mode 0600. No deployment was started.")
    except (OSError, ValueError, yaml.YAMLError, EOFError) as error:
        # YAML parser errors may include sensitive input; do not echo their text.
        message = "Invalid YAML in cluster values file" if isinstance(error, yaml.YAMLError) else str(error)
        parser.exit(1, f"Error: {message}\n")


if __name__ == "__main__":
    main()
