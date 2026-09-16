#!/usr/bin/env python3
"""2/8 isolated owner namespaces; bounded private IPC, NOT public P2P scale.

Python diagnostic client + one real owner process per namespace. Existing Node
soak is maintained separately; this driver does not claim a Node/browser test.
All owner endpoints are inherited AF_UNIX socketpairs, never public listeners.
"""
from __future__ import annotations
import argparse,asyncio,hashlib,json,math,os,shutil,socket,struct,sys,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
from tools import check_application_owner
from tools.run_provider_soak import message,send,binding
from product.wp13.par_matrix import FairConnectionPool
from product.wp13.par_matrix.factory import FactoryRefusal
from product.wp13.par_soak.metrics import sample_python,RSS_GROWTH_BUDGET
from product.wp10.transport import decode_frame
from harness.common import clean_env,atomic_json
ACTOR=ROOT/'tests/product/provider-soak/owner_actor.py'

async def frame_read(reader):
    n=struct.unpack('!I',await reader.readexactly(4))[0]
    if not 0<n<=131072:raise RuntimeError('MATRIX_FRAME_BUDGET')
    return decode_frame(await reader.readexactly(n))
async def frame_write(writer,obj):
    raw=json.dumps(obj,separators=(',',':'),allow_nan=False).encode()
    if not 0<len(raw)<=65536:raise RuntimeError('MATRIX_FRAME_BUDGET')
    writer.write(struct.pack('!I',len(raw))+raw);await writer.drain()

class Peer:
    def __init__(self,name,fixture,proc,ready,pairs):
        self.name=name;self.fixture=fixture;self.proc=proc;self.ready=ready
        self.sockets=[b for a,b in pairs];self.used=0;self.last=None;self.baseline=None
        self.entered=asyncio.Event();self.calls=[]
    async def connect(self,cancel,*,scenario='observe',identity='warmup'):
        if cancel.is_set():raise FactoryRefusal('CANCELLED')
        if self.used>=len(self.sockets):raise RuntimeError('MATRIX_FD_BUDGET')
        sock=self.sockets[self.used];self.used+=1;self.calls.append(identity)
        command={'cmd':'round','round':identity,'scenario':scenario}
        await send(self.proc,command);serving=await message(self.proc,'serving')
        if serving['round']!=identity:raise RuntimeError('MATRIX_CONTROL_ID')
        reader=writer=None
        try:
            reader,writer=await asyncio.open_connection(sock=sock,limit=131076)
            hello=await asyncio.wait_for(frame_read(reader),30)
            if hello.get('protocol')!='par-owner-application-0052' or hello.get('context')!=self.ready['context']:
                raise RuntimeError('MATRIX_CONTEXT')
            return OwnerConnection(self,reader,writer,hello['context'],scenario,identity)
        except BaseException:
            if writer is not None:
                writer.close();await writer.wait_closed()
            else:sock.close()
            raise

class OwnerConnection:
    def __init__(self,peer,reader,writer,context,scenario,identity):
        self.owner=peer;self.peer=peer.name;self.reader=reader;self.writer=writer
        self.context=context;self.scenario=scenario;self.identity=identity;self.closed=False
    async def perform(self,cancel):
        await frame_write(self.writer,{'v':1,'id':'1','op':'observe','args':{'context':self.context}})
        watcher=None
        try:
            if self.scenario=='cancel':
                row=await message(self.owner.proc,'entered')
                if row['round']!=self.identity:raise RuntimeError('MATRIX_BARRIER_ID')
                self.owner.entered.set()
                async def trigger():
                    await cancel.wait();await frame_write(self.writer,{'v':1,'cancel':'1'})
                watcher=asyncio.create_task(trigger())
            result=await asyncio.wait_for(frame_read(self.reader),30)
            if result.get('id')!='1' or result.get('op')!='observe':raise RuntimeError('MATRIX_RESPONSE_ID')
            if self.scenario=='cancel':
                if result.get('error')!='HOST_REQUEST_CANCELLED':raise RuntimeError('MATRIX_CANCEL_NOT_OBSERVED')
                return 'CANCELLED'
            if 'value'not in result:raise RuntimeError('MATRIX_OBSERVE_FAILED')
            if self.scenario=='reject':
                await frame_write(self.writer,{'v':1,'id':'2','op':'prepare','args':{'context':self.context}})
                denied=await asyncio.wait_for(frame_read(self.reader),30)
                if denied.get('id')!='2' or denied.get('error')!='OWNER_OPERATION_DENIED':raise RuntimeError('MATRIX_GRANT_BYPASSED')
                return 'AUTHORIZATION_DENIED'
            return 'OBSERVED'
        finally:
            if watcher:
                watcher.cancel();await asyncio.gather(watcher,return_exceptions=True)
    async def close(self):
        if self.closed:raise RuntimeError('MATRIX_DOUBLE_CLOSE')
        self.closed=True;self.writer.close();await self.writer.wait_closed()
        done=await message(self.owner.proc,'done')
        if done['round']!=self.identity:raise RuntimeError('MATRIX_CLOSE_ID')
        if not done['readonly_unchanged']or done['data_digest']!=done['initial_data_digest']:
            raise RuntimeError('MATRIX_PERSISTENT_STATE_CHANGED')
        self.owner.last=done

