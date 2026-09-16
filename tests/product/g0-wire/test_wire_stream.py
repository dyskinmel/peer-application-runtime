from wire_support import WireCase,sample
class StreamTests(WireCase):
 def test_each_byte_fragment(self):
  f=self.mod('framing');wire=f.encode_frame(sample(1));s=f.FrameReader();out=[]
  for b in wire:out+=s.feed(bytes([b]),now=0)
  self.assertEqual(out,[sample(1)]);s.finish()
 def test_concatenated_frames(self):
  f=self.mod('framing');s=f.FrameReader();self.assertEqual(s.feed(f.encode_frame(sample(1))+f.encode_frame(sample(2)),now=0),[sample(1),sample(2)]);s.finish()
 def test_empty_length(self):self.reject('LENGTH',self.mod('framing').decode_frame,b'\0'*4)
 def test_huge_length_rejected_before_body(self):
  s=self.mod('framing').FrameReader();self.reject('LENGTH',s.feed,b'\xff'*4,now=0);self.assertEqual(s.buffered_bytes,0)
 def test_partial_header_EOF(self):
  s=self.mod('framing').FrameReader();s.feed(b'\0',now=0);self.reject('TRUNCATED',s.finish)
 def test_partial_body_EOF(self):
  f=self.mod('framing');s=f.FrameReader();s.feed(f.encode_frame(sample(1))[:-1],now=0);self.reject('TRUNCATED',s.finish)
 def test_deadline_is_absolute_not_sliding(self):
  s=self.mod('framing').FrameReader(timeout=5);s.feed(b'\0',now=10);s.feed(b'\0',now=14);self.reject('TIMEOUT',s.feed,b'\0',now=15)
 def test_clock_rollback_rejected(self):
  s=self.mod('framing').FrameReader();s.feed(b'\0',now=10);self.reject('CLOCK',s.feed,b'',now=9)
 def test_clock_nan_rejected(self):self.reject('CLOCK',self.mod('framing').FrameReader().feed,b'',now=float('nan'))
 def test_reader_poisoned_after_bad_frame(self):
  s=self.mod('framing').FrameReader();self.reject('LENGTH',s.feed,b'\0'*4,now=0);self.reject('CLOSED',s.feed,b'anything',now=1)
 def test_single_decoder_rejects_stream_tail(self):
  f=self.mod('framing');wire=f.encode_frame(sample(1));self.reject('LENGTH',f.decode_frame,wire+wire)
 def test_max_frame_bytes_boundary(self):
  f=self.mod('framing');c=self.mod('codec');body=c.encode(b'a'*1048571);self.assertEqual(len(body),1048576)
  # Framing accepts exactly the budget; schema then rejects because bytes are not a frame map.
  self.reject('SCHEMA',f.decode_frame,len(body).to_bytes(4,'big')+body)
  self.reject('LENGTH',f.decode_frame,(1048577).to_bytes(4,'big'))
 def test_limited_feed_returns_backpressure_not_silent_loss(self):
  f=self.mod('framing');wire=f.encode_frame(sample(2));s=f.FrameReader(max_frames_per_feed=2)
  self.reject('RESOURCE_LIMIT',s.feed,wire*3,now=0)
 def test_finished_reader_rejects_further_feed(self):
  s=self.mod('framing').FrameReader();s.finish();self.reject('CLOSED',s.feed,b'',now=0)
