from submit_support import SubmitTest,h
class SubmitContract(SubmitTest):
    def test_pack_roundtrip(self):
        a,q=self.proposed();r=self.sc.pack_job('close',q,a);self.assertEqual(self.sc.unpack_job(r),('close',q,a))
    def test_compact_no_payload(self):self.assertEqual(self.sc.unpack_job(self.sc.pack_job('compact',None,None)),('compact',None,None))
    def test_unknown_action(self):self.err(None,lambda:self.sc.pack_job('shell',b'x',None))
    def test_close_needs_archive(self):self.err(None,lambda:self.sc.pack_job('close',b'x',None))
    def test_wrong_magic(self):self.err(None,lambda:self.sc.unpack_job(b'BADMAGIC'+self.payload()[8:]))
    def test_trailing_bytes(self):self.err(None,lambda:self.sc.unpack_job(self.payload()+b'x'))
    def test_header_size(self):self.err(None,lambda:self.sc.unpack_job(b'PARJSUB1'+(2**31).to_bytes(4,'big')+b'x'))
    def test_corrupt_archive(self):
        raw=bytearray(self.payload());raw[-1]^=1;self.err(None,lambda:self.sc.unpack_job(bytes(raw)))
    def test_descriptor_roundtrip(self):
        raw=self.payload();d=self.descriptor(raw);b=self.sc.check_descriptor(self.p,d);self.assertEqual(b[7],len(raw));self.assertEqual(b[5],self.jid())
    def test_descriptor_signature(self):
        d=bytearray(self.descriptor());d[-1]^=1;self.err(None,lambda:self.sc.check_descriptor(self.p,bytes(d)))
    def test_descriptor_bool_size(self):self.err(None,lambda:self.descriptor(size=True))
    def test_descriptor_bool_revision(self):self.err(None,lambda:self.descriptor(revision=True))
    def test_descriptor_big_size(self):self.err(None,lambda:self.descriptor(size=self.sc.MAX_PAYLOAD+1))
    def test_descriptor_hash_length(self):self.err(None,lambda:self.descriptor(payload_hash=b'x'))
    def test_descriptor_unknown_field(self):
        d=self.sc.check_descriptor(self.p,self.descriptor());d[100]=1
        raw=self.sc.signed(self.p,self.os,'descriptor',d,self.sc.MAX_DESCRIPTOR)
        self.err(None,lambda:self.sc.check_descriptor(self.p,raw))
    def test_profile_boundary(self):
        d=self.sc.check_descriptor(self.p,self.descriptor());d[1]='host-job-control-local-v1'
        self.err(None,lambda:self.sc.check_descriptor(self.p,self.sc.signed(self.p,self.os,'descriptor',d,self.sc.MAX_DESCRIPTOR)))
    def test_header_boolean_archive_size(self):
        h={0:1,1:'compact',2:None,3:False,4:None};raw=self.sc.dump(h,self.sc.MAX_HEADER)
        self.err(None,lambda:self.sc.unpack_job(self.sc.MAGIC+len(raw).to_bytes(4,'big')+raw))
    def test_large_archive_pack_not_frame(self):
        data=b'a'*(1048576+1);raw=self.sc.pack_job('close',b'cmd',data)
        self.assertEqual(self.sc.unpack_job(raw)[2],data);self.assertGreater(len(raw),self.sc.MAX_REQUEST)
