"""Self-SIGKILL at an actual persistence boundary; no external process signalled."""
import json,os,signal,sys
from pathlib import Path
R=Path(__file__).resolve().parents[3];sys.dont_write_bytecode=True
for p in [R,R/'tools']:sys.path.insert(0,str(p))
# The checker owns the pinned local test bootstrap; it does not execute on import.
import check_application_intent
from process_support import open_runtime
config=json.loads(Path(sys.argv[1]).read_text());mode=sys.argv[2];f=open_runtime(config)
try:
    f.port.identity['kind']='automerge' # Deliberately SYNTHETIC transaction fixture.
    def kill(label):
        print('KILL_BOUNDARY:'+label,flush=True);os.kill(os.getpid(),signal.SIGKILL)
    targets={
        'prepare-created':(1,'journal.after_create'),
        'prepare-synced':(1,'journal.after_dirsync'),
        'dispatch-synced':(2,'journal.after_dirsync'),
        'observe-written':(3,'journal.after_write'),
        'observe-synced':(3,'journal.after_dirsync'),
        'retire-synced':(4,'journal.after_dirsync')}
    def journal(stage):
        target=targets.get(mode)
        if target and stage==target[1] and len(list((f.j.root/'events').iterdir()))==target[0]:kill(mode)
    def application(stage):
        if mode==stage:kill(mode)
    f.j.observer=journal;f.app.observer=application
    f.d.prepare(b'o'*16,expected_revision=0,expected_observation=f.c.observe()['revision'])
    result=f.d.execute(f.j.current.digest,expected_observation=f.c.observe()['revision'])
    if result['state']!='OBSERVED':raise RuntimeError(str(result))
    f.d.retire(f.j.current.digest)
    if mode!='complete':raise RuntimeError('requested boundary not reached: '+mode)
    print(json.dumps({'journal':f.j.status(),'counts':f.nums(),'synthetic_core':True,
                     'real_automerge_executed':False}),flush=True)
finally:f.doCleanups()
