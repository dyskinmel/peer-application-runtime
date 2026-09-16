"""Actual EventJournal owner adapter; public synthetic test keys only."""
import importlib
from test_events import EventTest

class OwnerPortTests(EventTest):
    def port(self):
        try: m=importlib.import_module('product.wp10.sdk')
        except ModuleNotFoundError: m=None
        self.assertIsNotNone(m, 'event owner port is not implemented')
        self.m=m
        return m.EventOwnerPort(self.journal,b'c'*16)
    def test_open_context_and_zero_cursor(self):
        self.create();p=self.port();r=p.open({'context':p.context(),'expectedCursor':None})
        self.assertEqual(r['kind'],'opened');self.assertEqual(r['cursor']['position'],'0')
    def test_poll_and_ack_are_separate(self):
        self.create();self.emit();p=self.port();s=p.open({'context':p.context(),'expectedCursor':None})
        req={'sessionId':s['sessionId'],'limit':16,'byteLimit':262144};a=p.poll(req);b=p.poll(req)
        self.assertEqual(a,b);self.assertEqual(a['cursor']['position'],'0')
        r=p.ack({'sessionId':s['sessionId'],'token':a['ackToken']});self.assertEqual(r['cursor']['position'],'1')
    def test_uint64_does_not_round(self):
        self.create();self.emit();p=self.port();s=p.open({'context':p.context(),'expectedCursor':None})
        r=p.poll({'sessionId':s['sessionId'],'limit':1,'byteLimit':262144})
        self.assertEqual(r['events'][0]['payload']['count'],{'kind':'uint64','value':str(2**63+1)})
    def test_cancel_does_not_ack(self):
        self.create();self.emit();p=self.port();s=p.open({'context':p.context(),'expectedCursor':None});p.poll({'sessionId':s['sessionId'],'limit':1,'byteLimit':262144});p.cancel({'sessionId':s['sessionId']})
        q=self.m.EventOwnerPort(self.journal,b'c'*16);r=q.open({'context':q.context(),'expectedCursor':None});self.assertEqual(r['cursor']['position'],'0')
    def opened(self):
        self.create();self.emit();p=self.port();r=p.open({'context':p.context(),'expectedCursor':None});return p,r
    def test_session_mismatch(self):
        p,s=self.opened();self.rejects('SDK_SESSION_MISMATCH',lambda:p.poll({'sessionId':'00'*16,'limit':1,'byteLimit':1024}))
    def test_unknown_input_key(self):
        p,s=self.opened();self.rejects('SDK_INPUT_INVALID',lambda:p.poll({'sessionId':s['sessionId'],'limit':1,'byteLimit':1024,'execute':True}))
    def test_bool_limit_is_not_integer(self):
        p,s=self.opened();self.rejects('INVALID_INPUT',lambda:p.poll({'sessionId':s['sessionId'],'limit':True,'byteLimit':1024}))
    def test_context_mismatch_no_consumer_created(self):
        self.create();p=self.port();ctx=p.context();ctx['epoch']='2';self.rejects('SDK_CONTEXT_MISMATCH',lambda:p.open({'context':ctx,'expectedCursor':None}));self.assertEqual(self.journal.inspect()['consumers'],0)
    def test_duplicate_open_refused(self):
        p,s=self.opened();self.rejects('SUBSCRIPTION_BUSY',lambda:p.open({'context':p.context(),'expectedCursor':None}))
    def test_cancel_is_idempotent(self):
        p,s=self.opened();self.assertEqual(p.cancel({'sessionId':s['sessionId']}),p.cancel({'sessionId':s['sessionId']}))
    def test_cancelled_poll_refused(self):
        p,s=self.opened();p.cancel({'sessionId':s['sessionId']});self.rejects('SUBSCRIPTION_CLOSED',lambda:p.poll({'sessionId':s['sessionId'],'limit':1,'byteLimit':1024}))
    def test_context_is_a_copy(self):
        self.create();p=self.port();a=p.context();a['schema']['body']='bytes';self.assertEqual(p.context()['schema']['body'],'text')
    def test_cursor_pin_metadata_mismatch(self):
        p,s=self.opened();p.cancel({'sessionId':s['sessionId']});q=self.m.EventOwnerPort(self.journal,b'c'*16);c=dict(s['cursor']);c['position']='2';self.rejects('CURSOR_INVALID',lambda:q.open({'context':q.context(),'expectedCursor':c}))
    def test_reopened_unacked_redelivers_new_session(self):
        p,s=self.opened();b=p.poll({'sessionId':s['sessionId'],'limit':1,'byteLimit':1024});self.reopen();q=self.m.EventOwnerPort(self.journal,b'c'*16);n=q.open({'context':q.context(),'expectedCursor':s['cursor']});self.assertNotEqual(s['sessionId'],n['sessionId']);self.assertEqual(q.poll({'sessionId':n['sessionId'],'limit':1,'byteLimit':1024})['events'],b['events'])
    def test_old_session_ack_refused(self):
        p,s=self.opened();b=p.poll({'sessionId':s['sessionId'],'limit':1,'byteLimit':1024});self.reopen();q=self.m.EventOwnerPort(self.journal,b'c'*16);n=q.open({'context':q.context(),'expectedCursor':None});self.rejects('CURSOR_INVALID',lambda:q.ack({'sessionId':n['sessionId'],'token':b['ackToken']}))
    def test_authority_change_rejects_ack(self):
        p,s=self.opened();b=p.poll({'sessionId':s['sessionId'],'limit':1,'byteLimit':1024});self.same_epoch();self.rejects('AUTHORITY_CHANGED',lambda:p.ack({'sessionId':s['sessionId'],'token':b['ackToken']}));self.assertEqual(p.cursor({'sessionId':s['sessionId']})['cursor']['position'],'0')
    def test_lost_ack_reopen_observes_committed_cursor(self):
        p,s=self.opened();b=p.poll({'sessionId':s['sessionId'],'limit':1,'byteLimit':1024})
        def lost(stage):
            if stage=='ack.after_commit':raise OSError('lost reply')
        self.journal.observer=lost;self.rejects('EVENT_OUTCOME_UNKNOWN',lambda:p.ack({'sessionId':s['sessionId'],'token':b['ackToken']}));self.reopen();q=self.m.EventOwnerPort(self.journal,b'c'*16);n=q.open({'context':q.context(),'expectedCursor':s['cursor']});self.assertEqual(n['cursor']['position'],'1')
    def test_signed_unsigned_bytes_exact(self):
        self.create(schema={'s':'int64','u':'uint64','raw':'bytes','yes':'bool','text':'text'});self.journal.publish(b'o'*16,{'s':-2**63,'u':2**64-1,'raw':b'\x00\xff','yes':False,'text':'日本語🎵'});p=self.port();s=p.open({'context':p.context(),'expectedCursor':None});v=p.poll({'sessionId':s['sessionId'],'limit':1,'byteLimit':1024})['events'][0]['payload'];self.assertEqual(v['s']['value'],str(-2**63));self.assertEqual(v['u']['value'],str(2**64-1));self.assertEqual(v['raw']['value'],'00ff');self.assertEqual(v['yes']['value'],False)
    def test_too_small_window_does_not_skip(self):
        p,s=self.opened();self.rejects('EVENT_EXCEEDS_WINDOW',lambda:p.poll({'sessionId':s['sessionId'],'limit':1,'byteLimit':1}));self.assertEqual(p.cursor({'sessionId':s['sessionId']})['cursor']['position'],'0')
    def test_poll_does_not_publish_nonce(self):
        p,s=self.opened();before=self.journal.inspect();p.poll({'sessionId':s['sessionId'],'limit':1,'byteLimit':1024});after=self.journal.inspect();self.assertEqual(before['events'],after['events']);self.assertEqual(before['nonces'],after['nonces'])
