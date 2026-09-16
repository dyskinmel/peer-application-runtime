import copy
from lifecycle_support import ModelTest,fixture,hx

class PresenterTests(ModelTest):
    def test_live_requires_migration_even_all_terminal(self):
        v=fixture();v['source']='LIVE_READONLY';v['gates']={k:False for k in v['gates']}
        p=self.api.present(v)
        self.assertEqual(p['state'],'MIGRATION_REQUIRED');self.assertFalse(p['can_delete']);self.assertIsNone(p['completion_percent'])
    def test_model_is_labeled_not_runtime_qualified(self):
        p=self.api.present(fixture())
        self.assertEqual(p['state'],'MODEL_ELIGIBLE');self.assertTrue(p['simulation']);self.assertFalse(p['can_delete'])
    def test_counts_by_ledger(self):
        p=self.api.present(fixture())
        self.assertEqual({k:x['records'] for k,x in p['ledgers'].items()},{'job':1,'control':1,'submission':1})
    def test_unknown_needs_resolution(self):
        v=fixture();r=next(x for x in v['records'] if x['kind']=='control');r['state']='OUTCOME_UNKNOWN'
        p=self.api.present(v);self.assertEqual(p['state'],'RESOLUTION_REQUIRED');self.assertEqual(p['ledgers']['control']['unresolved'],1)
    def test_pending_staging_not_free_space(self):
        v=fixture();r=next(x for x in v['records'] if x['kind']=='submission');r.update(state='RECEIVING',reserved_bytes=100)
        p=self.api.present(v);self.assertEqual(p['reserved_bytes'],100);self.assertNotIn('disk_free_bytes',p)
    def test_does_not_expose_physical_deletion_action(self):
        p=self.api.present(fixture());self.assertEqual(p['allowed_actions'],['inspect_references','export_inventory'])
    def test_no_mutation(self):
        v=fixture();expected=copy.deepcopy(v);self.api.present(v);self.assertEqual(v,expected)
    def test_revoked_controller_blocks_model_plan(self):
        v=fixture();v['controller']=None
        self.assertIn('CONTROLLER_UNAVAILABLE',self.api.plan(v)['blockers'])
    def test_multiple_generations_obey_total_archive_budget(self):
        from par_record_lifecycle import model as module
        from unittest.mock import patch
        m=self.compacted();m.open_next(controller_revision=1)
        from lifecycle_support import record
        m.admit(record('job','large','CANCELLED'),generation=2,controller_revision=1)
        with patch.object(module,'MAX_ARCHIVE_ESTIMATE',3999):
            self.assertIn('ARCHIVE_BUDGET',m.plan()['blockers'])
            self.err('BLOCKED',lambda:m.close(m.plan(),controller_revision=1))
    def test_registered_reference_into_archive_must_match(self):
        from lifecycle_support import record
        m=self.compacted();m.open_next(controller_revision=1);j=next(x for x in fixture()['records'] if x['kind']=='job')
        r=record('submission','other',refs=[j['key']]);r['evidence_digest']=hx('wrong')
        self.err('REFERENCE_MISMATCH',lambda:m.admit(r,generation=2,controller_revision=1))
