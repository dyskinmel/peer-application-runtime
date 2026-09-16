"""Public synthetic materializer; real disk checkpoint adapter and transaction."""
from process_support import open_runtime
from product.wp09.par_application_intent import IntentJournal,LocalPinStore,AnchoredApplication

def open_anchored_runtime(config):
    f=open_runtime(config)
    try:
        f.j.close();binding=AnchoredApplication.binding(f.c)
        f.anchor=LocalPinStore.open(f.root.parent/'anchor',binding);f.addCleanup(f.anchor.close)
        f.j=IntentJournal.open_anchored(f.root.parent/'intents',binding,f.anchor);f.addCleanup(f.j.close)
        f.d=AnchoredApplication(f.j,f.c);return f
    except BaseException:f.doCleanups();raise
