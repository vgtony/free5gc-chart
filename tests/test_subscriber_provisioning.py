"""Rendering tests and opt-in real MongoDB checks in an isolated test namespace.

SUBSCRIBER_TEST_NAMESPACE must point at a disposable namespace with pod/mongodb.
Never point this suite at application data: it drops the provision_test database.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
HELM = os.environ.get('HELM', 'helm')
NS = os.environ.get('SUBSCRIBER_TEST_NAMESPACE')
KEY = '465b5ce8b199b49faa5f0a2ee238a6bc'
OP = 'cdc202d5123e20f62b6d676ac72cb318'
OPC = 'cd63cb71954a9f4e48a5994e37a02baf'


def render(enabled=True, external=False):
    values = {'ueransim': {'provisioning': {'enabled': enabled}, 'ue': {
        'auth': {'create': not external, 'key': KEY, 'op': OPC},
        'existingAuthSecret': 'external-auth' if external else '',
    }}}
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'values.json'
        path.write_text(json.dumps(values))
        result = subprocess.run([HELM, 'template', 'provision-test', str(ROOT), '-f', str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return [d for d in yaml.safe_load_all(result.stdout) if d]


class Rendering(unittest.TestCase):
    def test_init_container_gates_ue_and_shares_secret(self):
        for external in (False, True):
            docs = render(external=external)
            ue = next(d for d in docs if d['kind'] == 'Deployment' and d['metadata']['name'].endswith('ueransim-ue'))
            spec = ue['spec']['template']['spec']
            init = spec['initContainers'][0]
            self.assertEqual(init['name'], 'provision-subscriber')
            self.assertEqual(init['env'][:2], spec['containers'][0]['env'])
            self.assertFalse(spec['automountServiceAccountToken'])
            config = next(d for d in docs if d['kind'] == 'ConfigMap' and d['metadata']['name'].endswith('-subscriber'))
            self.assertNotIn(KEY, config['data']['subscriber.json'])
            self.assertIn('"sd": "010203"', config['data']['subscriber.json'])
            self.assertNotIn(OPC, config['data']['subscriber.json'])
            self.assertNotIn('helm.sh/hook', str(docs))

    def test_disabled_does_not_access_database(self):
        docs = render(enabled=False)
        ue = next(d for d in docs if d['kind'] == 'Deployment' and d['metadata']['name'].endswith('ueransim-ue'))
        self.assertNotIn('initContainers', ue['spec']['template']['spec'])
        self.assertFalse(any(d['metadata']['name'].endswith('-subscriber') for d in docs))


@unittest.skipUnless(NS, 'requires isolated MongoDB test namespace')
class MongoIntegration(unittest.TestCase):
    def exec(self, args, data=None, check=True):
        result = subprocess.run(['kubectl', '-n', NS, 'exec', '-i', 'mongodb', '--', *args], input=data, capture_output=True, text=True)
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def js(self, source):
        return self.exec(['mongosh', '--quiet', 'mongodb://127.0.0.1:27017/provision_test', '--eval', 'const check = require("assert").strictEqual; ' + source])

    def setUp(self):
        self.js('db.dropDatabase()')
        cm = next(d for d in render() if d['kind'] == 'ConfigMap' and d['metadata']['name'].endswith('-subscriber'))
        self.config = json.loads(cm['data']['subscriber.json'])
        self.config.update(database='provision_test', waitSeconds=2, authenticationSchema='legacy', sequenceNumberFormat='string', initialSqn='000000000000', migrateAuthentication=False)
        self.exec(['sh', '-c', 'cat > /tmp/provision-subscriber.js'], cm['data']['provision-subscriber.js'])

    def provision(self, key=KEY, op=OPC, check=True, uri='mongodb://127.0.0.1:27017/?serverSelectionTimeoutMS=500'):
        self.exec(['sh', '-c', 'cat > /tmp/subscriber.json'], json.dumps(self.config))
        return self.exec(['env', 'SUBSCRIBER_CONFIG=/tmp/subscriber.json', 'MONGO_URI=' + uri,
                          'UE_KEY=' + key, 'UE_OP=' + op, 'mongosh', '--quiet', '--nodb', '/tmp/provision-subscriber.js'], check=check)

    def test_creates_complete_subscription_and_preserves_sqn_and_other_subscriber(self):
        self.js('db.getCollection("subscriptionData.authenticationData.authenticationSubscription").insertOne({ueId:"unrelated",keep:true})')
        self.provision()
        self.js('''
const auth=db.getCollection('subscriptionData.authenticationData.authenticationSubscription');
check(auth.findOne({ueId:'imsi-208930000000003'}).opc.opcValue, 'cd63cb71954a9f4e48a5994e37a02baf');
check(auth.findOne({ueId:'imsi-208930000000003'}).sequenceNumber, '000000000000');
auth.updateOne({ueId:'imsi-208930000000003'}, {$set:{sequenceNumber:'000000000123'}});
check(db.getCollection('subscriptionData.provisionedData.smData').findOne({ueId:'imsi-208930000000003'}).dnnConfigurations.internet.pduSessionTypes.defaultSessionType, 'IPV4');
for (const c of ['subscriptionData.provisionedData.amData','subscriptionData.provisionedData.smfSelectionSubscriptionData','policyData.ues.amData','policyData.ues.smData']) check(db.getCollection(c).countDocuments({ueId:'imsi-208930000000003'}),1);
''')
        self.provision()
        self.js('''
const auth=db.getCollection('subscriptionData.authenticationData.authenticationSubscription');
check(auth.findOne({ueId:'imsi-208930000000003'}).sequenceNumber, '000000000123');
check(auth.findOne({ueId:'unrelated'}).keep,true);
check(auth.countDocuments({ueId:'imsi-208930000000003'}),1);
check(db.getCollection('subscriptionData.provisionedData.smData').countDocuments({ueId:'imsi-208930000000003'}),1);
''')

    def test_op_derivation_and_object_sequence_format(self):
        self.config.update(opType='OP', sequenceNumberFormat='object')
        self.provision(op=OP)
        self.js("const a=db.getCollection('subscriptionData.authenticationData.authenticationSubscription').findOne({ueId:'imsi-208930000000003'}); check(a.opc.opcValue,'" + OPC + "'); check(a.sequenceNumber.sqn,'000000000000');")

    def test_conflicting_credentials_do_not_overwrite(self):
        self.provision()
        result = self.provision(key='00'*16, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Existing subscriber authentication differs', result.stderr + result.stdout)
        self.js("check(db.getCollection('subscriptionData.authenticationData.authenticationSubscription').findOne({ueId:'imsi-208930000000003'}).permanentKey.permanentKeyValue,'" + KEY + "')")

    def test_modern_schema_creates_credentials_and_preserves_advanced_sqn(self):
        self.config.update(authenticationSchema='modern', sequenceNumberFormat='object', initialSqn='000000000020')
        self.provision()
        self.js("const c=db.getCollection('subscriptionData.authenticationData.authenticationSubscription'); const a=c.findOne({ueId:'imsi-208930000000003'}); check(a.encPermanentKey,'" + KEY + "'); check(a.encOpcKey,'" + OPC + "'); check(a.permanentKey,undefined); check(a.sequenceNumber.sqn,'000000000020'); c.updateOne({_id:a._id},{$set:{'sequenceNumber.sqn':'000000000123'}});")
        self.provision()
        self.js("check(db.getCollection('subscriptionData.authenticationData.authenticationSubscription').findOne({ueId:'imsi-208930000000003'}).sequenceNumber.sqn,'000000000123')")

    def test_migration_is_explicit_and_preserves_sqn(self):
        self.provision()
        self.js("db.getCollection('subscriptionData.authenticationData.authenticationSubscription').updateOne({ueId:'imsi-208930000000003'},{$set:{sequenceNumber:'000000000123'}})")
        self.config.update(authenticationSchema='modern', sequenceNumberFormat='object')
        result = self.provision(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('enable migrateAuthentication', result.stdout + result.stderr)
        self.config['migrateAuthentication'] = True
        self.provision()
        self.provision()
        self.js("const a=db.getCollection('subscriptionData.authenticationData.authenticationSubscription').findOne({ueId:'imsi-208930000000003'}); check(a.encPermanentKey,'" + KEY + "'); check(a.encOpcKey,'" + OPC + "'); check(a.sequenceNumber.sqn,'000000000123')")
        result = self.provision(key='00'*16, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('authentication differs', result.stdout + result.stderr)

    def test_migration_rejects_bad_sqn_without_writing_keys(self):
        self.provision()
        self.js("db.getCollection('subscriptionData.authenticationData.authenticationSubscription').updateOne({ueId:'imsi-208930000000003'},{$set:{sequenceNumber:'invalid'}})")
        self.config.update(authenticationSchema='modern', sequenceNumberFormat='object', migrateAuthentication=True)
        self.assertNotEqual(self.provision(check=False).returncode, 0)
        self.js("const a=db.getCollection('subscriptionData.authenticationData.authenticationSubscription').findOne({ueId:'imsi-208930000000003'}); check(a.encPermanentKey,undefined); check(a.sequenceNumber,'invalid')")

    def test_unavailable_database_fails_with_bounded_retry(self):
        result = self.provision(check=False, uri='mongodb://127.0.0.1:1/?serverSelectionTimeoutMS=500&connectTimeoutMS=500')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('MongoDB unavailable', result.stdout + result.stderr)

    def test_invalid_input_writes_nothing(self):
        self.config['sessions'][0]['type'] = 'IPv6'
        self.assertNotEqual(self.provision(check=False).returncode, 0)
        self.js("check(db.getCollection('subscriptionData.authenticationData.authenticationSubscription').countDocuments({}),0)")


if __name__ == '__main__':
    unittest.main()
