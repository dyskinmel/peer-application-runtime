#!/usr/bin/env python3
"""EXPLICIT fixture regeneration, never called by tests. All secret values are public synthetic fixtures."""
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True
for rel in ['tests/product/space-auth','experiments/space-auth','experiments/g0-crypto','experiments/g0-wire']:sys.path.insert(0,str(ROOT/rel))
from auth_support import provider,Scenario,epoch_bundle,decode,domain,hashed,control_id,h,pages_for,member_root
from par_auth.chain import AuthorityState
from par_auth.replay import export_public_replay
from par_auth.admission import create_join,issue_admission

def generate():
    p=provider();s=Scenario(p);first=epoch_bundle(s);pages=pages_for(s.entries[:2])
    b2=s.next(first['raw']);b2[6]=member_root(pages);raw2=s.raw(b2)
    b3=s.next(raw2,action=4);raw3=s.raw(b3,new_seed=s.owner1)
    b4=s.next(raw3,action=3);b4[12]=None;b4[11]=p.sign_public(s.owner1)
    fourth=epoch_bundle(s,body=b4,secret=h('fixed-epoch2-secret'),entries=s.entries[:2],owner=s.owner1)
    controls=[(first['raw'],first['pages']),(raw2,pages),(raw3,pages),(fourth['raw'],fourth['pages'])]
    state=AuthorityState(p,s.app,s.space,s.genesis);records=[];signatures=[]
    def signed(name,raw,label):
        o=decode(raw);signatures.append({'name':name,'label':label,'body':o[0].hex(),'pk':o[1].hex(),'signature':o[2].hex(),'message':domain(label,[o[0]]).hex()})
    signed('genesis',s.genesis,'genesis-sign')
    for i,d in enumerate(s.devices):signed('certificate-'+str(i),d['cert'],'certificate-sign')
    for raw,pp in controls:
        state.observe(raw);state.provide_membership(pp);o=decode(raw);b=decode(o[0])
        records.append({'raw':raw.hex(),'id':control_id(raw).hex(),'pages':[x.hex() for x in pp],'sequence':b[2],'epoch':b[3]})
        for field,label,pk in [(1,'control-sign',b[11])]+([(2,'authority-possession',b[12])] if 2 in o else []):
            signatures.append({'name':label+'-'+str(b[2]),'label':label,'body':o[0].hex(),'pk':pk.hex(),'signature':o[field].hex(),'message':domain(label,[o[0]]).hex()})
    d=s.devices[0];req=create_join(p,d['seed'],s.app,s.space,d['cert'],h('fixed-invite'),2)
    adm=issue_admission(state,s.owner1,d['cert'],req,expected_nonce=h('fixed-invite'),expected_role=2,minimum_sequence=4)
    signed('join',req,'join-request');signed('admission',adm,'admission-sign')
    forkbody=dict(b2);forkbody[7]=h('competing-resource-policy');fork=s.raw(forkbody)
    replay=export_public_replay(state)
    a={'certificate':d['cert'].hex(),'recipient_secret_public_fixture':d['secret'].hex(),'package':fourth['packages'][d['id']].hex(),'package_ids':[x.hex() for x in fourth['ids']],'manifest':fourth['manifest'].hex(),'blocks':{k.hex():v.hex() for k,v in fourth['seeds'].items()}}
    return {'schema_version':1,'classification':'PUBLIC_SYNTHETIC_TEST_ONLY','independent_review':False,'profile':'auth-local-v0.1','app':s.app,'space':s.space.hex(),'genesis':s.genesis.hex(),'controls':records,'signatures':signatures,'join':req.hex(),'admission':adm.hex(),'fork':fork.hex(),'activation':a,'replay':replay.hex(),'replay_digest':hashed('auth-local/replay',[replay]).hex()}
if __name__=='__main__':
    path=ROOT/'experiments/space-auth/fixtures/authority-candidate.json';path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(generate(),ensure_ascii=False,indent=2)+'\n');print(path)
