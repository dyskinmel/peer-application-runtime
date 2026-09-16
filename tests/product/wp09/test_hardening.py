"""Reproducers for ownership gaps found in local self-review, not an audit."""
import asyncio,gc,socket,unittest,warnings,sys
from pathlib import Path
from unittest.mock import patch
from product.wp09 import par_connectivity as api
from fixtures import Resolver,Dialer,Authenticator,settled
from test_policy import grant,policy,PUBLIC

class HardeningTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):self.clients=[];self.sockets=[]
    async def asyncTearDown(self):
        for c in self.clients:await c.close();await c.wait_for_cleanup()
        for c,b in self.sockets:await c.close();b.close()
    def client(self):
        d=Dialer();c=api.Connector(policy(grant()),Resolver(),d,Authenticator(),'scope-A');self.clients.append(c);return c,d
    async def test_cancel_during_stage_watcher_cleanup_retires_returned_socket(self):
        c,d=self.client();original=asyncio.gather;fired=False
        async def injected(*tasks,**kw):
            nonlocal fired
            if not fired:
                fired=True
                # Real Task.cancel while a returned resource is between port and owner.
                asyncio.current_task().cancel()
            return await original(*tasks,**kw)
        with patch('product.wp09.par_connectivity.controller.asyncio.gather',new=injected):
            t=asyncio.create_task(c.connect((api.Candidate(PUBLIC,'peer-A'),)))
            with self.assertRaises(asyncio.CancelledError):await t
        self.assertTrue(fired);self.assertEqual(len(d.connections),1)
        await asyncio.sleep(0);await asyncio.sleep(0)
        self.assertEqual(d.connections[0].closed,1,'acquired connection leaked during watcher cleanup cancellation')
    async def test_pending_io_cancel_before_inner_task_start_does_not_leak_coroutine(self):
        # Process exit releases task/traceback cycles, so a late warning cannot
        # escape the capture as it could with an in-process warnings context.
        code = """import asyncio,sys,socket,gc
sys.path.insert(0,sys.argv[1])
from product.wp09.par_connectivity import SocketConnection,ConnectivityError
async def run():
 a,b=socket.socketpair();c=SocketConnection(a)
 t=asyncio.create_task(c.read_exact(1));await asyncio.sleep(0);await c.close()
 try:await t
 except ConnectivityError:pass
 b.close()
asyncio.run(run());gc.collect()
"""
        p=await asyncio.create_subprocess_exec(sys.executable,'-I','-S','-B','-W','always','-c',code,
             str(Path(__file__).resolve().parents[3]),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        out,err=await p.communicate()
        self.assertEqual(p.returncode,0,err.decode());self.assertNotIn(b'never awaited',err)
    async def test_cleanup_failed_resource_reference_is_retained(self):
        c,d=self.client();r=await c.connect((api.Candidate(PUBLIC,'peer-A'),));d.connections[0].close_error=True;await c.disconnect(r.connection_id)
        self.assertEqual(c.diagnostics().get('failed_resources'),1)
    async def test_cleanup_complete_does_not_mean_active_resources_are_gone(self):
        c,d=self.client();await c.connect((api.Candidate(PUBLIC,'peer-A'),));self.assertFalse(c.diagnostics()['cleanup_complete'])
    async def test_ipv4_dotted_hex_not_treated_as_dns(self):
        with self.assertRaises(api.ConnectivityError):api.parse_endpoint('tcp://0x7f.0x0.0x0.0x1:443')
    async def test_dns_name_ip_spelling_confusion_never_reaches_resolver(self):
        with self.assertRaises(api.ConnectivityError):api.Candidate('tcp://0x7f.0.0.0x1:443','peer-A')
