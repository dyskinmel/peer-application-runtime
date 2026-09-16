import importlib,importlib.util,tempfile,unittest
from pathlib import Path

class JournalTest(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('product.wp09.par_application_intent'),
                             'durable application intent is not implemented')
        self.m=importlib.import_module('product.wp09.par_application_intent')
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.parent=Path(self.tmp.name);self.parent.chmod(0o700);self.root=self.parent/'journal'
        self.intent=self.new_intent()
    def new_intent(self,**overrides):
        values=dict(scope=('app',b's'*32,b'd'*32,1,b'h'*32,b'c'*32),
          store_generation=b'g'*16,inbox_generation='a'*32,certificate_digest=b'f'*32,
          operation_id=b'o'*16,expected_revision=0,targets=(b't'*32,),
          authority_digest=b'r'*32,input_digest=b'i'*32,connection_generation=9)
        values.update(overrides);return self.m.ApplicationIntent(**values)
    def create(self):
        j=self.m.IntentJournal.create(self.root,self.intent.binding());self.addCleanup(j.close);return j
    def reopen(self,j,pin=None):
        pin=pin or j.pin();j.close()
        new=self.m.IntentJournal.open(self.root,self.intent.binding(),expected_pin=pin)
        self.addCleanup(new.close);return new
    def receipt(self,**overrides):
        r=dict(profile='par-document-apply-local-0035',operationId=(b'o'*16).hex(),revision=1,
          heads=['1'*64],inputIds=[(b't'*32).hex()],eventDigest='2'*64,candidatePersisted=True,
          innerValidated=False,applied=False,replicated=False,phase='CANDIDATE_ONLY',productQualified=False)
        r.update(overrides);return r
