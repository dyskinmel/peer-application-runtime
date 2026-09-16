import socket,time,os
from dataclasses import replace
from service_support import ServiceTest,h
from par_keeper import issue_capability

class ServiceLifecycle(ServiceTest):
    def test_local_get_signed_response(self):
        self.start_local();c,hello=self.connect_local();oid=min(self.bundle.objects,key=lambda x:len(self.bundle.objects[x]));q=self.request_raw(hello,payload=oid)
        c.sendall(self.ipc.frame(q,self.ipc.MAX_REQUEST));self.pump()
        raw=self.ipc.receive(c,self.ipc.MAX_RESPONSE,time.monotonic()+1)
        self.assertEqual(self.ipc.check_response(self.p,self.kp,hello,q,raw),self.bundle.objects[oid])
        self.assertEqual(c.recv(1),b'')
    def test_get_keeps_pin_until_response_closes(self):
        self.start_local(send_chunk=1);c,hello=self.connect_local_chunked();q=self.request_raw(hello)
        c.sendall(self.ipc.frame(q,self.ipc.MAX_REQUEST))
        for _ in range(5):self.server.poll(.01)
        self.assertEqual(len(self.keeper._pins),1)
        self.err('PINNED',lambda:self.keeper.mark_repair(self.lid,self.cap,self.repair_request(self.lid)))
        self.release(self.lid);self.err('PINNED',lambda:self.keeper.mark(self.lid,self.cap,self.gc_request(self.lid)))
        self.server.poll(.01);self.assertEqual(len(self.keeper._pins),0)
    def connect_local_chunked(self):
        # Tiny chunks apply only to response, not the compact signed greeting.
        return self.connect_local()
    def test_disconnect_releases_reader_pin(self):
        self.start_local(send_chunk=1);c,hello=self.connect_local();q=self.request_raw(hello);c.sendall(self.ipc.frame(q,self.ipc.MAX_REQUEST))
        for _ in range(4):self.server.poll(.01)
        self.assertEqual(len(self.keeper._pins),1);c.close();self.pump()
        self.assertEqual(len(self.keeper._pins),0)
    def test_authority_change_drops_pending_response(self):
        self.start_local(send_chunk=1);c,hello=self.connect_local();q=self.request_raw(hello);c.sendall(self.ipc.frame(q,self.ipc.MAX_REQUEST))
        for _ in range(4):self.server.poll(.01)
        self.keeper.update_authority(replace(self.authority,head=h('next'),sequence=2));self.pump()
        self.assertEqual(self.server.diagnostics()['active_connections'],0);self.assertEqual(len(self.keeper._pins),0)
    def test_released_lease_get_denied(self):
        self.start_local();self.release(self.lid);c,hello=self.connect_local();q=self.request_raw(hello);c.sendall(self.ipc.frame(q,self.ipc.MAX_REQUEST));self.pump()
        raw=self.ipc.receive(c,self.ipc.MAX_RESPONSE,time.monotonic()+1)
        self.err('REMOTE_UNAVAILABLE',lambda:self.ipc.check_response(self.p,self.kp,hello,q,raw))
    def test_current_authority_rejects_old_capability(self):
        self.start_local();self.keeper.update_authority(replace(self.authority,head=h('next'),sequence=2));c,hello=self.connect_local();q=self.request_raw(hello);c.sendall(self.ipc.frame(q,self.ipc.MAX_REQUEST));self.pump()
        raw=self.ipc.receive(c,self.ipc.MAX_RESPONSE,time.monotonic()+1)
        self.err('REMOTE_REQUEST_REJECTED',lambda:self.ipc.check_response(self.p,self.kp,hello,q,raw))
    def test_corrupt_get_not_returned(self):
        self.start_local();oid=sorted(self.bundle.objects)[0];self.damage(self.lid,'corrupt',oid)
        c,hello=self.connect_local();q=self.request_raw(hello,payload=oid);c.sendall(self.ipc.frame(q,self.ipc.MAX_REQUEST));self.pump()
        raw=self.ipc.receive(c,self.ipc.MAX_RESPONSE,time.monotonic()+1)
        self.err('REMOTE_DATA_INVALID',lambda:self.ipc.check_response(self.p,self.kp,hello,q,raw))
    def test_process_get(self):
        self.start_process();oid=sorted(self.bundle.objects)[0]
        self.assertEqual(self.client.fetch(self.lid,oid),self.bundle.objects[oid])
    def test_process_status_not_all_leases(self):
        self.start_process();v=self.client.status(self.lid)
        self.assertEqual(v['expected'],len(self.bundle.objects));self.assertFalse(v['product_qualified']);self.assertNotIn('leases',v)
    def test_process_receipt_matches_preexisting(self):
        lid,rc=self.ready();self.lid=lid;self.start_process(existing=True)
        self.assertEqual(self.client.receipt(lid),rc)
    def test_process_challenge_nonce(self):
        from par_keeper.contract import split
        self.start_process();nonce=h('challenge');raw=self.client.challenge(self.lid,nonce);v,_=split(raw)
        self.assertEqual(v[4],nonce);self.assertFalse(v[8])
    def test_process_wrong_pinned_key(self):
        self.start_process();client=self.ipc.Client(self.socket_path,self.p,h('wrong-key'),self.cs,self.cap)
        self.err('HELLO_AUTH',lambda:client.status(self.lid))
    def test_process_no_read_method_permission(self):
        self.start_process()
        cap=issue_capability(self.p,self.s.owner,self.authority,self.kp,self.cp,self.rpin.index_id,('status',),60,h('status-only'))
        client=self.ipc.Client(self.socket_path,self.p,self.kp,self.cs,cap)
        self.assertFalse(client.status(self.lid)['product_qualified'])
        self.err('REMOTE_REQUEST_REJECTED',lambda:client.fetch(self.lid,sorted(self.bundle.objects)[0]))
    def test_endpoint_mode_is_private(self):
        self.start_process();self.assertEqual(self.socket_path.stat().st_mode&0o777,0o600)
    def test_clean_shutdown_unlinks_endpoint(self):
        self.start_process();rc,_,err=self.stop_process();self.assertEqual(rc,0);self.assertFalse(self.socket_path.exists());self.assertEqual(err,'')
    def test_close_is_idempotent_and_releases_pin(self):
        self.start_local();self.server.close();self.server.close();self.assertFalse(self.socket_path.exists())
    def test_private_directory_required(self):
        self.socket_dir.chmod(0o755);self.err('SOCKET_PERMISSIONS',lambda:self.ipc.socket_identity(self.socket_path))
    def test_existing_regular_file_never_deleted(self):
        self.lid,_=self.ready();self.socket_path.write_bytes(b'keep')
        self.err('SOCKET_EXISTS',lambda:self.ipc.Server(self.keeper,self.socket_path));self.assertEqual(self.socket_path.read_bytes(),b'keep')
    def test_symlink_endpoint_refused(self):
        target=self.socket_dir/'target';target.write_bytes(b'keep');self.socket_path.symlink_to(target)
        self.err('SOCKET_PATH',lambda:self.ipc.socket_identity(self.socket_path));self.assertEqual(target.read_bytes(),b'keep')
    def test_symlink_parent_refused(self):
        link=self.socket_dir.parent/'link';link.symlink_to(self.socket_dir,target_is_directory=True)
        self.err('SOCKET_PATH',lambda:self.ipc.socket_identity(link/'keeper.sock'))
    def test_abstract_and_relative_addresses_refused(self):
        self.err('SOCKET_PATH',lambda:self.ipc.socket_identity('\0service'))
        self.err('SOCKET_PATH',lambda:self.ipc.socket_identity('service.sock'))
    def test_server_unknown_option_not_implicit_dispatch(self):
        self.start_local();self.assertEqual(self.ipc.METHODS,frozenset(('get','status','receipt','challenge')))
    def test_child_inherits_harness_process_group(self):
        self.start_process();self.assertEqual(os.getpgid(self.process.pid),os.getpgrp())
