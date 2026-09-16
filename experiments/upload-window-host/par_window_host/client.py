"""Explicit, pinned client. No implicit rollover, downgrade or automatic retry."""
import socket,time,hashlib
from par_crypto.primitives import hashed
from par_keeper.contract import split
from par_keeper_service.transport import private_path,socket_identity,peer_uid,receive,send,remaining
from par_keeper_upload.client import Client as LegacyClient
from par_keeper_upload import protocol as u
from par_upload_window import contract as w
from .protocol import *

class Client(LegacyClient):
    def __init__(self,path,provider,keeper_public,subject_seed,capability,store_id,window,*,timeout=5):
        super().__init__(path,provider,keeper_public,subject_seed,capability,timeout=timeout)
        fixed(store_id);grant=w.check_window(provider,window)
        cap,_=split(capability);u.capability_shape(cap)
        if (grant[3],grant[4],cap[3],cap[4],cap[2][:2])!=(keeper_public,store_id,keeper_public,provider.sign_public(subject_seed),grant[2][:2]):raise E('WINDOW_SCOPE')
        self.store_id=store_id;self.window=window
    def command(self,action,operation,payload=None,lease=None,call=None):
        inner=super().command(action,operation,payload,lease,call)
        return w.wrap_command(self.p,self._seed,self.window,'execute',inner)
    def execute(self,command):
        outer,c=data_command(self.p,self.window,command);cap,_=split(c[4])
        if c[4]!=self.capability or cap[3]!=self.public or cap[4]!=self.p.sign_public(self._seed):raise E('REQUEST_SCOPE')
        deadline=time.monotonic()+self.timeout;sent=False;s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        try:
            identity=socket_identity(self.path);s.settimeout(remaining(deadline));s.connect(str(self.path));peer_uid(s)
            if socket_identity(self.path)!=identity:raise E('SOCKET_IDENTITY')
            hello=receive(s,MAX_HELLO,deadline);b=check_hello(self.p,self.public,self.store_id,self.window,hello)
            deadline=min(deadline,time.monotonic()+b[5]/1000)
            request=make_request(self.p,self._seed,hello,self.window,command)
            sent=True;send(s,request,MAX_REQUEST,deadline)
            result=check_response(self.p,self.public,hello,request,receive(s,MAX_RESPONSE,deadline))
            return validate_result(self.p,c,result)
        except E as ex:
            if sent and ex.code in ('DEADLINE','DISCONNECTED'):raise E('OUTCOME_UNKNOWN') from None
            raise
        except OSError:raise E('OUTCOME_UNKNOWN' if sent else 'CONNECTION_UNAVAILABLE') from None
        finally:s.close()
    def upload_bundle(self,index,pin,objects,seconds,operation):
        fixed(operation)
        # Convenience operation IDs must differ across window generations.
        root=hashed('upload-window-host-local/operation',[w.digest(self.window),operation])
        return super().upload_bundle(index,pin,objects,seconds,root)

def validate_result(p,c,result):
    """Validate successful signed responses against the original stable command."""
    cap,_=split(c[4])
    if c[2] in ('begin','chunk','progress'):
        u.progress_shape(result)
        # No new signatures when validating a historical command/result.
        token=hashed('keeper-upload-local/stage',[cap[3],cap[4],c[3]]) if c[2]=='begin' else (c[7][0] if c[2]=='chunk' else c[7])
        if result[0]!=token:raise E('RESPONSE_SCOPE')
        if c[2]=='begin':
            if result[2]!=c[7][2]:raise E('RESPONSE_SCOPE')
            if result[1]==result[2] and result[3]!=c[7][3]:raise E('RESPONSE_SCOPE')
        if result[1]==0 and result[3]!=hashlib.sha256(b'').digest():raise E('RESPONSE_SCOPE')
        if c[2]=='chunk' and result[1]<c[7][1]+len(c[7][2]):raise E('RESPONSE_SCOPE')
    elif c[2]=='reserve':
        fixed(result);inner,_=split(c[5]);expected=hashed('keeper-local/lease-id',[cap[3],cap[4],inner[7]])
        if result!=expected:raise E('RESPONSE_SCOPE')
    elif c[2]=='put':fixed(result) # full object identity also checked by upload_object
    elif type(result) is not bytes:raise E('RESPONSE_TYPE')
    return load(dump(result,MAX_RESPONSE),MAX_RESPONSE)
