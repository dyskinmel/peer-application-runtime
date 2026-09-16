"""Pinned one-shot local reader. No implicit retry, mutation or socket discovery."""
import secrets,socket,time
from par_keeper import make_call
from par_keeper.contract import split
from par_crypto.primitives import domain,hashed
from par_recovery.contract import MAX_OBJECT,inspect_index,object_id
from .errors import ServiceError as E
from .protocol import *
from .transport import private_path,socket_identity,peer_uid,receive,send,remaining
from .server import status_unpack

class Client:
    def __init__(self,path,provider,keeper_public,subject_seed,capability,*,timeout=5):
        fixed(keeper_public);fixed(subject_seed)
        if type(timeout) not in (int,float) or not .05<=timeout<=30:raise E('PROTOCOL_SCHEMA')
        self.path=private_path(path);self.p=provider;self.public=keeper_public;self._seed=subject_seed;self.capability=capability;self.timeout=timeout
    def _call(self,action,lease,payload=None):
        if action not in METHODS:raise E('METHOD_DENIED')
        fixed(lease)
        deadline=time.monotonic()+self.timeout;sent=False;s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        try:
            identity=socket_identity(self.path);s.settimeout(remaining(deadline));s.connect(str(self.path));peer_uid(s)
            if socket_identity(self.path)!=identity:raise E('SOCKET_IDENTITY')
            hello=receive(s,MAX_HELLO,deadline);b=check_hello(self.p,self.public,hello)
            deadline=min(deadline,time.monotonic()+b[5]/1000)
            call=make_call(self.p,self._seed,self.capability,action,lease,secrets.token_bytes(32),payload)
            request=make_request(self.p,self._seed,hello,self.capability,call,action,lease,payload)
            sent=True;send(s,request,MAX_REQUEST,deadline)
            response=receive(s,MAX_RESPONSE,deadline)
            result=check_response(self.p,self.public,hello,request,response)
            return result,call
        except E as ex:
            if sent and ex.code in ('DEADLINE','DISCONNECTED'):raise E('OUTCOME_UNKNOWN') from None
            raise
        except OSError:raise E('OUTCOME_UNKNOWN' if sent else 'CONNECTION_UNAVAILABLE') from None
        finally:s.close()
    def fetch(self,lease,oid):
        fixed(oid);result,_=self._call('get',lease,oid)
        if type(result) is not bytes or not 1<=len(result)<=MAX_OBJECT:raise E('RESPONSE_TYPE')
        return result
    def status(self,lease):
        result,_=self._call('status',lease);return status_unpack(result)
    def receipt(self,lease):
        result,_=self._call('receipt',lease)
        if type(result) is not bytes:raise E('RESPONSE_TYPE')
        return result # Caller verifies historical retention with its separate Pin.
    def challenge(self,lease,nonce):
        fixed(nonce);result,call=self._call('challenge',lease,nonce)
        try:
            b,o=split(result)
            if (b[2],b[3],b[4],b[5],b[8])!=(self.public,lease,nonce,hashed('keeper-local/call',[call]),False):raise ValueError()
            self.p.verify(self.public,domain('keeper-local/observation-sign',[o[0]]),o[1])
        except Exception:raise E('RESPONSE_SCOPE') from None
        return result

class RemoteProvider:
    """Recovery Inbox port. Exact index is supplied with a separately trusted Pin."""
    def __init__(self,client,lease,index,pin):
        body,_=inspect_index(index,pin);self.client=client;self.lease=lease
        self.descriptors={d[0]:(d[1],d[2]) for d in body[15]}
    def fetch(self,oid):
        if oid not in self.descriptors:raise E('OBJECT_SCOPE')
        raw=self.client.fetch(self.lease,oid);kind,size=self.descriptors[oid]
        if len(raw)!=size or object_id(kind,raw)!=oid:raise E('DATA_INVALID')
        return raw
