"""Pinned explicit client, one request per connection, no implicit retries."""
import socket,time
from par_job_submit.client import Client as RegistrationClient
from par_job_submit import protocol as s
from par_keeper_service.transport import socket_identity,peer_uid,remaining,receive,send
from . import protocol as c
class Client(RegistrationClient):
    def call(self,action,descriptor,authorization=None):
        q={0:1,1:c.PROFILE,2:bytes(32),3:action,4:descriptor,5:authorization};d=c.request_shape(self.p,q)
        if (d[2],d[3])!=(self.kp,self.store):raise c.E('RETIRE_CONTROL_TARGET')
        end=time.monotonic()+self.timeout;sent=False;sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        try:
            identity=socket_identity(self.path);sock.settimeout(remaining(end));sock.connect(str(self.path));peer_uid(sock)
            if socket_identity(self.path)!=identity:raise c.E('SOCKET_IDENTITY')
            hello=receive(sock,c.MAX_HELLO,end);h=s.check_hello(self.p,self.kp,self.store,self.public,self.revision,hello)
            end=min(end,time.monotonic()+h[8]/1000)
            req=c.make_request(self.p,self._seed,hello,action,descriptor,authorization);sent=True
            send(sock,req,c.MAX_REQUEST,end);raw=receive(sock,c.MAX_RESPONSE,end)
            result=c.check_response(self.p,self.kp,hello,req,raw)
            self.last_exchange={0:hello,1:req,2:raw}
            return result
        except c.E as exc:
            if sent and exc.code in ('DEADLINE','DISCONNECTED','REMOTE_UNCERTAIN'):raise c.E('OUTCOME_UNKNOWN') from None
            raise
        except OSError:raise c.E('OUTCOME_UNKNOWN' if sent else 'CONNECTION_UNAVAILABLE') from None
        finally:sock.close()
    def stage(self,*args,**kwargs):
        raise c.E('RETIRE_CONTROL_METHOD')
