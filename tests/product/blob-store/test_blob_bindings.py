from blob_support import *
class BindingTests(BlobTest):
    def test_typed_and_raw_ids_are_distinct(self):
        a=self.attachment();b=self.verify(a);self.assertEqual(b.typed_id,objects.block_id(a.sealed_bytes));self.assertEqual(b.locator,hashlib.sha256(a.sealed_bytes).digest());self.assertNotEqual(b.typed_id,b.locator)
    def test_header_fields_roundtrip(self):
        a=self.attachment(7);b=self.verify(a);self.assertEqual((b.app,b.space,b.epoch,b.object_id,b.kind,b.index,b.plain_size),(self.s.app,self.s.space,1,h('blob-object'),3,7,20))
    def test_wrong_typed_id_rejected(self):
        a=self.attachment();self.reject('BLOCK_ID_MISMATCH',lambda:self.verify(replace(a,typed_id=h('wrong'))))
    def test_raw_locator_cannot_be_used_as_typed_id(self):
        a=self.attachment();self.reject('BLOCK_ID_MISMATCH',lambda:self.verify(replace(a,typed_id=hashlib.sha256(a.sealed_bytes).digest())))
    def test_changed_ciphertext_rejected_even_with_updated_id(self):
        a=self.attachment();v=decode(a.sealed_bytes);v[2]=v[2][:-1]+bytes([v[2][-1]^1]);raw=encode(v);self.reject('AEAD_INVALID',lambda:self.verify(replace(a,typed_id=objects.block_id(raw),sealed_bytes=raw)))
    def test_wrong_secret_rejected(self):self.reject('AEAD_INVALID',lambda:self.verify(self.attachment(),h('wrong')))
    def test_header_replacement_rejected(self):
        a=self.attachment();v=decode(a.header_bytes);v[5]=2;self.reject('BLOCK_HEADER_MISMATCH',lambda:self.verify(replace(a,header_bytes=encode(v))))
    def test_space_substitution_rejected(self):self.reject('BLOCK_CONTEXT_MISMATCH',lambda:self.verify(self.attachment(header={1:h('other-space')})))
    def test_epoch_substitution_rejected(self):self.reject('BLOCK_CONTEXT_MISMATCH',lambda:self.verify(self.attachment(header={2:2})))
    def test_app_substitution_rejected(self):self.reject('BLOCK_CONTEXT_MISMATCH',lambda:self.verify(self.attachment(header={0:'org.other.app'})))
    def test_non_blob_kind_rejected(self):self.reject('BLOCK_KIND',lambda:self.verify(self.attachment(header={4:1})))
    def test_zero_length_chunk_is_valid(self):self.assertEqual(self.verify(self.attachment(plain=b'')).plain_size,0)
    def test_maximum_plain_chunk_is_valid(self):self.assertEqual(self.verify(self.attachment(plain=b'x'*262144)).plain_size,262144)
    def test_truncated_block_rejected(self):
        a=self.attachment();raw=a.sealed_bytes[:-1];self.reject(None,lambda:self.verify(replace(a,typed_id=objects.block_id(raw),sealed_bytes=raw)))
    def test_trailing_bytes_rejected(self):
        a=self.attachment();raw=a.sealed_bytes+b'\0';self.reject(None,lambda:self.verify(replace(a,typed_id=objects.block_id(raw),sealed_bytes=raw)))
    def test_mutable_bytes_rejected(self):
        a=self.attachment();self.reject('BLOB_INPUT',lambda:self.verify(replace(a,sealed_bytes=bytearray(a.sealed_bytes))))
    def test_incorrect_id_width_rejected(self):self.reject('BLOB_INPUT',lambda:self.verify(replace(self.attachment(),typed_id=b'x')))
    def test_invalid_header_type_rejected(self):self.reject('BLOB_INPUT',lambda:self.verify(replace(self.attachment(),header_bytes={})))
    def test_repr_does_not_dump_ciphertext(self):self.assertNotIn('sealed_bytes=',repr(self.attachment()))
