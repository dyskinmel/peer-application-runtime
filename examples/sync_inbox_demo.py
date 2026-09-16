#!/usr/bin/env python3
"""Actual signed/encrypted pending bytes; opaque test input, NOT an Automerge demo."""
from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True
for p in [ROOT,ROOT/'tests/product/sync-inbox',ROOT/'tests/product/shared-document',ROOT/'tests/product/auth-store',ROOT/'tests/product/space-auth']+[p for p in (ROOT/'experiments').iterdir() if p.is_dir()]:sys.path.insert(0,str(p))
from inbox_support import InboxTest

def main():
 t=InboxTest();t.setUp()
 try:
  t.create();a=t.change('parent');b=t.change('child',parents=[t.cid(a[0])],previous=t.eid(a[0]),seq=2)
  received=t.receive(b);waiting=t.box.inspect(t.eid(b[0]));pin=t.box.pin();t.reopen_box(expected_pin=pin)
  missing=t.box.needed();t.receive(a);t.receive(b);ready=t.box.inspect(t.eid(b[0]));blocked=t.box.validate(t.eid(b[0]),None)
  result={'scope':'ACTUAL_CRYPTO_PENDING_BYTES_OPAQUE_TEST_INPUT','receipt':received,'beforeParent':waiting,'afterRestartNeeded':missing,'afterParent':ready,'withoutCore':blocked,'applicationEnvelopes':t.count('envelopes'),'inboxUsage':t.box.usage()}
  assert waiting['state']=='WAITING_DEPENDENCIES' and ready['state']=='READY_FOR_CORE' and blocked['state']=='CORE_BLOCKED' and result['applicationEnvelopes']==0
  print(json.dumps(result,ensure_ascii=False,indent=2))
 finally:t.doCleanups()
if __name__=='__main__':main()
