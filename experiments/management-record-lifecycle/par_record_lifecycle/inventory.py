"""Validated metadata capture from the three live owner-managed ledgers.

No close/compact/retire/submit/reconcile method is invoked. Hash-only output is
not portable proof of data completeness: it is a diagnostic snapshot. Existing
signed source records remain authoritative. The live protocol has no common
replay generation, so all four migration gates are unconditionally false.
"""
from __future__ import annotations
from . import contracts as c


def collect_inventory(submissions, *, expected_pins=None, observer=None) -> dict:
    from par_management_jobs import contract as job
    from par_job_control import protocol as ctl
    from par_job_submit import protocol as stage
    from par_recovery.transfer import read_file
    try:
        s=submissions; h=s.host; jobs=s.jobs; control=s.ctl
        c.require(jobs is h.jobs and control.host is h and s.k is h.keeper and s.p is h.provider,'SOURCE_SCOPE')
        s.guard(); jobs.journal.guard(); control.journal.guard()
        if expected_pins is not None:
            c.keys(expected_pins, ('jobs','control','submissions'))
            jobs.verify_pin(expected_pins['jobs']); control.journal.verify_pin(expected_pins['control']);s.verify_pin(expected_pins['submissions'])

        def token():
            h._guard(); d=h.diagnostics(); a=d['activity']
            c.require(a['connections']==0 and a['reader_pins']==0 and d['selected_job'] is None and d['fault'] is None,'SOURCE_BUSY')
            # All participating roots are locked by the already-open owner. This
            # check is a consistency guard, not a cross-process transaction.
            for root in (jobs.journal.root,control.journal.root,s.root):
                c.require(not any(p.name.endswith('.tmp') for p in root.iterdir()),'UNACKNOWLEDGED_TEMP')
            values=[jobs.pin(),control.journal.pin(),s.pin(),list(control.policy()),list(jobs.backend.context()),
                    [d['mode'],d['selected_job'],a['connections'],a['reader_pins'],a['read_accepting'],a['upload_accepting']]]
            return c.sha(job.dump(values))

        before=token()
        if observer:observer('between_reads')
        anchors={};records=[]
        policy=control.journal.policy()
        policy_digest=c.sha(job.dump(policy))
        policy_key='policy:'+policy_digest
        anchors[policy_key]={'key':policy_key,'proof_digest':policy_digest}

        def new_record(kind,identifier,state,intent,input_digest,proof,refs,evidence=None,size=0,reserved=0):
            return {'key':kind+':'+identifier.hex(),'kind':kind,'local_id':identifier.hex(),
                    'state':state,'intent_digest':intent,'input_digest':input_digest,'proof_digest':proof,
                    'refs':sorted(set(refs+[policy_key])),'evidence_digest':evidence,
                    'storage_bytes':size,'reserved_bytes':reserved}

        job_ids=set()
        for b,archive,_ in jobs.journal.audit():
            jid=b[4];job_ids.add(jid)
            b,archive,raw=jobs.journal.read(jid)
            status=jobs.poll(jid)  # SUCCEEDED also requires authoritative effect proof.
            event=b[13][-1];refs=[];evidence=None
            if event[1]=='SUCCEEDED':
                c.require(status['result_verified'] is True,'SOURCE_REJECTED')
                evidence=event[3].hex();key='evidence:'+evidence
                anchor={'key':key,'proof_digest':c.sha(event[2])}
                c.require(key not in anchors or anchors[key]==anchor,'EVIDENCE_CONFLICT')
                anchors[key]=anchor;refs.append(key)
            records.append(new_record('job',jid,event[1],job.intent(b).hex(),job.intent(b).hex(),c.sha(raw),refs,evidence,len(raw)))

        for oid in sorted(control.journal.audit()):
            b,raw=control.journal.read(oid);_,intent=ctl.inspect_intent(s.p,b[4])
            c.require(intent.job_id in job_ids,'DANGLING_REFERENCE')
            records.append(new_record('control',oid,b[5],ctl.digest(b[4]).hex(),ctl.digest(b[4]).hex(),c.sha(raw),
                                      ['job:'+intent.job_id.hex()],size=len(raw)))

        for m,d in s.audit():
            jid=d[5];raw=s._source(jid);retired=s.retirement_path(jid).exists();ret_raw=b''
            state=m[7];evidence=m[9].hex() if m[9] is not None else None
            if retired:
                rb,_,_=s._record(jid);state=rb[8]
                ret_raw=read_file(s.retirement_path(jid),65536)
            else:
                s._view(m,d)  # Retain original registration-to-job matching checks.
            refs=[]
            if m[9] is not None or jid in job_ids:
                c.require(jid in job_ids,'DANGLING_REFERENCE')
                fact=s._lookup(m,d) if not retired else m[9]
                c.require(fact is not None,'DANGLING_REFERENCE')
                refs.append('job:'+jid.hex())
            payload_size=s.payload_path(jid).stat().st_size if s.payload_path(jid).exists() else 0
            proof=c.sha(b'PAR/lifecycle/stage\x00'+len(raw).to_bytes(8,'big')+raw+ret_raw)
            records.append(new_record('submission',jid,state,c.sha(m[4]),d[8].hex(),proof,refs,evidence,
                                      len(raw)+len(ret_raw)+payload_size,0 if state=='TOMBSTONED' else d[7]))

        after=token()
        c.require(before==after,'SOURCE_CHANGED')
        public,revision=control.policy()
        v={'schema':1,'profile':c.PROFILE,'source':'LIVE_READONLY','keeper':s.k.public.hex(),
           'store':h.gateway.store_id.hex(),'controller':public.hex() if public is not None else None,
           'controller_revision':revision,'observation':after,'gates':{k:False for k in c.GATES},
           'anchors':sorted(anchors.values(),key=lambda a:a['key']),
           'records':sorted(records,key=lambda r:r['key'])}
        return c.decode_inventory(c.encode_inventory(v))
    except c.LifecycleError:
        raise
    except Exception:
        # No paths, command bytes or private inputs in diagnostic errors.
        raise c.LifecycleError('SOURCE_REJECTED') from None
