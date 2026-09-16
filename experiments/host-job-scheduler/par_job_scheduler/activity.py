"""Owner-only admission and measured selector activity; never a cached zero."""
from __future__ import annotations
import os
import selectors
import threading
from par_keeper_service.server import Server as ReadServer
from par_window_host.server import Server as UploadServer
from par_keeper_service.transport import socket_identity
from par_management_jobs.contract import E

class Admission:
    """Mixin: only listener monitoring changes; existing wire and guards remain."""
    def __init__(self,*args,**kwargs):
        self._pid=os.getpid();self.accepting=True
        super().__init__(*args,**kwargs)
    def _owner(self):
        if self._pid!=os.getpid():raise E('SCHEDULER_OWNER')
        super()._owner()
    def pause_accepting(self):
        self._owner()
        if self.accepting:
            key=self.selector.get_key(self.endpoint.socket)
            if key.data is not None:raise E('ACTIVITY_MISMATCH')
            self.selector.unregister(self.endpoint.socket);self.accepting=False
    def resume_accepting(self):
        self._owner()
        if not self.accepting:
            if socket_identity(self.endpoint.path)!=self.endpoint.identity:raise E('ENDPOINT_CHANGED')
            self.selector.register(self.endpoint.socket,selectors.EVENT_READ,None);self.accepting=True
    def _accept(self):
        # Covers a stale ready notification as well as accidental direct calls.
        self._owner()
        if self.accepting:super()._accept()
    def close(self):
        if getattr(self,'closed',False):return
        if self._pid!=os.getpid() or getattr(self,'_thread',threading.get_ident())!=threading.get_ident():raise E('SCHEDULER_OWNER')
        super().close()

class ScheduledRead(Admission,ReadServer):pass
class ScheduledUpload(Admission,UploadServer):pass

class BoundActivity:
    """Two concrete endpoints bound to a keeper, not a caller supplied counter."""
    def __init__(self,keeper,read,upload):
        if type(read) is not ScheduledRead or type(upload) is not ScheduledUpload or read is upload:raise E('ACTIVITY_BINDING')
        if read.keeper is not keeper or upload.keeper is not keeper:raise E('ACTIVITY_BINDING')
        self.keeper=keeper;self.servers=(read,upload);self.owner=(os.getpid(),threading.get_ident())
    def guard(self):
        if self.owner!=(os.getpid(),threading.get_ident()):raise E('SCHEDULER_OWNER')
        if self.keeper._closed:raise E('CLOSED')
    def snapshot(self):
        self.guard();counts=[];sending=0;receiving=0
        for server in self.servers:
            server._owner()
            if server.keeper is not self.keeper:raise E('ACTIVITY_BINDING')
            mapping=server.selector.get_map()
            if mapping is None:raise E('ACTIVITY_MISMATCH')
            endpoint_fd=server.endpoint.socket.fileno();expected=set(server.connections)
            if server.accepting:expected.add(endpoint_fd)
            if set(mapping)!=expected:raise E('ACTIVITY_MISMATCH')
            if server.accepting:
                listener=mapping[endpoint_fd]
                if listener.fileobj is not server.endpoint.socket or listener.data is not None or listener.events!=selectors.EVENT_READ:raise E('ACTIVITY_MISMATCH')
            for fd,c in server.connections.items():
                key=mapping[fd]
                if fd<0 or c.socket.fileno()!=fd or key.fileobj is not c.socket or key.data is not c:raise E('ACTIVITY_MISMATCH')
                if c.phase not in ('hello','request','response'):raise E('ACTIVITY_MISMATCH')
                if key.events!=(selectors.EVENT_READ if c.phase=='request' else selectors.EVENT_WRITE):raise E('ACTIVITY_MISMATCH')
                sending+=int(c.phase=='response');receiving+=int(c.phase=='request')
            counts.append(len(server.connections))
        if type(self.keeper._pins) is not dict:raise E('ACTIVITY_MISMATCH')
        return {'read_connections':counts[0],'upload_connections':counts[1],
                'connections':sum(counts),'reader_pins':len(self.keeper._pins),
                'sending_responses':sending,'receiving_requests':receiving,
                'read_accepting':self.servers[0].accepting,'upload_accepting':self.servers[1].accepting,
                'backlog_included':False}
    def for_job(self):
        value=self.snapshot()
        if value['read_accepting'] or value['upload_accepting']:raise E('ADMISSION_NOT_PAUSED')
        return value['connections']
