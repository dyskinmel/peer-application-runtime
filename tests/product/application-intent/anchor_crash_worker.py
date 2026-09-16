"""Kill only this child, at a declared real pin/SQLite boundary."""
import json,os,signal,sys
from pathlib import Path
R=Path(__file__).resolve().parents[3];sys.dont_write_bytecode=True;sys.path[:0]=[str(R),str(R/'tools')]
import check_application_intent
from anchored_process_support import open_anchored_runtime
f=open_anchored_runtime(json.loads(Path(sys.argv[1]).read_text()));mode=sys.argv[2]
try:
    f.port.identity['kind']='automerge' # SYNTHETIC CONTRACT, NOT an actual CRDT.
    def kill():
        print(json.dumps({'killed_at':mode,'pgid':os.getpgrp(),'synthetic_core':True}),flush=True)
        os.kill(os.getpid(),signal.SIGKILL)
    advance=f.anchor.advance
    def advancing(old,new):
        if new.sequence==2 and mode=='before-dispatch-pin':kill()
        advance(old,new)
        if (new.sequence,mode)in((1,'after-prepare-pin'),(2,'after-dispatch-pin'),(4,'after-retire-pin')):kill()
    f.anchor.advance=advancing
    replace=os.replace
    def replacing(src,dst):
        if mode=='partial-dispatch-pin' and Path(dst)==f.anchor.root/'pin.json' and f.j.pin().sequence==2:kill()
        return replace(src,dst)
    os.replace=replacing
    def application(stage):
        if mode=='commit-response-loss' and stage=='apply.after_commit':kill()
    f.app.observer=application
    f.d.prepare(b'o'*16,expected_revision=0,expected_observation=f.c.observe()['revision'])
    value=f.d.execute(f.j.current.digest,expected_observation=f.c.observe()['revision'])
    if value['state']!='OBSERVED':raise RuntimeError(str(value))
    f.d.retire(f.j.current.digest)
    if mode!='complete':raise RuntimeError('boundary not hit')
    print(json.dumps({'state':f.j.status()['state'],'anchor_matches':f.anchor.load()==f.j.pin(),
                     'counts':f.nums(),'synthetic_core':True,'real_core_executed':False}),flush=True)
finally:f.doCleanups()
