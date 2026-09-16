#!/usr/bin/env python3
"""Explicit maintenance generator for a public candidate vector, NOT an independent KAT."""
import json,tempfile,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
from tools.check_keeper import GROUPS
from auth_support import provider,h
from par_recovery import Pin
from par_keeper import *
from par_keeper.contract import authority_body

def generate():
    v=json.loads((ROOT/'experiments/recovery-closure/fixtures/closure-current-epoch.json').read_text());pp=v['pin']
    pin=Pin(pp[0],bytes.fromhex(pp[1]),bytes.fromhex(pp[2]),pp[3],pp[4],bytes.fromhex(pp[5]),bytes.fromhex(pp[6]),tuple(bytes.fromhex(x) for x in pp[7]),bytes.fromhex(pp[8]))
    index=bytes.fromhex(v['index_hex']);objects={bytes.fromhex(k):bytes.fromhex(x) for k,x in v['objects'].items()}
    p=provider();ks=h('keeper-signing');subject=h('sign-1');authority=Authority(pin.app,pin.space,pin.head,pin.sequence,pin.epoch,p.sign_public(h('authority-0')))
    class Clock:
        def sample(self):return Tick(h('fixture-boot'),10**10)
    cap=issue_capability(p,h('authority-0'),authority,p.sign_public(ks),p.sign_public(subject),pin.index_id,tuple(METHODS),60,h('fixture-capability'))
    request=make_call(p,subject,cap,'reserve',None,h('fixture-reserve'),reserve_payload(index,pin,30))
    with tempfile.TemporaryDirectory() as td:
        with Keeper(Path(td)/'keeper',p,ks,authority,quota_bytes=1048576,clock=Clock(),allow_unpatched_sqlite=True) as k:
            lid=k.reserve(index,pin,30,cap,request)
            for oid,raw in sorted(objects.items()):
                call=make_call(p,subject,cap,'put',lid,h('put-'+oid.hex()),put_payload(oid,raw));k.put(lid,oid,raw,cap,call)
            seal=make_call(p,subject,cap,'seal',lid,h('fixture-seal'),None);receipt=k.seal(lid,cap,seal)
    return {'kind':'SELF_GENERATED_PUBLIC_CANDIDATE_VECTOR_NOT_INDEPENDENT_KAT','recovery_fixture':'experiments/recovery-closure/fixtures/closure-current-epoch.json','keeper_public_hex':p.sign_public(ks).hex(),
            'capability_hex':cap.hex(),'reserve_call_hex':request.hex(),'seal_call_hex':seal.hex(),'lease_id_hex':lid.hex(),'receipt_hex':receipt.hex()}
if __name__=='__main__':
    if sys.argv[1:]!=['--write']:raise SystemExit('Explicit --write required; ordinary tests never regenerate frozen vectors.')
    out=ROOT/'experiments/keeper-retention/fixtures/retention-receipt.json';out.parent.mkdir(exist_ok=True);out.write_text(json.dumps(generate(),indent=2)+'\n')
