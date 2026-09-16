"""Fixed public corpus, Node/OpenSSL route and fresh-process replay."""
import hashlib,json,shutil,subprocess,sys
from pathlib import Path
from auth_support import AuthTest,ROOT,decode,encode,domain,hashed,control_id,h,wrap,member_root

FIXTURE=ROOT/'experiments/space-auth/fixtures/authority-candidate.json'
def bridge(v):
    if type(v) is bytes:return {'$bytes':v.hex()}
    if type(v) is int:return {'$uint':str(v)}
    if type(v) is list:return [bridge(x) for x in v]
    if type(v) is dict:return {'$map':[[str(k),bridge(x)] for k,x in sorted(v.items())]}
    return v
class VectorTests(AuthTest):
    def corpus(self):
        self.assertTrue(FIXTURE.is_file(),'fixed public authority corpus has not been generated')
        return json.loads(FIXTURE.read_text())
    def state_from(self,c):
        st=self.require('chain').AuthorityState(self.p,c['app'],bytes.fromhex(c['space']),bytes.fromhex(c['genesis']))
        for entry in c['controls']:
            st.observe(bytes.fromhex(entry['raw']))
            st.provide_membership([bytes.fromhex(x) for x in entry['pages']])
            self.assertEqual(st.head.hex(),entry['id'])
            self.assertEqual(st.epoch,entry['epoch'])
        return st
    def test_fixed_corpus_replay(self):
        c=self.corpus();st=self.state_from(c)
        self.assertEqual(st.status()['state'],'EPOCH_PENDING');self.assertEqual(st.sequence,4)
    def test_fixed_corpus_genesis_hash(self):
        c=self.corpus();self.assertEqual(hashed('space-id',[decode(bytes.fromhex(c['genesis']))[0]]).hex(),c['space'])
    def test_fixed_corpus_membership_roots(self):
        c=self.corpus();m=self.require('membership')
        for item in c['controls']:
            body=decode(decode(bytes.fromhex(item['raw']))[0]);view=m.verify_membership(body[6],[bytes.fromhex(x) for x in item['pages']]);self.assertEqual(view.root,body[6])
    def test_fixed_corpus_all_signatures(self):
        for r in self.corpus()['signatures']:
            self.assertEqual(domain(r['label'],[bytes.fromhex(r['body'])]).hex(),r['message'])
            self.p.verify(bytes.fromhex(r['pk']),bytes.fromhex(r['message']),bytes.fromhex(r['signature']))
    def test_fixed_corpus_known_fork_stays_frozen(self):
        c=self.corpus();st=self.state_from(c)
        self.reject('CONTROL_FORK',lambda:st.observe(bytes.fromhex(c['fork'])))
        self.assertEqual(st.status()['state'],'CONTROL_FORK')
    def test_fixed_corpus_activation(self):
        c=self.corpus();st=self.state_from(c);a=c['activation']
        result=st.activate(bytes.fromhex(a['certificate']),bytes.fromhex(a['recipient_secret_public_fixture']),bytes.fromhex(a['package']),[bytes.fromhex(x) for x in a['package_ids']],bytes.fromhex(a['manifest']),{bytes.fromhex(k):bytes.fromhex(v) for k,v in a['blocks'].items()})
        self.assertEqual(result['epoch'],2);self.assertFalse(result['automerge_validated'])
        self.assertEqual(st.authorize(bytes.fromhex(a['certificate']),'write').epoch,2)
    def test_fixed_corpus_is_labeled_test_only(self):
        c=self.corpus();self.assertEqual(c['classification'],'PUBLIC_SYNTHETIC_TEST_ONLY');self.assertFalse(c['independent_review'])
    def test_fixed_corpus_digest_anchor(self):
        c=self.corpus();r=self.require('replay');st=self.state_from(c)
        raw=r.export_public_replay(st);self.assertEqual(hashed('auth-local/replay',[raw]).hex(),c['replay_digest'])
    def node_wire(self,requests):
        self.assertIsNotNone(shutil.which('node'),'Node required for separate codec route')
        p=subprocess.run([shutil.which('node'),str(ROOT/'experiments/g0-wire/oracle.mjs')],input=''.join(json.dumps(x)+'\n' for x in requests),text=True,capture_output=True,timeout=15)
        self.assertEqual(p.returncode,0,p.stderr);v=[json.loads(x) for x in p.stdout.splitlines()];self.assertEqual(len(v),len(requests));return v
    def test_node_domains_equal_fixed_signing_bytes(self):
        c=self.corpus();rows=c['signatures'];req=[{'kind':'cbor','op':'encode','value':bridge(['PAR',1,r['label'],[bytes.fromhex(r['body'])]])} for r in rows]
        for r,out in zip(rows,self.node_wire(req)):
            self.assertTrue(out['ok']);self.assertEqual(out['hex'],r['message'])
    def test_node_canonical_control_bytes_equal(self):
        rows=self.corpus()['controls'];req=[{'kind':'cbor','op':'decode','hex':r['raw']} for r in rows]
        for r,out in zip(rows,self.node_wire(req)):self.assertTrue(out['ok']);self.assertEqual(out['hex'],r['raw'])
    def test_node_rejects_trailing_control_data(self):
        rows=self.corpus()['controls'];outs=self.node_wire([{'kind':'cbor','op':'decode','hex':r['raw']+'00'} for r in rows]);self.assertTrue(all(not o['ok'] for o in outs))
    def node_crypto(self,requests):
        self.assertIsNotNone(shutil.which('node'),'Node required for OpenSSL route')
        p=subprocess.run([shutil.which('node'),str(ROOT/'experiments/g0-crypto/node_oracle.mjs')],input=json.dumps(requests),text=True,capture_output=True,timeout=15)
        self.assertEqual(p.returncode,0,p.stderr);return json.loads(p.stdout)
    def test_node_openssl_verifies_fixed_signatures(self):
        rows=self.corpus()['signatures'];outs=self.node_crypto([{'op':'ed-verify','pk':r['pk'],'message':r['message'],'signature':r['signature']} for r in rows]);self.assertEqual(len(outs),len(rows));self.assertTrue(all(o.get('valid') for o in outs))
    def test_node_openssl_rejects_mutated_signature(self):
        rows=self.corpus()['signatures'];outs=self.node_crypto([{'op':'ed-verify','pk':r['pk'],'message':r['message'],'signature':(bytes([int(r['signature'][:2],16)^1])+bytes.fromhex(r['signature'][2:])).hex()} for r in rows]);self.assertTrue(all(o.get('valid') is False for o in outs))
    def test_fresh_process_replay_requires_reactivation(self):
        self.corpus();script=r'''
import sys,json
from pathlib import Path
root=Path(sys.argv[1]);sys.dont_write_bytecode=True
for rel in ['experiments/space-auth','experiments/g0-wire','experiments/g0-crypto']:sys.path.insert(0,str(root/rel))
from par_auth.replay import restore_public_replay
from par_crypto.provider import SodiumProvider
c=json.loads((root/'experiments/space-auth/fixtures/authority-candidate.json').read_text())
p=SodiumProvider(json.loads((root/'policy/crypto-provider.json').read_text()),allow_legacy_experiment=True)
s=restore_public_replay(p,c['app'],bytes.fromhex(c['space']),bytes.fromhex(c['controls'][-1]['id']),bytes.fromhex(c['replay_digest']),bytes.fromhex(c['replay']),minimum_sequence=4)
print(json.dumps(s.status()))
'''
        p=subprocess.run([sys.executable,'-I','-S','-c',script,str(ROOT)],capture_output=True,text=True,timeout=15)
        self.assertEqual(p.returncode,0,p.stderr);v=json.loads(p.stdout);self.assertEqual(v['state'],'EPOCH_PENDING');self.assertIsNone(v['active_epoch'])
    def test_generated_checkpoint_trace_retains_roots(self):
        st=self.state();raw=self.s.raw()
        for i in range(128):
            body=self.s.next(raw,action=5);raw=self.s.raw(body);st.observe(raw);st.provide_membership(self.s.pages)
            self.assertEqual(st.sequence,i+2);self.assertEqual(st.epoch,1);self.assertEqual(st.membership.root,self.s.root)
    def test_generated_invalid_signatures_do_not_advance(self):
        st=self.state();body=self.s.next(self.s.raw());raw=self.s.raw(body);entry=decode(raw)
        for i in range(64):
            sig=bytearray(entry[1]);sig[i]^=1;bad=encode({**entry,1:bytes(sig)})
            self.reject('CRYPTO_INVALID',lambda:st.observe(bad));self.assertEqual(st.sequence,1);self.assertFalse(st.frozen)
    def test_generated_keeper_toggle_preserves_content_projection(self):
        m=self.require('membership');st=self.state();raw=self.s.raw();content=st.membership.content_members
        for i in range(64):
            entries=self.s.entries if i%2 else self.s.entries[:2];pages=m.build_membership(entries);view=m.verify_membership(member_root(pages),pages)
            body=self.s.next(raw,action=2);body[6]=view.root;raw=self.s.raw(body);st.observe(raw);st.provide_membership(list(view.pages))
            self.assertEqual(st.membership.content_members,content);self.assertEqual(st.epoch,1)
