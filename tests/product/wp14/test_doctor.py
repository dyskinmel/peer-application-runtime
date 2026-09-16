import json, unittest

class DoctorTests(unittest.TestCase):
    def setUp(self):
        from product.wp14.par_native_provider import doctor,model,handoff
        self.d=doctor;self.m=model;self.h=handoff;self.epoch='11'*16

    def test_missing_provider_is_blocked_not_pass(self):
        r=self.d.local_doctor(None)
        self.assertEqual(r['result'],'BLOCKED');self.assertEqual(r['executedNativeOperations'],0)

    def test_doctor_is_read_only_and_no_egress(self):
        calls=[];desc=self.m.experimental_posix_descriptor(epoch=self.epoch)
        bundle=self.h.ProviderBundle(desc,pin_factory=lambda *a:calls.append(a),connection_factory=lambda *a:calls.append(a))
        r=self.d.local_doctor(bundle)
        self.assertEqual(r['result'],'PASS');self.assertEqual(r['egressAttempts'],0);self.assertEqual(calls,[])

    def test_doctor_output_has_no_secret_or_path_values(self):
        desc=self.m.experimental_posix_descriptor(epoch=self.epoch)
        r=self.d.local_doctor(self.h.ProviderBundle(desc))
        text=json.dumps(r,sort_keys=True)
        for canary in ('BEGIN PRIVATE KEY','invite-secret','/Users/alice','/home/alice'):self.assertNotIn(canary,text)

    def test_build_not_run_is_not_available(self):
        desc=self.m.apple_source_descriptor(epoch='22'*16)
        r=self.d.local_doctor(self.h.ProviderBundle(desc))
        self.assertEqual(r['nativeBuild'],'BUILD_NOT_RUN');self.assertFalse(r['osProtectionProven'])

    def test_capability_probe_is_injected_not_shell_magic(self):
        desc=self.m.experimental_posix_descriptor(epoch=self.epoch)
        r=self.d.local_doctor(self.h.ProviderBundle(desc),tool_probe=lambda:{'swiftc':False,'rustc':False,'cargo':False})
        self.assertEqual(r['toolchain'],{'swiftc':'NOT_FOUND','rustc':'NOT_FOUND','cargo':'NOT_FOUND'})

    def test_export_requires_explicit_request(self):
        desc=self.m.experimental_posix_descriptor(epoch=self.epoch)
        r=self.d.local_doctor(self.h.ProviderBundle(desc))
        self.assertNotIn('export',r);self.assertFalse(r['telemetryEnabled'])

    def test_result_scope_and_freshness_present(self):
        desc=self.m.experimental_posix_descriptor(epoch=self.epoch)
        r=self.d.local_doctor(self.h.ProviderBundle(desc),observed_at='2026-09-10T00:00:00Z')
        self.assertEqual(r['scope'],'LOCAL_PROVIDER_CAPABILITY_ONLY');self.assertEqual(r['observedAt'],'2026-09-10T00:00:00Z');self.assertEqual(r['freshness'],'CURRENT_PROCESS')

    def test_descriptor_epoch_is_redacted_but_bound(self):
        desc=self.m.experimental_posix_descriptor(epoch=self.epoch)
        r=self.d.local_doctor(self.h.ProviderBundle(desc))
        self.assertNotIn(self.epoch,json.dumps(r));self.assertEqual(len(r['providerEpochRef']),16)

if __name__=='__main__':unittest.main()
