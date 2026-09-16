"""Pinned one-request connections. No automatic submission or effect replay."""
import math,socket,time
from par_keeper_service.transport import private_path,socket_identity,peer_uid,remaining,receive,send
from . import protocol as c
E=c.E
class Client:
    def __init__(self,path,provider,keeper_public,store_id,owner_seed,revision,*,timeout=5):
        for v in (keeper_public,store_id,owner_seed):c.fixed(v)
        c.integer(revision,1,2**53-1)
        if type(timeout) not in (int,float) or not math.isfinite(timeout) or not .05<=timeout<=30:raise E('SUBMIT_INPUT')
        self.path=private_path(path);self.p=provider;self.kp=keeper_public;self.store=store_id;self._seed=owner_seed
        self.public=provider.sign_public(owner_seed);self.revision=revision;self.timeout=timeout
    def descriptor(self,payload,job_id,target):
        c.unpack_job(payload)
        return c.make_descriptor(self.p,self._seed,keeper=self.kp,store=self.store,revision=self.revision,job_id=job_id,target=target,size=len(payload),payload_hash=c.sha(payload))
    def call(self,action,descriptor=None,offset=None,data=None):
        # Validate before opening a socket, without weakening connection proof.
        b={0:1,1:c.PROFILE,2:bytes(32),3:action,4:descriptor,5:offset,6:data};c.request_shape(self.p,b)
        if descriptor is not None:
            d=c.check_descriptor(self.p,descriptor)
            if (d[2],d[3],d[4],d[9])!=(self.kp,self.store,self.public,self.revision):raise E('STALE_CONTROLLER')
        end=time.monotonic()+self.timeout;sent=False;s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        try:
            identity=socket_identity(self.path);s.settimeout(remaining(end));s.connect(str(self.path));peer_uid(s)
            if socket_identity(self.path)!=identity:raise E('SOCKET_IDENTITY')
            hi=receive(s,c.MAX_HELLO,end);h=c.check_hello(self.p,self.kp,self.store,self.public,self.revision,hi);end=min(end,time.monotonic()+h[8]/1000)
            req=c.make_request(self.p,self._seed,hi,action,descriptor,offset,data);sent=True
            send(s,req,c.MAX_REQUEST,end);raw=receive(s,c.MAX_RESPONSE,end);return c.check_response(self.p,self.kp,hi,req,raw)
        except E as exc:
            if sent and exc.code in ('DEADLINE','DISCONNECTED','REMOTE_UNCERTAIN'):raise E('OUTCOME_UNKNOWN') from None
            raise
        except OSError:raise E('OUTCOME_UNKNOWN' if sent else 'CONNECTION_UNAVAILABLE') from None
        finally:s.close()
    def stage(self,payload,descriptor):
        """Transfer/resume verified bytes only; submit remains an explicit call."""
        c.unpack_job(payload);d=c.check_descriptor(self.p,descriptor)
        if (len(payload),c.sha(payload))!=(d[7],d[8]):raise E('SUBMIT_HASH')
        progress=self.call('begin',descriptor)
        while progress['received']<len(payload):
            off=progress['received']
            if progress['prefix_hash']!=c.sha(payload[:off]).hex():raise E('SUBMIT_HASH')
            chunk=payload[off:off+c.CHUNK]
            progress=self.call('chunk',descriptor,off,chunk)
            if progress['received']!=off+len(chunk):raise E('SUBMIT_PROGRESS')
        if progress['prefix_hash']!=c.sha(payload).hex():raise E('SUBMIT_HASH')
        return progress
