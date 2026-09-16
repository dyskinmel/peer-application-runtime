#!/usr/bin/env python3
"""Run bounded persistent-process read-only experiments, never production retry.

Requires Linux /proc, Node and existing synthetic-fixture dependencies. All peer
sockets are preconnected AF_UNIX pairs; there are no listening/network endpoints.
A boundary stop can resume; a failed or unfinished round cannot be retried here.
"""
from __future__ import annotations
import argparse,asyncio,hashlib,json,os,platform,shutil,socket,sys,time,uuid,sqlite3,ssl
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
from product.wp13.par_soak import Campaign,SCENARIOS,compare_resources
from harness.common import clean_env,atomic_json
from harness.snapshot import snapshot
ACTORS=ROOT/'tests/product/provider-soak'

def binding():
    node=shutil.which('node')
    if not node or not Path('/proc/self/status').is_file():raise RuntimeError('LINUX_NODE_PROVIDER_UNAVAILABLE')
    env={'python_path':sys.executable,'python_sha256':hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
         'python_version':platform.python_version(),'node_path':node,
         'node_sha256':hashlib.sha256(Path(node).read_bytes()).hexdigest(),
         'system':platform.system(),'machine':platform.machine(),'kernel':platform.release(),
         'cpu_model':next((x.split(':',1)[1].strip()for x in Path('/proc/cpuinfo').read_text().splitlines()if x.startswith('model name')),'UNAVAILABLE'),
         'logical_cpus':os.cpu_count(),'affinity_cpus':len(os.sched_getaffinity(0)),
         'memory_total_bytes':int(next(x.split()[1]for x in Path('/proc/meminfo').read_text().splitlines()if x.startswith('MemTotal:')))*1024,
         'node_version':__import__('subprocess').check_output([node,'--version'],text=True,timeout=10).strip(),
         'sqlite_version':sqlite3.sqlite_version,'openssl_version':ssl.OPENSSL_VERSION}
    # Host-visible CPU/memory are not container quotas or a certified hardware class.
    return {'source':snapshot(ROOT)['digest'],'environment':hashlib.sha256(json.dumps(env,sort_keys=True).encode()).hexdigest()},env

async def message(p,kind,timeout=30):
    line=await asyncio.wait_for(p.stdout.readline(),timeout)
    if not line:
        _,err=await asyncio.wait_for(p.communicate(),3)
        raise RuntimeError(f'{kind}: child exit {p.returncode}: '+err.decode(errors='replace')[:3000])
    value=json.loads(line)
    if value.get('kind')!=kind:raise RuntimeError(f'{kind}: unexpected {value!r}')
    return value

async def send(p,obj):
    p.stdin.write((json.dumps(obj)+'\n').encode());await p.stdin.drain()

async def run_segment(entries,on_begin,on_result,*,inject_fd_leak=None,inject_task_leak=None):
    from tools import check_application_owner # Existing exact fixture bootstrap.
    from test_application_process import ApplicationProcessTests
    fixture=ApplicationProcessTests()
    children=[];sockets=[];segment=uuid.uuid4().hex;segment_start=time.monotonic_ns();started_unix_ns=time.time_ns()
    try:
        await fixture.asyncSetUp()
        schedule=[(-i-1,s)for i,s in enumerate(SCENARIOS)]+entries
        for _ in schedule:sockets.append(socket.socketpair())
        server_fds=[a.fileno()for a,b in sockets];client_fds=[b.fileno()for a,b in sockets]
        env=clean_env()
        owner=await asyncio.create_subprocess_exec(sys.executable,'-I','-S','-B',str(ACTORS/'owner_actor.py'),str(fixture.path),json.dumps(server_fds),pass_fds=server_fds,stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,env=env);children.append(owner)
        ready=await message(owner,'ready')
        if ready['pgid']!=os.getpgrp():raise RuntimeError('PROCESS_GROUP_CHANGED')
        node=await asyncio.create_subprocess_exec(shutil.which('node'),str(ACTORS/'node_actor.mjs'),json.dumps(ready['context']),json.dumps(ready['targets']),str(fixture.caller),json.dumps(client_fds),pass_fds=client_fds,stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,env=env);children.append(node)
        await message(node,'ready')
        for a,b in sockets:a.close();b.close()
        base_py=base_node=None;warmup=[]
        for index,scenario in schedule:
            if index>=0:on_begin(index)
            command={'cmd':'round','round':index,'scenario':scenario}
            try:
                await send(owner,{**command,'leak_fd':index>=0 and index==inject_fd_leak,'leak_task':index>=0 and index==inject_task_leak})
                await message(owner,'serving')
                await send(node,command)
                if scenario in ('cancel','timeout','disconnect'):
                    await message(node,'started');entered=await message(owner,'entered')
                    if entered['round']!=index:raise RuntimeError('GATE_IDENTITY_MISMATCH')
                    await send(node,{'cmd':'trigger','round':index})
                nr=await message(node,'done');pr=await message(owner,'done')
                if nr['round']!=index or pr['round']!=index:raise RuntimeError('RESULT_IDENTITY_MISMATCH')
                py={**pr['python'],'segment':segment};nd={**nr['node'],'segment':segment}
                if index<0:
                    if not pr['readonly_unchanged']or not nr['readonly_unchanged']:raise RuntimeError('WARMUP_MUTATED_STORE')
                    if py['channels']or py['inflight']or nd['inflight']or nd['pendingRequests']or nd['pendingStore']:raise RuntimeError('WARMUP_PENDING')
                    warmup.append({'scenario':scenario,'python':py,'node':nd});base_py,base_node=py,nd
                    continue
                violations=compare_resources(base_py,base_node,py,nd)
                if not pr['readonly_unchanged']or not nr['readonly_unchanged']:violations.append('PERSISTENT_STATE_CHANGED')
                if nr['close_us']>2_000_000:violations.append('CLOSE_DIAGNOSTIC_BUDGET')
                record={'round':index,'scenario':scenario,'status':'FAIL'if violations else'PASS','violations':violations,
                        'segment':segment,'baseline_python':base_py,'baseline_node':base_node,'python':py,'node':nd,
                        'readonly_unchanged':pr['readonly_unchanged']and nr['readonly_unchanged'],
                        'close_us':nr['close_us'],'duration_us':nr['duration_us'],'operation_error':nr['code'],
                        'lifecycle':nr['lifecycle'],'timeout_mode':nr['timeout_mode'],
                        'warmup_rounds':len(warmup),'real_core_executed':False,
                        'started_unix_ns':started_unix_ns,'elapsed_us':(time.monotonic_ns()-segment_start)//1000,
                        'initial_data_digest':pr['initial_data_digest'],'data_digest':pr['data_digest']}
                on_result(index,record)
                if violations:break
            except Exception as exc:
                if index>=0:
                    on_result(index,{'round':index,'scenario':scenario,'status':'FAIL','reason':'DRIVER_FAILURE','detail':str(exc)[:3500],'segment':segment})
                    break
                raise
        for p in (node,owner):await send(p,{'cmd':'exit'})
        for p in (node,owner):
            out,err=await asyncio.wait_for(p.communicate(),10)
            if p.returncode!=0 or err:raise RuntimeError(f'ACTOR_FINALIZATION: {p.returncode} '+err.decode(errors='replace')[:3500])
    finally:
        for a,b in sockets:a.close();b.close()
        for p in children:
            if p.returncode is None:p.kill()
            await p.communicate()
        await fixture.asyncTearDown()
        if hasattr(fixture,'f'):fixture.f.doCleanups() # Plain TestCase; no uninitialised IsolatedAsyncio runner.

