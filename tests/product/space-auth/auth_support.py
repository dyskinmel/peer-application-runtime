"""Synthetic public keys/data; independent fixture construction from the draft."""
from pathlib import Path
import hashlib, importlib, json, unittest
from par_wire.codec import encode, decode
from par_crypto.provider import SodiumProvider
from par_crypto.primitives import hashed, domain
from par_crypto import objects
ROOT=Path(__file__).resolve().parents[3]
def h(label):return hashlib.sha256(label.encode()).digest()
def provider():return SodiumProvider(json.loads((ROOT/'policy/crypto-provider.json').read_text()),allow_legacy_experiment=True)
def module(name):
    try:return importlib.import_module('par_auth.'+name)
    except ModuleNotFoundError as e:
        if e.name=='par_auth' or e.name.startswith('par_auth.'):return None
        raise

def pages_for(entries):
    items=sorted(entries,key=lambda x:x[0]);return [encode(items[i:i+64]) for i in range(0,len(items),64)]
def member_root(pages):return hashed('membership-root',[[hashed('member-page-id',[x]) for x in pages]])
def wrap(p,seed,body,new_seed=None):
    raw=encode(body);out={0:raw,1:p.sign(seed,domain('control-sign',[raw]))}
    if new_seed is not None:out[2]=p.sign(new_seed,domain('authority-possession',[raw]))
    return encode(out)
def control_id(raw):return hashed('control-id',[raw])

class Scenario:
    def __init__(self,p):
        self.p=p;self.app='org.example.auth';self.owner=h('authority-0');self.owner1=h('authority-1');self.secret=h('content-1')
        self.policy=h('resource-policy');self.feature=h('feature-policy');self.devices=[]
        for i,role in enumerate([2,1,3]):
            s=h('sign-'+str(i));x=h('recipient-'+str(i));a=h('account-'+str(i))
            cert=objects.create_certificate(p,a,self.app,p.sign_public(s),p.dh_public(x),h('serial-'+str(i))[:16])
            did=hashed('device-id',[self.app,p.sign_public(s)]);cid=objects.certificate_id(cert)
            self.devices.append({'seed':s,'secret':x,'cert':cert,'id':did,'cid':cid,'role':role})
        self.entries=[{0:d['id'],1:d['cid'],2:d['role']} for d in self.devices];self.pages=pages_for(self.entries);self.root=member_root(self.pages)
        b={0:1,1:self.app,2:p.sign_public(self.owner),3:h('genesis-salt'),4:self.root,5:self.policy}
        self.genesis=objects._signed(p,self.owner,'genesis-sign',b);self.space=hashed('space-id',[encode(b)])
        self.initial={0:self.app,1:self.space,2:1,3:1,4:self.space,5:1,6:self.root,7:self.policy,8:h('package-root-1'),9:h('seed-root-1'),10:h('set-1')[:16],11:p.sign_public(self.owner),12:None,13:self.feature}
    def raw(self,body=None,seed=None,new_seed=None):return wrap(self.p,seed or self.owner,body or self.initial,new_seed)
    def next(self,previous,action=2,**changes):
        raw=self.raw(previous) if type(previous) is dict else previous
        b=decode(decode(raw)[0]);b[2]+=1;b[4]=control_id(raw);b[5]=action
        if action==3:b[3]+=1;b[8]=h('packages-'+str(b[3]));b[9]=h('seeds-'+str(b[3]));b[10]=h('set-'+str(b[3]))[:16]
        if action==4:b[12]=self.p.sign_public(self.owner1)
        return b

class AuthTest(unittest.TestCase):
    def setUp(self):self.p=provider();self.s=Scenario(self.p)
    def require(self,name):
        m=module(name);self.assertIsNotNone(m,'Space auth '+name+' is not implemented');return m
    def state(self,ready=True,initial=None):
        m=self.require('chain');st=m.AuthorityState(self.p,self.s.app,self.s.space,self.s.genesis)
        if ready:st.observe(self.s.raw(initial));st.provide_membership(self.s.pages)
        return st
    def reject(self,code,fn):
        E=self.require('errors').AuthError
        with self.assertRaises(E) as cm:fn()
        if code:self.assertEqual(cm.exception.code,code)

# Seed/root fixture format is a candidate overlay, built here independently of the receiver.
def epoch_bundle(s,body=None,secret=None,entries=None,owner=None):
    b=dict(body or s.initial);secret=secret or s.secret;entries=entries or s.entries;owner=owner or s.owner
    pp=pages_for(entries);b[6]=member_root(pp);packages={}
    for d in s.devices:
        entry=next((e for e in entries if e[0]==d['id']),None)
        if entry is None or entry[2] not in (1,2):continue
        ctx={0:s.app,1:s.space,2:b[3],3:b[10],4:d['id'],5:d['cid'],6:b[6]}
        packages[d['id']]=objects.seal_package(s.p,owner,s.p.dh_public(d['secret']),ctx,secret,random_source=lambda n:h('hpke-'+d['id'].hex()+str(b[3]))[:n])
    ids=sorted(objects.package_id(raw) for raw in packages.values());b[8]=objects.package_root(ids)
    seed=h('object-seed');plain=b'opaque seed: not an Automerge document';header={0:s.app,1:s.space,2:b[3],3:seed,4:5,5:0,6:0,7:len(plain)}
    raw=objects.seal_block(s.p,secret,header,plain,h('seed-nonce-'+str(b[3]))[:24]);bid=objects.block_id(raw)
    descriptor={0:1,1:s.app,2:s.space,3:b[3],4:b[10],5:[{0:seed,1:bid,2:0,3:len(plain),4:hashlib.sha256(plain).digest()}],6:[]}
    manifest=encode(descriptor);b[9]=hashed('auth-local/seed-root',[manifest])
    return {'body':b,'raw':s.raw(b,owner),'pages':pp,'packages':packages,'ids':ids,'manifest':manifest,'seeds':{bid:raw},'plain':plain,'secret':secret}

def active_state(test,bundle=None,index=0):
    bundle=bundle or epoch_bundle(test.s);st=test.state(False);st.observe(bundle['raw']);st.provide_membership(bundle['pages'])
    activate(st,test.s,bundle,index);return st,bundle

def activate(st,s,bundle,index=0):
    d=s.devices[index];return st.activate(d['cert'],d['secret'],bundle['packages'].get(d['id'],next(iter(bundle['packages'].values()))),bundle['ids'],bundle['manifest'],bundle['seeds'])
