"""Explicit, pinned one-shot upload client. Reconnect/retry is caller-controlled."""
import hashlib,socket,time
from par_keeper import make_call
from par_keeper.contract import split,reserve_payload,pin_values,put_payload,verify_receipt,authority_from,capability_id
from par_recovery.contract import inspect_index,object_id
from par_crypto.primitives import hashed
from par_keeper_service.transport import private_path,socket_identity,peer_uid,receive,send,remaining
from .protocol import *

def op(root,label):return hashed('keeper-upload-local/operation',[root,label])
class Client:
    def __init__(self,path,provider,keeper_public,subject_seed,capability,*,timeout=5):
        fixed(keeper_public);fixed(subject_seed)
        if type(timeout) not in (int,float) or not .05<=timeout<=30:raise E('PROTOCOL_SCHEMA')
        self.path=private_path(path);self.p=provider;self.public=keeper_public;self._seed=subject_seed;self.capability=capability;self.timeout=timeout
    def command(self,action,operation,payload=None,lease=None,call=None):
        return make_command(self.p,self._seed,self.capability,action,operation,call,lease,payload)
    def execute(self,command):
        c=check_command(self.p,command);cap,_=split(c[4])
        if c[4]!=self.capability or cap[3]!=self.public or cap[4]!=self.p.sign_public(self._seed):raise E('REQUEST_SCOPE')
        deadline=time.monotonic()+self.timeout;sent=False;s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        try:
            identity=socket_identity(self.path);s.settimeout(remaining(deadline));s.connect(str(self.path));peer_uid(s)
            if socket_identity(self.path)!=identity:raise E('SOCKET_IDENTITY')
            hello=receive(s,MAX_HELLO,deadline);b=check_hello(self.p,self.public,hello);deadline=min(deadline,time.monotonic()+b[5]/1000)
            request=make_request(self.p,self._seed,hello,command)
            sent=True;send(s,request,MAX_REQUEST,deadline)
            result=check_response(self.p,self.public,hello,request,receive(s,MAX_RESPONSE,deadline))
            if c[2] in ('begin','chunk','progress'):
                progress_shape(result);token=token_for(self.p,command) if c[2]=='begin' else (c[7][0] if c[2]=='chunk' else c[7])
                if result[0]!=token:raise E('RESPONSE_SCOPE')
                if c[2]=='begin' and result[2]!=c[7][2]:raise E('RESPONSE_SCOPE')
                if c[2]=='chunk' and result[1]<c[7][1]+len(c[7][2]):raise E('RESPONSE_SCOPE')
            elif c[2]=='reserve':
                fixed(result);inner,_=split(c[5]);expected=hashed('keeper-local/lease-id',[self.public,cap[4],inner[7]])
                if result!=expected:raise E('RESPONSE_SCOPE')
            elif c[2]=='put':
                fixed(result);inner,_=split(c[5])
                # The stable put payload commitment is verified by Keeper; high-level
                # upload_object also checks the returned ID against its local bytes.
            elif type(result) is not bytes:raise E('RESPONSE_TYPE')
            return result
        except E as ex:
            if sent and ex.code in ('DEADLINE','DISCONNECTED'):raise E('OUTCOME_UNKNOWN') from None
            raise
        except OSError:raise E('OUTCOME_UNKNOWN' if sent else 'CONNECTION_UNAVAILABLE') from None
        finally:s.close()
    def begin(self,kind,oid,raw,operation,lease=None,call=None):
        if type(raw) is not bytes:raise E('PROTOCOL_SCHEMA')
        q=self.command('begin',operation,[kind,oid,len(raw),hashlib.sha256(raw).digest()],lease,call)
        r=self.execute(q)
        if r[3]!=hashlib.sha256(raw[:r[1]]).digest():raise E('RESPONSE_SCOPE')
        return r[0],r
    def chunk(self,token,offset,data,lease=None):
        fixed(token);integer(offset,0,max(MAX_INDEX,MAX_OBJECT))
        if type(data) is not bytes or not 1<=len(data)<=CHUNK:raise E('PROTOCOL_SCHEMA')
        return self.execute(self.command('chunk',op(token,['chunk',offset,hashlib.sha256(data).digest()]),[token,offset,data],lease))
    def progress(self,token,lease=None):return self.execute(self.command('progress',op(token,'progress'),token,lease))
    def stream(self,token,raw,lease=None):
        fixed(token)
        if type(raw) is not bytes or not 1<=len(raw)<=max(MAX_INDEX,MAX_OBJECT):raise E('PROTOCOL_SCHEMA')
        r=self.progress(token,lease)
        if r[2]!=len(raw) or r[3]!=hashlib.sha256(raw[:r[1]]).digest():raise E('RESPONSE_SCOPE')
        if r[4]:return r
        for offset in range(r[1],len(raw),CHUNK):r=self.chunk(token,offset,raw[offset:offset+CHUNK],lease)
        if r[3]!=hashlib.sha256(raw).digest():raise E('RESPONSE_SCOPE')
        return r
    def reserve_command(self,token,index,pin,seconds,operation):
        call=make_call(self.p,self._seed,self.capability,'reserve',None,operation,reserve_payload(index,pin,seconds))
        return self.command('reserve',operation,[token,pin_values(pin),seconds],call=call)
    def reserve(self,token,index,pin,seconds,operation):return self.execute(self.reserve_command(token,index,pin,seconds,operation))
    def upload_object(self,lease,oid,raw,operation):
        call=make_call(self.p,self._seed,self.capability,'put',lease,op(operation,'put'),put_payload(oid,raw))
        token,_=self.begin('object',oid,raw,op(operation,'begin'),lease,call);self.stream(token,raw,lease)
        result=self.execute(self.command('put',op(operation,'put-final'),token,lease,call))
        if result!=oid:raise E('RESPONSE_SCOPE')
        return result
    def seal(self,lease,index,pin,operation):
        call=make_call(self.p,self._seed,self.capability,'seal',lease,operation)
        result=self.execute(self.command('seal',operation,None,lease,call));cap,_=split(self.capability)
        verify_receipt(self.p,result,self.public,index,pin,lease,authority_from(cap[2]),operation,capability_id(self.capability))
        return result
    def upload_bundle(self,index,pin,objects,seconds,operation):
        fixed(operation);body,_=inspect_index(index,pin)
        if type(objects) is not dict or set(objects)!={d[0] for d in body[15]}:raise E('OBJECT_SCOPE')
        for oid,kind,n in body[15]:
            raw=objects[oid]
            if type(raw) is not bytes or len(raw)!=n or object_id(kind,raw)!=oid:raise E('DATA_INVALID')
        token,_=self.begin('index',pin.index_id,index,op(operation,'index-begin'));self.stream(token,index)
        lease=self.reserve(token,index,pin,seconds,op(operation,'reserve'))
        for oid in sorted(objects):self.upload_object(lease,oid,objects[oid],op(operation,['object',oid]))
        return lease,self.seal(lease,index,pin,op(operation,'seal'))
