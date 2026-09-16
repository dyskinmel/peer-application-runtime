#!/usr/bin/env python3
"""Explicit regeneration of PUBLIC synthetic data. Never executed by normal tests."""
from pathlib import Path
import sys,json,hashlib
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
from tools.check_recovery import GROUPS
from file_support import FileTest
from par_recovery import Grant,collect,index_id,Pin,verify
from auth_support import h,control_id

def main():
    c=FileTest();c.setUp()
    try:
        c.data=b'Public synthetic recovery fixture. Not production data.\n';c.source.write_bytes(c.data);c.start();counter=0
        def rng(n):
            nonlocal counter
            counter+=1;return hashlib.sha256(b'public-test-only'+counter.to_bytes(4,'big')).digest()[:n]
        w=c.fw(random_source=rng);r=w.commit(c.stage(w),*c.request()[1:]);d=c.s.devices[1]
        g=Grant(d['cert'],c.b['packages'][d['id']],tuple(c.b['ids']),c.b['manifest'],tuple(sorted(c.b['seeds'].items())))
        b=collect(c.db,c.s.space,(r.envelope_id,),g,c.s.devices[0]['cert'],c.s.devices[0]['seed'])
        p=Pin(c.s.app,c.s.space,control_id(c.b['raw']),1,1,d['id'],d['cid'],(r.envelope_id,),index_id(b.index))
        verify(b,p,c.p,d['secret'])
        pin=[p.app,p.space.hex(),p.head.hex(),p.sequence,p.epoch,p.recipient_id.hex(),p.certificate_id.hex(),[i.hex() for i in p.roots],p.index_id.hex()]
        v={'kind':'SELF_GENERATED_PUBLIC_CANDIDATE_VECTOR_NOT_INDEPENDENT_KAT','pin':pin,'index_hex':b.index.hex(),'objects':{i.hex():raw.hex() for i,raw in b.objects.items()},'plaintext_hex':c.data.hex()}
        (ROOT/'experiments/recovery-closure/fixtures/closure-current-epoch.json').write_text(json.dumps(v,indent=2)+'\n')
    finally:c.doCleanups()
if __name__=='__main__':main()
