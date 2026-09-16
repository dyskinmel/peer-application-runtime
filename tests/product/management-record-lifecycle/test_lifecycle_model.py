import copy,json
from lifecycle_support import ModelTest,fixture,record,hx

class GenerationTests(ModelTest):
    def test_closed_before_archive(self):
        m=self.model();self.err('PHASE',m.archive)
    def test_archive_before_compact(self):
        m=self.closed();self.err('PHASE',m.compact)
    def test_compact_before_new_generation(self):
        m=self.archived();self.err('PHASE',lambda:m.open_next(controller_revision=1))
    def test_archived_job_keeps_actual_state(self):
        m=self.compacted();j=record(refs=['evidence:'+hx('effect-one')]);r=m.resolve(j['key']);self.assertEqual(r['state'],'SUCCEEDED')
        self.assertEqual(m.view()['active_records'],0);self.assertEqual(m.view()['archived_records'],3)
    def test_reference_resolves_after_logical_compaction(self):
        m=self.compacted();s=record('submission',refs=['job:'+hx('one')]);r=m.resolve(s['key']);self.assertEqual(m.resolve(r['refs'][0])['input_digest'],hx('job-input-one'))
    def test_old_request_rejected_at_closed(self):
        m=self.closed();self.err('GENERATION_CLOSED',lambda:m.admit(record('job','new','CANCELLED'),generation=1,controller_revision=1))
    def test_old_request_rejected_after_reopen(self):
        m=self.compacted();m.open_next(controller_revision=1);self.err('GENERATION_CLOSED',lambda:m.admit(record('job','new','CANCELLED'),generation=1,controller_revision=1))
    def test_new_generation_does_not_resurrect_old_id(self):
        m=self.compacted();m.open_next(controller_revision=1)
        self.err('ID_REUSE',lambda:m.admit(record(),generation=2,controller_revision=1))
    def test_alias_new_id_still_rejected(self):
        m=self.compacted();m.open_next(controller_revision=1);r=record('job','alias','CANCELLED');r['intent_digest']=hx('job-intent-one')
        self.err('INTENT_ALIAS',lambda:m.admit(r,generation=2,controller_revision=1))
    def test_legitimate_new_record(self):
        m=self.compacted();m.open_next(controller_revision=1);r=record('job','new','CANCELLED');m.admit(r,generation=2,controller_revision=1)
        self.assertEqual(m.resolve(r['key']),r);self.assertEqual(m.view()['active_records'],1)
    def test_stale_plan_after_new_record(self):
        m=self.model();p=m.plan();m.admit(record('job','new','CANCELLED'),generation=1,controller_revision=1)
        self.err('STALE_PLAN',lambda:m.close(p,controller_revision=1))
    def test_stale_plan_after_rotation(self):
        m=self.model();p=m.plan();m.rotate(hx('new-controller'),2)
        self.err('STALE_PLAN',lambda:m.close(p,controller_revision=2))
    def test_old_controller_rejected(self):
        m=self.model();m.rotate(hx('new-controller'),2);self.err('STALE_CONTROLLER',lambda:m.close(m.plan(),controller_revision=1))
    def test_controller_revision_strictly_increases(self):
        m=self.model();self.err('STALE_CONTROLLER',lambda:m.rotate(hx('new-controller'),1))
    def test_rotation_not_in_middle_of_committed_migration(self):
        m=self.closed();self.err('PHASE',lambda:m.rotate(hx('new-controller'),2))
    def test_inflight_job_blocks_closure(self):
        v=fixture();j=next(r for r in v['records'] if r['kind']=='job');j.update(state='EXECUTING',evidence_digest=None)
        m=self.api.LifecycleModel(v);self.err('BLOCKED',lambda:m.close(m.plan(),controller_revision=1))
    def test_stage_intent_blocks_closure(self):
        v=fixture();next(r for r in v['records'] if r['kind']=='submission')['state']='INTENT'
        m=self.api.LifecycleModel(v);self.err('BLOCKED',lambda:m.close(m.plan(),controller_revision=1))
    def test_live_snapshot_cannot_enter_model(self):
        v=fixture();v['source']='LIVE_READONLY';v['gates']={k:False for k in v['gates']}
        self.err('MODEL_ONLY',lambda:self.api.LifecycleModel(v))
    def test_no_mutation_of_input(self):
        v=fixture();m=self.api.LifecycleModel(v);v['records'].clear();self.assertEqual(m.view()['active_records'],3)
    def test_no_mutation_through_view(self):
        m=self.model();r=m.resolve('job:'+hx('one'));r['state']='CANCELLED';self.assertEqual(m.resolve(r['key'])['state'],'SUCCEEDED')
    def test_failed_command_does_not_advance(self):
        m=self.model();before=m.checkpoint();self.err('PHASE',m.compact);self.assertEqual(m.checkpoint(),before)
    def test_plan_tamper(self):
        m=self.model();p=m.plan();p['archive_bytes_estimate']=0;self.err('STALE_PLAN',lambda:m.close(p,controller_revision=1))
    def test_empty_next_generation(self):
        m=self.compacted();m.open_next(controller_revision=1);m.close(m.plan(),controller_revision=1);m.archive();m.compact();self.assertEqual(m.view()['closed_through'],2)
    def test_forward_reference_to_retained_archive(self):
        m=self.compacted();m.open_next(controller_revision=1);r=record('control','two',refs=['job:'+hx('one')]);m.admit(r,generation=2,controller_revision=1)
        m.close(m.plan(),controller_revision=1);m.archive();m.compact();self.assertEqual(m.resolve(r['key'])['refs'],['job:'+hx('one')])
    def test_replay_checkpoint_at_every_phase(self):
        m=self.model()
        for action in (lambda:None,lambda:m.close(m.plan(),controller_revision=1),m.archive,m.compact,lambda:m.open_next(controller_revision=1)):
            action();restored=self.api.LifecycleModel.restore(m.checkpoint(),expected_pin=m.pin());self.assertEqual(restored.view(),m.view());self.assertEqual(restored.checkpoint(),m.checkpoint())
    def test_checkpoint_does_not_auto_advance(self):
        m=self.closed();r=self.api.LifecycleModel.restore(m.checkpoint(),expected_pin=m.pin());self.assertEqual(r.view()['phase'],'CLOSED')
    def test_external_pin_rejects_truncation(self):
        m=self.model();raw=m.checkpoint();m.close(m.plan(),controller_revision=1);self.err('PIN_MISMATCH',lambda:self.api.LifecycleModel.restore(raw,expected_pin=m.pin()))
    def test_older_pin_accepts_extension(self):
        m=self.model();pin=m.pin();m.close(m.plan(),controller_revision=1);self.assertEqual(self.api.LifecycleModel.restore(m.checkpoint(),expected_pin=pin).view(),m.view())
    def test_pin_is_required_for_claimed_recovery(self):
        m=self.model();self.err('PIN_REQUIRED',lambda:self.api.LifecycleModel.restore(m.checkpoint(),expected_pin=None))
    def test_valid_prefix_change_detected(self):
        m=self.model();p=m.pin();r=json.loads(m.checkpoint());r['initial']['observation']=hx('other');self.err('PIN_MISMATCH',lambda:self.api.LifecycleModel.restore(json.dumps(r).encode(),expected_pin=p))
    def test_injected_unknown_event(self):
        m=self.model();r=json.loads(m.checkpoint());r['events'].append({'action':'delete_everything'});self.err('SCHEMA',lambda:self.api.LifecycleModel.restore(json.dumps(r).encode(),expected_pin=m.pin()))
    def test_illegal_event_order(self):
        m=self.model();r=json.loads(m.checkpoint());r['events'].append({'action':'compact'});self.err('PHASE',lambda:self.api.LifecycleModel.restore(json.dumps(r).encode(),expected_pin=m.pin()))
    def test_bool_pin_sequence_rejected(self):
        m=self.model();p=m.pin();p['sequence']=True;self.err('SCHEMA',lambda:self.api.LifecycleModel.restore(m.checkpoint(),expected_pin=p))
    def test_wrong_pin_scope(self):
        m=self.model();p=m.pin();p['store']=hx('other');self.err('PIN_MISMATCH',lambda:self.api.LifecycleModel.restore(m.checkpoint(),expected_pin=p))
    def test_snapshot_foreign_scope(self):
        v=fixture();v['controller']=None;m=self.api.LifecycleModel(v);self.err('STALE_CONTROLLER',lambda:m.close(m.plan(),controller_revision=1))
    def test_model_has_no_real_delete_capability(self):
        m=self.compacted();self.assertFalse(m.view()['real_deletion_allowed']);self.assertFalse(m.view()['product_qualified']);self.assertTrue(m.view()['simulation'])