async def operation(connection,cancel):return await connection.perform(cancel)

def growth(label,base,current):
    errors=[]
    for key in ('pid','raw_fd','reserved_fd','fd','tasks','rss_bytes'):
        if any(type(r.get(key))is not int or r[key]<0 for r in(base,current)):raise RuntimeError('MATRIX_METRIC_SCHEMA')
    if base['pid']!=current['pid']:raise RuntimeError('MATRIX_PID_CHANGED')
    if current['raw_fd']-current['reserved_fd']!=current['fd']:raise RuntimeError('MATRIX_FD_ACCOUNTING')
    if current['fd']>base['fd']:errors.append(label+'_FD_GROWTH')
    if current['tasks']>base['tasks']:errors.append(label+'_TASK_GROWTH')
    if current['rss_bytes']-base['rss_bytes']>RSS_GROWTH_BUDGET:errors.append(label+'_RSS_BUDGET')
    return errors

def distribution(values):
    data=sorted(v for v in values if v is not None)
    if not data:return {'count':0}
    return {'count':len(data),'min_us':data[0],'p50_us':data[math.ceil(len(data)*.5)-1],
            'p95_us':data[math.ceil(len(data)*.95)-1],'max_us':data[-1]}

async def run_cell(participants,max_active,*,rounds_per_peer=3,inject=None):
    if participants not in (2,8) or type(participants)is not int or type(max_active)is not int or not 1<=max_active<=participants:
        raise ValueError('MATRIX_CONFIG')
    if type(rounds_per_peer)is not int or not 1<=rounds_per_peer<=4 or inject not in(None,'fd','task'):raise ValueError('MATRIX_CONFIG')
    if not sys.platform.startswith('linux') or not Path('/proc/self/status').is_file():raise RuntimeError('LINUX_PROC_REQUIRED')
    from test_application_process import ApplicationProcessTests
    peers=[];fixtures=[];children=[];pairs=[];pool=None;leakfd=None;leaktask=None
    begin=time.monotonic_ns();rows=[];violations=[];child_exits=[];segment=uuid.uuid4().hex
    try:
        for i in range(participants):
            fixture=ApplicationProcessTests();fixtures.append(fixture);await fixture.asyncSetUp()
            pp=[socket.socketpair()for _ in range(rounds_per_peer+1)];pairs+=pp
            fds=[a.fileno()for a,b in pp]
            proc=await asyncio.create_subprocess_exec(sys.executable,'-I','-S','-B',str(ACTOR),str(fixture.path),json.dumps(fds),pass_fds=fds,
                stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,env=clean_env());children.append(proc)
            ready=await message(proc,'ready')
            if ready['pgid']!=os.getpgrp():raise RuntimeError('PROCESS_GROUP_CHANGED')
            for a,b in pp:a.close()
            peers.append(Peer('peer'+str(i),fixture,proc,ready,pp))
        for peer in peers:
            conn=await peer.connect(asyncio.Event());await conn.perform(asyncio.Event());await conn.close();peer.baseline=peer.last
        reserved=lambda:[s.fileno()for p in peers for s in p.sockets[p.used:]]
        baseline=sample_python(reserved())
        pool=FairConnectionPool(tuple(p.name for p in peers),max_active=max_active,max_queued=participants*(rounds_per_peer+1),per_peer=8)
        slow=peers[0]
        async def slow_factory(peer,cancel):return await slow.connect(cancel,scenario='cancel',identity='slow')
        h=pool.submit(slow.name,'slow',slow_factory,operation,timeout=60)
        await asyncio.wait_for(slow.entered.wait(),30)
        handles=[h];others=[]
        # Deliberately enqueue in per-peer bursts, not already fair global order.
        for i,p in enumerate(peers):
            for j in range(1 if i==0 else 0,rounds_per_peer):
                identity=f'{i}:{j}';scenario='reject'if j%2 else'observe'
                async def factory(peer,cancel,p=p,identity=identity,scenario=scenario):
                    return await p.connect(cancel,scenario=scenario,identity=identity)
                job=pool.submit(p.name,identity,factory,operation,timeout=60);handles.append(job)
                if i!=0:others.append(job)
        # Fill remaining queue across participants: no socket is allocated
        # by these probes. Cancel them while queued, before releasing slow peer.
        pressure=[];rejections=0
        while pool.status()['queued']<pool.max_queued:
            q=pool.submit(peers[len(pressure)%participants].name,'pressure:'+str(len(pressure)),slow_factory,operation,timeout=60);pressure.append(q)
        try:pool.submit(slow.name,'overflow',slow_factory,operation)
        except ValueError as exc:
            if str(exc)!='QUEUE_FULL':raise
            rejections+=1
        else:raise RuntimeError('MATRIX_QUEUE_NOT_BOUNDED')
        for q in pressure:q.cancel()
        for q in pressure:
            if (await q.wait()).code!='CANCELLED_BEFORE_START':raise RuntimeError('MATRIX_PRESSURE_STARTED')
        progressed=False
        if max_active>1:
            # Completion itself, while slow remains running, is the progress proof;
            # 30s here is a diagnostic watchdog, not a product latency SLO.
            result=await asyncio.wait_for(others[0].wait(),30)
            if result.code!='OK' or h.done:raise RuntimeError('MATRIX_OTHER_PROGRESS')
            progressed=True
        control_start=time.monotonic_ns();state=pool.status();cancel_accepted=h.cancel();control_us=(time.monotonic_ns()-control_start)//1000
        control_progress=cancel_accepted and h.done
        if not control_progress:raise RuntimeError('MATRIX_CONTROL_NOT_COMPLETED')
        results=await asyncio.wait_for(asyncio.gather(*(q.wait()for q in handles)),60)
        if results[0].code!='CANCELLED_AFTER_START' or any(r.code!='OK'for r in results[1:]):
            raise RuntimeError('MATRIX_RESULTS:'+','.join(r.code for r in results))
        cleanup=await pool.close(timeout=10)
        if not cleanup:violations.append('MATRIX_CLEANUP_UNCONFIRMED')
        await asyncio.sleep(0);await asyncio.sleep(0)
        if inject=='fd':leakfd=os.open('/dev/null',os.O_RDONLY)
        if inject=='task':leaktask=asyncio.create_task(asyncio.Event().wait())
        final=sample_python(reserved());violations+=growth('DRIVER',baseline,final)
        for p in peers:
            violations+=growth(p.name.upper(),p.baseline['python'],p.last['python'])
            if p.last['python']['channels']or p.last['python']['inflight']:violations.append(p.name+'_PENDING')
        observations=pool.observations()
        for p in peers:await send(p.proc,{'cmd':'exit'})
        for p in peers:
            out,err=await asyncio.wait_for(p.proc.communicate(),15);child_exits.append(p.proc.returncode)
            if p.proc.returncode!=0 or err or out:violations.append(p.name+'_FINALIZATION')
        return {'profile':'par-resource-matrix-0055','status':'FAIL'if violations else'PASS','violations':violations,
                'participants':participants,'max_active':max_active,'rounds_per_peer':rounds_per_peer,
                'completed_jobs':len(handles),'peak_active':pool.status()['peak_active'],'peak_queued':pool.status()['peak_queued'],
                'queue_limit':pool.max_queued,'queue_full_rejections':rejections,'control_bypasses_queue':control_progress,'control_us':control_us,
                'other_progress_before_slow_cancel':progressed,'all_slots_occupied_at_control':state['active']==max_active,
                'final_pool':pool.status(),'driver_pid':os.getpid(),'owner_pids':[p.proc.pid for p in peers],
                'child_exit_codes':child_exits,'segment':segment,'driver_baseline':baseline,'driver_final':final,
                'peers':[{'peer':p.name,'baseline':p.baseline['python'],'final':p.last['python'],
                          'initial_data_digest':p.last['initial_data_digest'],'data_digest':p.last['data_digest'],
                          'factory_calls':p.calls,'readonly_unchanged':p.last['readonly_unchanged']}for p in peers],
                'readonly_unchanged':all(p.last['readonly_unchanged']for p in peers),
                'observations':observations,'queue_latency':distribution(x['queue_us']for x in observations),
                'lifetime_latency':distribution(x['lifetime_us']for x in observations),
                'elapsed_us':(time.monotonic_ns()-begin)//1000,'node_executed':False,'real_core_executed':False,
                'public_network_executed':False,'product_qualified':False}
    finally:
        if leakfd is not None:os.close(leakfd)
        if leaktask:leaktask.cancel();await asyncio.gather(leaktask,return_exceptions=True)
        if pool:await pool.close(timeout=2)
        for a,b in pairs:a.close();b.close()
        for p in children:
            if p.returncode is None:p.kill()
            await p.communicate()
        for f in fixtures:
            await f.asyncTearDown()
            if hasattr(f,'f'):f.f.doCleanups()

