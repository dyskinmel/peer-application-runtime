"""Pinned one-shot owner client. Mutations require an explicit stable operation ID."""
import secrets,socket,time,math
from par_keeper_service.transport import private_path,socket_identity,peer_uid,remaining,receive,send
from . import protocol as c
E=c.E
class Client:
    def __init__(self,path,provider,keeper_public,store_id,owner_seed,revision,*,timeout=5):
        for v in (keeper_public,store_id,owner_seed):c.fixed(v)
        c.integer(revision,1,2**53-1)
        if type(timeout) not in (int,float) or not math.isfinite(timeout) or not .05<=timeout<=30:raise E('CONTROL_INPUT')
        self.path=private_path(path);self.p=provider;self.kp=keeper_public;self.store=store_id;self._seed=owner_seed
        self.public=provider.sign_public(owner_seed);self.revision=revision;self.timeout=timeout
    def intent(self,action,job_id=None,operation_id=None):
        if operation_id is None:
            if action!='status':raise E('OPERATION_ID_REQUIRED')
            operation_id=secrets.token_bytes(32)
        return c.make_intent(self.p,self._seed,keeper=self.kp,store=self.store,revision=self.revision,operation_id=operation_id,action=action,job_id=job_id)
    def call(self,action,job_id=None,operation_id=None):return self.request(self.intent(action,job_id,operation_id))
    def request(self,intent):
        c.check_intent(self.p,self.kp,self.store,self.public,self.revision,intent)
        deadline=time.monotonic()+self.timeout;sent=False;s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        try:
            identity=socket_identity(self.path);s.settimeout(remaining(deadline));s.connect(str(self.path));peer_uid(s)
            if socket_identity(self.path)!=identity:raise E('SOCKET_IDENTITY')
            hello=receive(s,c.MAX_HELLO,deadline)
            body=c.check_hello(self.p,self.kp,self.store,self.public,self.revision,hello)
            deadline=min(deadline,time.monotonic()+body[8]/1000)
            request=c.make_request(self.p,self._seed,hello,intent);sent=True
            send(s,request,c.MAX_REQUEST,deadline);response=receive(s,c.MAX_RESPONSE,deadline)
            return c.check_response(self.p,self.kp,hello,request,response)
        except E as exc:
            if sent and exc.code in ('DEADLINE','DISCONNECTED','REMOTE_CONTROL_UNCERTAIN'):raise E('OUTCOME_UNKNOWN') from None
            raise
        except OSError:raise E('OUTCOME_UNKNOWN' if sent else 'CONNECTION_UNAVAILABLE') from None
        finally:s.close()
