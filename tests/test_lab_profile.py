"""Guard compatibility across rendered NF config, subscriber schema and UPF pools."""
import os
from pathlib import Path
import subprocess
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
HELM = os.environ.get('HELM', 'helm')

class LabProfile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = subprocess.run([HELM, 'template', 'lab', str(ROOT)], capture_output=True, text=True, check=True)
        cls.docs = [d for d in yaml.safe_load_all(result.stdout) if d]

    def config(self, suffix):
        return next(d['data'] for d in self.docs if d['kind'] == 'ConfigMap' and d['metadata']['name'].endswith(suffix))

    def test_anchor_nat_and_policy_routes_cover_allocated_pools(self):
        for role in ('upf1', 'upf2'):
            data = self.config(role + '-configmap')
            for dnn in yaml.safe_load(data['upfcfg.yaml'])['dnnList']:
                self.assertIn('-s ' + dnn['cidr'] + ' -o n6 -j MASQUERADE', data['wrapper.sh'])
                self.assertIn('ip rule add from ' + dnn['cidr'] + ' table n6if', data['wrapper.sh'])
            self.assertNotIn('10.1.0.0/16', data['wrapper.sh'])

    def test_branch_receives_n3_and_n9_without_transport_nat(self):
        data = self.config('upfb-configmap')
        self.assertEqual(yaml.safe_load(data['upfcfg.yaml'])['gtpu']['ifList'][0]['addr'], '0.0.0.0')
        self.assertNotIn('-o n3 -j MASQUERADE', data['wrapper.sh'])
        self.assertNotIn('-o n9 -j MASQUERADE', data['wrapper.sh'])

    def test_osm_wait_checks_ngap_and_tunnel_and_keeps_tun_capabilities(self):
        gnb = next(d for d in self.docs if d['kind'] == 'Deployment' and d['metadata']['name'].endswith('ueransim-gnb'))['spec']['template']['spec']['containers'][0]
        for probe in ('startupProbe', 'readinessProbe', 'livenessProbe'):
            self.assertIn('is-ngap-up: true', gnb[probe]['exec']['command'][-1])
        ue = next(d for d in self.docs if d['kind'] == 'Deployment' and d['metadata']['name'].endswith('ueransim-ue'))['spec']['template']['spec']['containers'][0]
        self.assertTrue({'NET_ADMIN', 'NET_RAW', 'MKNOD'}.issubset(ue['securityContext']['capabilities']['add']))
        self.assertIn('uesimtun', ue['readinessProbe']['exec']['command'][-1])

    def test_modern_udr_and_authentication_settings_are_consistent(self):
        udr = yaml.safe_load(self.config('udr-configmap')['udrcfg.yaml'])
        self.assertEqual(udr['info']['version'], '1.1.0')
        self.assertEqual(udr['configuration']['dbConnectorType'], 'mongodb')
        auth = yaml.safe_load(self.config('ueransim-subscriber')['subscriber.json'])
        self.assertEqual(auth['authenticationSchema'], 'modern')
        self.assertEqual(auth['sequenceNumberFormat'], 'object')
        self.assertEqual(auth['initialSqn'], '000000000020')

if __name__ == '__main__':
    unittest.main()
