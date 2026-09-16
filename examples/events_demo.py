#!/usr/bin/env python3
"""Disposable public fixture: durable replay differs from coalescing snapshot and presence."""
import json,sys
from pathlib import Path
R=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True
for p in [R,R/'tests/product/wp10',R/'tests/product/auth-store',R/'tests/product/space-auth']+[p for p in (R/'experiments').iterdir() if p.is_dir()]:sys.path.insert(0,str(p))
from test_events import EventTest
from product.wp10.subscriptions import LatestSnapshot,PresenceHints

def main():
 t=EventTest();t.setUp()
 try:
  j=t.create();a=t.emit(1);t.emit(2,(a.event_id,));s=j.subscribe(b'd'*16);first=s.poll(limit=1)
  t.reopen();s=t.journal.subscribe(b'd'*16);again=s.poll(limit=1)
  assert first.events==again.events
  s.ack(again.token);second=s.poll();s.ack(second.token)
  cursor=s.cursor();t.reopen();s=t.journal.subscribe(b'd'*16,expected_cursor=cursor)
  assert not s.poll().events
  snapshots=[];latest=LatestSnapshot(1,b'old',snapshots.append);latest.publish(2,b'latest');latest.dispatch();latest.close()
  clock=[1];p=PresenceHints(clock=lambda:clock[0]);p.activate(b'p'*32,b's'*16);p.update(b'p'*32,b's'*16,1,b'editing',ttl_ns=10);clock[0]=11
  print(json.dumps({'result':'PASS','scope':'LOCAL_SYNTHETIC_CREDENTIALS_REAL_CRYPTO_AND_SQLITE','redelivered_before_ack':True,'acknowledged_position':s.position,'snapshots_delivered':[x.revision for x in snapshots],'presence_after_expiry':p.get(b'p'*32).state,'remote_delivery':False,'crdt_test_executed':False,'product_qualified':False},indent=2))
 finally:t.doCleanups()
if __name__=='__main__':main()
