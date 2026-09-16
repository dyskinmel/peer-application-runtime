from recovery_support import *
class Contract(RecoveryTest):
    def test_complete_readonly_view(self):
        b=self.collect();v=self.verify(b);self.assertEqual(v.status()['state'],'RECIPIENT_VALIDATED_READ_ONLY');self.assertFalse(v.status()['applied'])
    def test_missing_object_rejected(self):
        b=self.collect();b.objects.pop(next(iter(b.objects)));self.reject_rc('OBJECT_SET',lambda:self.verify(b))
    def test_extra_object_rejected(self):
        b=self.collect();b.objects[h('extra')]=b'X';self.reject_rc('OBJECT_SET',lambda:self.verify(b))
    def test_wrong_content_rejected(self):
        b=self.collect();i=next(iter(b.objects));b.objects[i]=b'x'*len(b.objects[i]);self.reject_rc('OBJECT_HASH',lambda:self.verify(b))
    def test_index_digest_required(self):
        b=self.collect();self.reject_rc('PIN_MISMATCH',lambda:self.verify(b,replace(self.pin(b),index_id=h('wrong'))))
    def test_wrong_recipient(self):
        b=self.collect();self.reject_rc('PIN_MISMATCH',lambda:self.verify(b,replace(self.pin(b),recipient_id=h('wrong'))))
    def test_wrong_certificate_pin(self):
        b=self.collect();self.reject_rc('PIN_MISMATCH',lambda:self.verify(b,replace(self.pin(b),certificate_id=h('wrong'))))
    def test_wrong_space(self):
        b=self.collect();self.reject_rc('PIN_MISMATCH',lambda:self.verify(b,replace(self.pin(b),space=h('wrong'))))
    def test_wrong_head(self):
        b=self.collect();self.reject_rc('PIN_MISMATCH',lambda:self.verify(b,replace(self.pin(b),head=h('wrong'))))
    def test_wrong_epoch(self):
        b=self.collect();self.reject_rc('PIN_MISMATCH',lambda:self.verify(b,replace(self.pin(b),epoch=2)))
    def test_wrong_roots(self):
        b=self.collect();self.reject_rc('PIN_MISMATCH',lambda:self.verify(b,replace(self.pin(b),roots=(h('wrong'),))))
    def test_wrong_secret(self):
        b=self.collect();self.reject_rc('RECIPIENT_CRYPTO',lambda:self.verify(b,secret=h('wrong')))
    def test_unknown_index_field(self):
        b=self.rewrite(self.collect(),lambda v:v.update({99:0}));self.reject_rc('INDEX_SCHEMA',lambda:self.verify(b))
    def test_duplicate_descriptor(self):
        b=self.rewrite(self.collect(),lambda v:v[15].append(v[15][0]));self.reject_rc('INDEX_SCHEMA',lambda:self.verify(b))
    def test_duplicate_entry(self):
        b=self.rewrite(self.collect(),lambda v:v[14].append(v[14][0]));self.reject_rc('INDEX_SCHEMA',lambda:self.verify(b))
    def test_duplicate_root(self):
        b=self.rewrite(self.collect(),lambda v:v[9].append(v[9][0]));self.reject_rc('INDEX_SCHEMA',lambda:self.verify(b))
    def test_unsorted_descriptors(self):
        b=self.rewrite(self.collect(),lambda v:v[15].reverse());self.reject_rc('INDEX_SCHEMA',lambda:self.verify(b))
    def test_unknown_object_type(self):
        b=self.rewrite(self.collect(),lambda v:v[15][0].__setitem__(1,'unknown'));self.reject_rc('INDEX_SCHEMA',lambda:self.verify(b))
    def test_zero_object_size(self):
        b=self.rewrite(self.collect(),lambda v:v[15][0].__setitem__(2,0));self.reject_rc('INDEX_SCHEMA',lambda:self.verify(b))
    def test_index_unknown_version(self):
        b=self.rewrite(self.collect(),lambda v:v.__setitem__(0,2));self.reject_rc('INDEX_SCHEMA',lambda:self.verify(b))
    def test_index_bool_version(self):
        b=self.rewrite(self.collect(),lambda v:v.__setitem__(0,True));self.reject_rc('INDEX_SCHEMA',lambda:self.verify(b))
    def test_index_trailing_bytes(self):
        b=self.collect();b=self.rc.Bundle(b.index+b'\0',b.objects);self.reject_rc('INDEX_SCHEMA',lambda:self.verify(b))
    def test_signature_corrupt_even_if_pin_matches(self):
        b=self.collect();o=decode(b.index,max_bytes=524288);o[1]=bytes([o[1][0]^1])+o[1][1:];b=self.rc.Bundle(encode(o,max_bytes=524288),b.objects)
        self.reject_rc('INDEX_SIGNATURE',lambda:self.verify(b))
    def test_keeper_not_exporter(self):self.reject_rc('NOT_AUTHORIZED',lambda:self.collect(certificate=self.s.devices[2]['cert'],seed=self.s.devices[2]['seed']))
    def test_reader_not_exporter(self):self.reject_rc('NOT_AUTHORIZED',lambda:self.collect(certificate=self.reader['cert'],seed=self.reader['seed']))
    def test_exporter_key_mismatch(self):self.reject_rc('SIGNER_MISMATCH',lambda:self.collect(seed=h('wrong')))
    def test_no_new_member_grant(self):
        d=self.s.devices[2];g=replace(self.grant,certificate=d['cert']);self.reject_rc('NOT_AUTHORIZED',lambda:self.collect(grant=g))
    def test_empty_roots(self):self.reject_rc('ROOT_SET',lambda:self.collect(roots=()))
    def test_duplicate_roots_input(self):self.reject_rc('ROOT_SET',lambda:self.collect(roots=(self.receipt.envelope_id,)*2))
    def test_missing_root_input(self):self.reject_rc('DEPENDENCY_MISSING',lambda:self.collect(roots=(h('missing'),)))
    def test_boolean_pin_sequence_refused(self):
        b=self.collect();self.reject_rc('PIN_MISMATCH',lambda:self.verify(b,replace(self.pin(b),sequence=True)))
    def test_declared_objects_exceed_byte_budget(self):
        def mut(v):
            for d in v[15]:d[2]=900001
        b=self.rewrite(self.collect(),mut);self.reject_rc('INDEX_SCHEMA',lambda:self.verify(b))
    def test_wrong_index_tag(self):
        b=self.rewrite(self.collect(),lambda v:v.__setitem__(1,'other'));self.reject_rc('INDEX_SCHEMA',lambda:self.verify(b))
    def test_wrong_object_length_not_only_digest(self):
        b=self.rewrite(self.collect(),lambda v:v[15][0].__setitem__(2,v[15][0][2]+1));self.reject_rc('OBJECT_HASH',lambda:self.verify(b))
    def test_wrong_kind_reference_rejected(self):
        def mut(v):
            e=next(d for d in v[15] if d[1]=='envelope');v[10]=e[0]
        b=self.rewrite(self.collect(),mut);self.reject_rc('OBJECT_REFERENCE',lambda:self.verify(b))
    def test_descriptor_same_count_different_identity(self):
        def mut(v):v[15][0][0]=h('substituted');v[15].sort()
        b=self.rewrite(self.collect(),mut);self.reject_rc('OBJECT_SET',lambda:self.verify(b))

    def test_frozen_candidate_vector(self):
        import json
        root=Path(__file__).resolve().parents[3]
        v=json.loads((root/'experiments/recovery-closure/fixtures/closure-current-epoch.json').read_text())
        pp=v['pin'];pin=self.rc.Pin(pp[0],bytes.fromhex(pp[1]),bytes.fromhex(pp[2]),pp[3],pp[4],bytes.fromhex(pp[5]),bytes.fromhex(pp[6]),tuple(bytes.fromhex(x) for x in pp[7]),bytes.fromhex(pp[8]))
        bundle=self.rc.Bundle(bytes.fromhex(v['index_hex']),{bytes.fromhex(k):bytes.fromhex(r) for k,r in v['objects'].items()})
        view=self.rc.verify(bundle,pin,self.p,h('recipient-1'));view.export_file(pin.roots[0],self.output)
        self.assertEqual(self.output.read_bytes(),bytes.fromhex(v['plaintext_hex']))
