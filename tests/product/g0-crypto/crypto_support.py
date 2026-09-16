"""Public, deterministic test material; never import into a product key path."""
from pathlib import Path
import json, unittest, importlib
ROOT=Path(__file__).resolve().parents[3]
FIX=ROOT/'experiments/g0-crypto/fixtures'
PIN=ROOT/'policy/crypto-provider.json'
def fixture(name):return json.loads((FIX/name).read_text())
def module(name):
    try:return importlib.import_module('par_crypto.'+name)
    except ModuleNotFoundError as exc:
        if exc.name=='par_crypto' or exc.name.startswith('par_crypto.'):return None
        raise
class CryptoTest(unittest.TestCase):
    def setUp(self):
        self.provider_module=module('provider')
        self.assertIsNotNone(self.provider_module,'G0 crypto provider has not been implemented')
        self.p=self.provider_module.SodiumProvider(json.loads(PIN.read_text()),allow_legacy_experiment=True)
    def require(self,name):
        m=module(name);self.assertIsNotNone(m,'G0 '+name+' has not been implemented');return m
    def reject(self,code,fn):
        E=self.require('errors').CryptoError
        with self.assertRaises(E) as cm:fn()
        if code is not None:self.assertEqual(cm.exception.code,code)
