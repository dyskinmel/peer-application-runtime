"""Disposable public synthetic fixtures; real files, locks and SQLite, NOT CRDT."""
from pathlib import Path
from apply_support import ApplyTest,h
from product.wp04.inbox import SyncInbox
from product.wp04.exchange import Source
from product.wp09.par_secure_fetch import FetchPlan
from product.runtime_read.fetch import FetchApplicationController
from product.wp09.par_application_intent import IntentJournal,JournalPin,DurableApplication

def open_runtime(config):
    f=ApplyTest();f.setUp();f.close()
    try:
        f.root=Path(config['database']);f.db=f.Store.open(f.root,provider=f.p,allow_unpatched_sqlite=True)
        f.db.reactivate(f.s.space,f.s.devices[0]['secret'])
        f.box=SyncInbox.open(f.root.parent/'inbox',f.db,app_id=f.s.app,space_id=f.s.space,
            document_id=h('doc'),epoch=1,schema_id=h('schema'));f.addCleanup(f.box.close)
        f.source=Source(f.box,f.s.devices[0]['cert'],f.s.devices[0]['seed'])
        f.plan=FetchPlan.from_bytes(bytes.fromhex(config['plan']))
        f.target=bytes.fromhex(config['target'])
        f.app=f.make(inbox=f.box,allow_contract_double=False)
        f.c=FetchApplicationController(f.plan,f.source,[f.target],lambda:9,application=f.app)
        f.j=IntentJournal.open(f.root.parent/'intents',DurableApplication.binding(f.c),
                              expected_pin=JournalPin(**config['pin']));f.addCleanup(f.j.close)
        f.d=DurableApplication(f.j,f.c)
        return f
    except BaseException:
        f.doCleanups();raise