DEFAULT_CELLS=[{'participants':2,'max_active':1,'rounds_per_peer':3},
               {'participants':2,'max_active':2,'rounds_per_peer':3},
               {'participants':8,'max_active':2,'rounds_per_peer':3},
               {'participants':8,'max_active':4,'rounds_per_peer':3}]

async def run_campaign(output,*,cells=None,seed=5500,resume=False,stop_after=None):
    from product.wp13.par_matrix.campaign import MatrixCampaign
    cells=DEFAULT_CELLS if cells is None else cells
    config={'cells':cells,'seed':seed};bound,env=binding();root=Path(output)
    if stop_after is not None and(type(stop_after)is not int or not 1<=stop_after<=len(cells)):raise ValueError('STOP_AFTER')
    c=MatrixCampaign.open(root,bound,config)if resume else MatrixCampaign.create(root,bound,config)
    try:
        state=c.state()
        if state['result']=='PARTIAL':
            begin=state['next_round'];end=min(len(cells),begin+stop_after)if stop_after else len(cells);exits=[]
            try:
                for index in range(begin,end):
                    c.begin(index);cell=cells[index]
                    r=await run_cell(cell['participants'],cell['max_active'],rounds_per_peer=cell['rounds_per_peer'])
                    r['round']=index;c.finish(index,r)
                    if r['status']!='PASS':break
                    exits.append(r['child_exit_codes'])
                if c.state()['result']!='FAIL':c.seal(exits)
            except Exception as exc:c.abort('MATRIX_DRIVER_FAILED:'+type(exc).__name__+':'+str(exc)[:2000])
        report={**c.state(),'profile':'par-resource-matrix-0055','binding':bound,'environment':env,
                'config':config,'pin':c.pin(),'cells':[e['payload']for e in c.records()if e['kind']=='RESULT'],
                'product_qualified':False,'seven_day_soak_qualified':False,'native_executed':False,
                'independent_review':'NOT_RUN','resume_unit':'SEALED_CELL_BOUNDARY'}
        atomic_json(root.parent/(root.name+'-summary.json'),report);return report
    finally:c.close()

async def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--participants',type=int,choices=(2,8));p.add_argument('--active',type=int,default=2)
    p.add_argument('--rounds-per-peer',type=int,default=3);p.add_argument('--resume',action='store_true');p.add_argument('--stop-after',type=int)
    a=p.parse_args();cells=None if a.participants is None else [{'participants':a.participants,'max_active':a.active,'rounds_per_peer':a.rounds_per_peer}]
    if not sys.platform.startswith('linux')or not Path('/proc/self/status').is_file():
        print(json.dumps({'result':'BLOCKED','executed_cells':0,'reason':'LINUX_PROC_REQUIRED'}));return 78
    r=await run_campaign(a.output,cells=cells,resume=a.resume,stop_after=a.stop_after)
    print(json.dumps(r,indent=2));return 0 if r['result']=='PASS'else 2 if r['result']=='PARTIAL'else 1
if __name__=='__main__':raise SystemExit(asyncio.run(main()))
