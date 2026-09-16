import copy,hashlib,importlib,unittest

def hx(label):return hashlib.sha256(label.encode()).hexdigest()

def record(kind='job',label='one',state=None,refs=None):
    states={'job':'SUCCEEDED','control':'ACCEPTED','submission':'TOMBSTONED'}
    if refs is None and kind=='job' and (state is None or state=='SUCCEEDED'):
        refs=['evidence:'+hx('effect-'+label)]
    return {'key':kind+':'+hx(label),'kind':kind,'local_id':hx(label),
        'state':state or states[kind],'intent_digest':hx(kind+'-intent-'+label),
        'input_digest':hx(kind+'-input-'+label),'proof_digest':hx(kind+'-proof-'+label),
        'refs':sorted(refs or []),'evidence_digest':hx('effect-'+label) if kind=='job' and (state is None or state=='SUCCEEDED') else None,
        'storage_bytes':1000,'reserved_bytes':0}

def fixture():
    j=record(refs=['evidence:'+hx('effect-one')]);c=record('control',refs=[j['key']]);s=record('submission',refs=[j['key']]);s['evidence_digest']=j['intent_digest']
    return {'schema':1,'profile':'management-record-lifecycle-local-v1','source':'MODEL_FIXTURE',
        'keeper':hx('keeper'),'store':hx('store'),'controller':hx('controller'),'controller_revision':1,
        'observation':hx('observation'),'gates':{k:True for k in ('jobs','control','submissions','archive_resolver')},
        'anchors':[{'key':'evidence:'+hx('effect-one'),'proof_digest':hx('effect-one')}],
        'records':sorted([j,c,s],key=lambda r:r['key'])}

class ModelTest(unittest.TestCase):
    def setUp(self):
        try:self.api=importlib.import_module('par_record_lifecycle')
        except ModuleNotFoundError:self.api=None
        self.assertIsNotNone(self.api,'management record lifecycle model not implemented')
        self.assertTrue(callable(getattr(self.api,'encode_inventory',None)), 'lifecycle contract API not implemented')
    def err(self,code,fn):
        with self.assertRaises(self.api.LifecycleError) as cm:fn()
        if code:self.assertEqual(cm.exception.code,code)
    def model(self):return self.api.LifecycleModel(fixture())
    def closed(self):
        m=self.model();m.close(m.plan(),controller_revision=1);return m
    def archived(self):
        m=self.closed();m.archive();return m
    def compacted(self):
        m=self.archived();m.compact();return m
