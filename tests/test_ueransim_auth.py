"""Offline rendering checks; synthetic credentials never contact a cluster."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELM = os.environ.get("HELM", "helm")
KEY = "01" * 16
OP = "ab" * 16


class AuthRendering(unittest.TestCase):
    def render(self, ue=None, *, umbrella=False, release="test", namespace="fresh", enabled=True):
        values = {"ue": ue or {}}
        if umbrella:
            values = {"ueransim": values, "deployUeransim": enabled}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "values.json"
            path.write_text(json.dumps(values))
            chart = ROOT if umbrella else ROOT / "charts/ueransim"
            return subprocess.run(
                [HELM, "template", release, str(chart), "-n", namespace, "-f", str(path)],
                capture_output=True, text=True,
            )

    def test_missing_credentials_fail_before_install(self):
        for umbrella in (False, True):
            r = self.render(umbrella=umbrella)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("ue.auth.key must contain exactly 32 hexadecimal characters", r.stderr)

    def test_managed_secret_matches_both_refs_in_new_namespaces(self):
        for umbrella in (False, True):
            for release in ("alpha", "beta"):
                namespace = release + "-namespace"
                r = self.render({"auth": {"key": KEY, "op": OP}}, umbrella=umbrella,
                                release=release, namespace=namespace)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn('kind: Secret', r.stdout)
                self.assertEqual(r.stdout.count(f'name: "{release}-ueransim-ue-auth"'), 3)
                self.assertIn(f'namespace: "{namespace}"', r.stdout)
                self.assertIn(f'key: "{KEY}"', r.stdout)
                self.assertIn(f'op: "{OP}"', r.stdout)

    def test_external_mode_requires_explicit_name(self):
        r = self.render({"auth": {"create": False}})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("ue.existingAuthSecret is required", r.stderr)
        r = self.render({"auth": {"create": False}, "existingAuthSecret": "subscriber"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("kind: Secret", r.stdout)
        self.assertEqual(r.stdout.count('name: "subscriber"'), 2)

    def test_explicit_managed_name_preserves_compatibility(self):
        r = self.render({"auth": {"key": KEY, "op": OP}, "existingAuthSecret": "ueransim-ue-auth"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.count('name: "ueransim-ue-auth"'), 3)

    def test_invalid_credentials_and_op_type_fail(self):
        for key, op in (("bad", OP), (KEY, "z" * 32), (KEY, "")):
            r = self.render({"auth": {"key": key, "op": op}})
            self.assertNotEqual(r.returncode, 0)
        r = self.render({"auth": {"key": KEY, "op": OP}, "config": {"opType": "invalid"}})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("ue.config.opType must be OP or OPC", r.stderr)

    def test_core_only_needs_no_ue_credentials(self):
        r = self.render(umbrella=True, enabled=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("ueransim-ue-auth", r.stdout)


if __name__ == "__main__":
    unittest.main()
