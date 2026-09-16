from pathlib import Path
import sys,asyncio,json
ROOT=Path(__file__).resolve().parents[3];sys.dont_write_bytecode=True
for p in[ROOT]+[ROOT/'tests/product'/n for n in('fetch-owner','secure-fetch','secure-transport','causal-exchange','auth-store','space-auth')]+list((ROOT/'experiments').iterdir()):sys.path.insert(0,str(p))
from test_owner import OwnerTests
async def main():
    t=OwnerTests('test_observe_no_automatic_network_or_apply');t.setUpClass();t.setUp()
    try:
        await t.asyncSetUp();waiting=await t.observed();proposed=await t.proposed()
        accepted=await t.call('accept',expectedRevision=proposed['observation']['revision'],proposalId=proposed['proposal']['id'])
        fetched=await t.call('fetch',expectedRevision=accepted['observation']['revision'],planDigest=accepted['selection']['planDigest'])
        validated=await t.call('validate',expectedRevision=fetched['observation']['revision'])
        print(json.dumps({'pin':t.ctx,'waiting':waiting,'proposed':proposed,'accepted':accepted,'fetched':fetched,'validated':validated}))
    finally:
        await t.asyncTearDown();t.tearDown();t.tearDownClass()
if __name__=='__main__':asyncio.run(main())
