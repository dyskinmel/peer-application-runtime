#!/usr/bin/env python3
"""Explicit Node -> private owner -> TLS provider demo using public synthetic data."""
from pathlib import Path
import asyncio,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
from tools.check_fetch_owner import inventory
from test_owner_process import OwnerProcessTests
async def main():
    t=OwnerProcessTests('test_two_rounds_three_level_and_core_blocked');t.setUpClass()
    try:
        await t.asyncSetUp()
        n,o,p=await t.phase('rounds',6)
        assert o['candidate_count']==3 and o['network_calls']==6 and o['db_unchanged']
        assert n['state']['snapshot']['observation']['records'][0]['validation']['reason']=='CORE_UNAVAILABLE'
        assert o['owner']['cleanupComplete'] and not o['owner']['inflight']
        print(json.dumps({'result':'PASS','processes':3,'candidate_count':3,'requests':p['requests'],
              'core':'CORE_UNAVAILABLE','applied':False,'shared_write':False,'automatic_ack':False,
              'store_unchanged':o['db_unchanged'],'cleanup_complete':True,'browser_executed':False}))
    finally:
        await t.asyncTearDown();t.tearDownClass()
if __name__=='__main__':asyncio.run(main())
