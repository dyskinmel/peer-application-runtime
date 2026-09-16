"""Boundary tests with explicitly synthetic decoded reports, NOT CRDT execution."""
import base64, copy, hashlib, importlib.util, json, unittest
from par_crypto.primitives import hashed
from auth_store_support import h

class SharedContractTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(importlib.util.find_spec('product.wp04.contracts') is not None,
                        'single-change actor/dependency contract has not been implemented')
        from product.wp04 import contracts as m
        self.m=m
        self.payload=b'CONTRACT-TEST-ONLY; this is not an Automerge change'
        self.header={0:'org.example.notes',1:h('space'),2:1,3:h('document'),4:1,5:h('device'),6:h('generation')[:16],7:1,8:None,9:h('schema'),10:[],11:len(self.payload),12:h('inner'),13:h('control'),14:1,15:0}
    def change(self,header=None,payload=None):
        return self.m.ChangeInput.create(self.header if header is None else header,self.payload if payload is None else payload,schema_id=h('schema'))
    def request(self):return self.m.core_request(self.change(),())
    def report(self):
        r=self.request()
        return {'profile':self.m.PROFILE,'requestDigest':self.m.request_digest(r),'engine':{'name':'@automerge/automerge','version':'3.4.1','kind':'contract-test-double','digest':'a'*64},'changes':[{'actor':r['candidate']['actor'],'sequence':'1','hash':r['candidate']['hash'],'dependencies':[]}], 'appliedHashes':[r['candidate']['hash']], 'missing':[], 'note':{'title':'test','body':'synthetic result','titleConflicts':[]},'schema':'note-v1-local'}
    def validate(self,value=None,**kw):return self.m.check_report(self.request(),self.report() if value is None else value,expected_engine={'name':'@automerge/automerge','version':'3.4.1','kind':'contract-test-double','digest':'a'*64},allow_contract_double=True,**kw)
    def bad(self,fn,code=None):
        with self.assertRaises(self.m.SharedChangeError) as cm:fn()
        if code:self.assertEqual(cm.exception.code,code)
    def test_actor_is_existing_domain_hash(self):self.assertEqual(self.change().actor,hashed('actor-id',[self.header[k] for k in (1,2,3,5,6)]))
    def test_generation_changes_actor(self):
        a=self.change().actor;self.header[6]=h('different')[:16];self.assertNotEqual(a,self.change().actor)
    def test_scope_changes_actor(self):
        a=self.change().actor;self.header[3]=h('other-document');self.assertNotEqual(a,self.change().actor)
    def test_payload_length_rejected(self):self.header[11]+=1;self.bad(self.change,'LENGTH_MISMATCH')
    def test_bool_sequence_rejected(self):self.header[7]=True;self.bad(self.change)
    def test_unsafe_js_sequence_rejected(self):self.header[7]=2**53;self.bad(self.change,'UNSUPPORTED_INTEGER_RANGE')
    def test_duplicate_dependencies_rejected(self):self.header[10]=[h('d'),h('d')];self.bad(self.change)
    def test_wrong_schema_rejected(self):self.header[9]=h('other');self.bad(self.change,'SCHEMA_MISMATCH')
    def test_wrong_kind_rejected(self):self.header[4]=2;self.bad(self.change,'UNSUPPORTED_KIND')
    def test_wrong_codec_rejected(self):self.header[14]=2;self.bad(self.change)
    def test_empty_payload_rejected(self):self.header[11]=0;self.bad(lambda:self.change(payload=b''))
    def test_mutable_payload_rejected(self):self.bad(lambda:self.change(payload=bytearray(self.payload)))
    def test_header_copied_before_callback(self):
        c=self.change();self.header[10].append(h('later'));self.assertEqual(c.header[10],[])
        c.header[10].append(h('again'));self.assertEqual(c.header[10],[])
    def test_canonical_request_digest(self):
        r=self.request();self.assertEqual(self.m.request_digest(r),hashlib.sha256(json.dumps(r,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest())
    def test_test_double_never_semantic_success(self):self.assertFalse(self.validate().semantic_validated)
    def test_test_double_rejected_without_explicit_scope(self):
        self.bad(lambda:self.m.check_report(self.request(),self.report(),expected_engine=self.report()['engine']), 'CORE_NOT_REAL')
    def test_body_not_validated_by_hash_of_raw_payload(self):
        r=self.report();r['changes'][0]['hash']=hashlib.sha256(self.payload).hexdigest();self.bad(lambda:self.validate(r),'INNER_OUTER_MISMATCH')
    def test_wrong_actor_rejected(self):
        r=self.report();r['changes'][0]['actor']='b'*64;self.bad(lambda:self.validate(r),'INNER_OUTER_MISMATCH')
    def test_wrong_sequence_rejected(self):
        r=self.report();r['changes'][0]['sequence']='2';self.bad(lambda:self.validate(r),'INNER_OUTER_MISMATCH')
    def test_wrong_dependencies_rejected(self):
        r=self.report();r['changes'][0]['dependencies']=['b'*64];self.bad(lambda:self.validate(r),'INNER_OUTER_MISMATCH')
    def test_more_than_one_change_rejected(self):
        r=self.report();r['changes'].append(copy.deepcopy(r['changes'][0]));self.bad(lambda:self.validate(r),'NOT_SINGLE_CHANGE')
    def test_no_added_change_rejected(self):
        r=self.report();r['changes']=[];self.bad(lambda:self.validate(r),'NOT_SINGLE_CHANGE')
    def test_pending_dependencies_not_applied(self):
        r=self.report();r['missing']=['b'*64];self.bad(lambda:self.validate(r),'DEPENDENCIES_MISSING')
    def test_exact_applied_set_not_count(self):
        r=self.report();r['appliedHashes']=['b'*64];self.bad(lambda:self.validate(r),'APPLIED_SET_MISMATCH')
    def test_duplicate_applied_hash_rejected(self):
        r=self.report();r['appliedHashes']*=2;self.bad(lambda:self.validate(r),'APPLIED_SET_MISMATCH')
    def test_wrong_request_digest_rejected(self):
        r=self.report();r['requestDigest']='b'*64;self.bad(lambda:self.validate(r),'CORE_CONTEXT_MISMATCH')
    def test_wrong_engine_rejected(self):
        r=self.report();r['engine']['version']='0.0.0';self.bad(lambda:self.validate(r),'CORE_IDENTITY_CHANGED')
    def test_extra_claims_rejected(self):
        r=self.report();r['productQualified']=True;self.bad(lambda:self.validate(r))
    def test_wrong_note_shape_rejected(self):
        r=self.report();r['note']['secret']=1;self.bad(lambda:self.validate(r))
    def test_lone_surrogate_rejected(self):
        r=self.report();r['note']['body']='\ud800';self.bad(lambda:self.validate(r))
    def test_no_text_normalization(self):
        r=self.report();r['note']['body']='e\u0301😀日本語';self.assertEqual(self.validate(r).note['body'],r['note']['body'])
    def test_conflicting_title_values_preserved(self):
        r=self.report();r['note']['titleConflicts']=['first','second'];self.assertEqual(self.validate(r).note['titleConflicts'],['first','second'])
    def test_report_copy_not_shared(self):
        v=self.validate();n=v.note;n['body']='mutated';self.assertEqual(v.note['body'],'synthetic result')
    def test_missing_declared_dep_blocks_before_core(self):
        self.header[10]=[h('missing')];self.bad(lambda:self.m.core_request(self.change(),()),'DEPENDENCIES_MISSING')
    def test_self_dependency_rejected(self):self.header[10]=[self.header[12]];self.bad(self.change,'SELF_DEPENDENCY')
    def test_sequence_one_cannot_claim_previous(self):self.header[8]=h('previous');self.bad(self.change,'PREVIOUS_MISMATCH')
    def test_sequence_later_requires_previous(self):self.header[7]=2;self.bad(self.change,'PREVIOUS_MISMATCH')
    def test_full_closure_plus_candidate_applied_set(self):
        deps=[];prior=None
        for i in range(128):
            hdr=copy.deepcopy(self.header);hdr[5]=h('writer'+str(i));hdr[12]=h('change'+str(i));hdr[10]=[] if prior is None else [prior]
            deps.append(self.m.Dependency(h('env'+str(i)),self.change(hdr)));prior=hdr[12]
        self.header[10]=[prior];request=self.m.core_request(self.change(),tuple(deps));report=self.report_for(request)
        result=self.m.check_report(request,report,expected_engine=report['engine'],allow_contract_double=True)
        self.assertFalse(result.semantic_validated)
    def report_for(self,request):
        r={'profile':self.m.PROFILE,'requestDigest':self.m.request_digest(request),'engine':{'name':'@automerge/automerge','version':'3.4.1','kind':'contract-test-double','digest':'a'*64},'changes':[{k:request['candidate'][k] for k in ('actor','sequence','hash','dependencies')}], 'appliedHashes':[d['hash'] for d in request['closure']]+[request['candidate']['hash']], 'missing':[], 'note':{'title':'test','body':'synthetic','titleConflicts':[]},'schema':'note-v1-local'}
        return r
    def dep(self,label,parents=(),**overrides):
        hdr=copy.deepcopy(self.header);hdr[5]=h('writer-'+label);hdr[12]=h(label);hdr[10]=list(parents);hdr.update(overrides)
        return self.m.Dependency(h('envelope-'+label),self.change(hdr))
    def test_extraneous_dependency_not_accepted(self):
        self.bad(lambda:self.m.core_request(self.change(),(self.dep('unused'),)),'EXTRANEOUS_DEPENDENCY')
    def test_dependency_wrong_epoch(self):
        dep=self.dep('dep');hdr=dep.change.header;hdr[2]=2;dep=self.m.Dependency(dep.envelope_id,self.change(hdr));self.header[10]=[h('dep')]
        self.bad(lambda:self.m.core_request(self.change(),(dep,)),'DEPENDENCY_SCOPE_MISMATCH')
    def test_dependency_cycle_is_not_accepted(self):
        a=self.dep('a',[h('b')]);b=self.dep('b',[h('a')]);self.header[10]=[h('a')]
        self.bad(lambda:self.m.core_request(self.change(),(a,b)),'DEPENDENCY_CYCLE')
    def test_duplicate_inner_hash_not_counted_twice(self):
        a=self.dep('a');self.header[10]=[h('a')]
        self.bad(lambda:self.m.core_request(self.change(),(a,a)),'DEPENDENCY_EQUIVOCATION')
    def test_closure_order_deterministic(self):
        a=self.dep('a');b=self.dep('b',[h('a')]);self.header[10]=[h('b')]
        self.assertEqual(self.m.core_request(self.change(),(b,a)),self.m.core_request(self.change(),(a,b)))
    def test_actor_equivocation_not_hidden_by_distinct_envelope(self):
        a=self.dep('a');b=self.dep('b');hdr=b.change.header;hdr[5]=a.change.header[5];b=self.m.Dependency(b.envelope_id,self.change(hdr));self.header[10]=[h('a'),h('b')]
        self.bad(lambda:self.m.core_request(self.change(),(a,b)),'ACTOR_EQUIVOCATION')
    def test_closure_count_budget(self):
        self.bad(lambda:self.m.core_request(self.change(),tuple(self.dep(str(i)) for i in range(129))),'RESOURCE_LIMIT')