def summarize(c,env):
    result=c.state();rows=[e['payload']for e in c.records()if e['kind']=='RESULT'];segments={};scenario_counts={}
    for r in rows:
        scenario_counts[r['scenario']]=scenario_counts.get(r['scenario'],0)+1
        sid=r.get('segment');s=segments.setdefault(sid,{'id':sid,'rounds':0});s['rounds']+=1
        if 'python'in r:
            s.update(python_pid=r['python']['pid'],node_pid=r['node']['pid'],baseline_python=r['baseline_python'],baseline_node=r['baseline_node'],final_python=r['python'],final_node=r['node'],elapsed_us=r['elapsed_us'],started_unix_ns=r['started_unix_ns'])
    result.update(pin=c.pin(),segments=list(segments.values()),scenarios=scenario_counts,round_ids=[r['round']for r in rows],
                  persistent_data_unchanged=bool(rows)and all(r.get('readonly_unchanged',False)for r in rows),
                  persistent_data_digests_verified=bool(rows)and all(r.get('data_digest')and r['data_digest']==r.get('initial_data_digest')for r in rows),
                  environment=env,scope='LOCAL_PERSISTENT_PROCESSES_NOT_7DAY_OR_NATIVE_QUALIFICATION',
                  product_qualified=False,independent_review='NOT_RUN',rss_is_diagnostic=True)
    return result

async def run_campaign(root,*,rounds=140,seed=5400,resume=False,stop_after=None,inject_fd_leak=None,inject_task_leak=None):
    root=Path(root);root.parent.mkdir(parents=True,exist_ok=True)
    if stop_after is not None and(type(stop_after)is not int or not 1<=stop_after<=rounds):raise ValueError('INVALID_STOP_AFTER')
    bound,env=binding();config={'rounds':rounds,'seed':seed}
    c=Campaign.open(root,bound,config)if resume else Campaign.create(root,bound,config)
    try:
        state=c.state()
        if state['result']not in('PASS','FAIL','INTERRUPTED','UNSEALED'):
            start=state['next_round'];end=min(rounds,start+stop_after)if stop_after else rounds
            try:
                await run_segment([(i,c.scenario(i))for i in range(start,end)],c.begin,c.finish,inject_fd_leak=inject_fd_leak,inject_task_leak=inject_task_leak)
                if c.state()['result']!='FAIL':c.seal()
            except Exception as exc:c.abort('ACTOR_FINALIZATION_OR_WARMUP: '+str(exc)[:3500])
        r=summarize(c,env);atomic_json(root.parent/(root.name+'-summary.json'),r);return r
    finally:c.close()

async def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--output',type=Path,required=True);ap.add_argument('--rounds',type=int,default=140);ap.add_argument('--seed',type=int,default=5400);ap.add_argument('--resume',action='store_true');ap.add_argument('--stop-after',type=int);args=ap.parse_args()
    try:r=await run_campaign(args.output,rounds=args.rounds,seed=args.seed,resume=args.resume,stop_after=args.stop_after)
    except RuntimeError as exc:
        if str(exc)=='LINUX_NODE_PROVIDER_UNAVAILABLE':print(json.dumps({'result':'BLOCKED','executed_rounds':0,'reason':str(exc)}));return 78
        raise
    print(json.dumps(r,indent=2));return 0 if r['result']=='PASS'else 2 if r['result']=='PARTIAL'else 1
if __name__=='__main__':raise SystemExit(asyncio.run(main()))
