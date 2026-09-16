"""Ephemeral PUBLIC TEST PKI only; no enrolled user secrets or network listener."""
from pathlib import Path
import asyncio, hashlib, importlib, importlib.util, os, socket, ssl, subprocess, tempfile

class TestPKI:
    def __init__(self):
        self.temp = tempfile.TemporaryDirectory(prefix='par-test-pki-')
        self.path = Path(self.temp.name)
        self._run('req','-x509','-newkey','ec','-pkeyopt','ec_paramgen_curve:P-256',
                  '-nodes','-keyout','ca.key','-out','ca.pem','-days','2','-subj','/CN=PAR TEST ONLY',
                  '-addext','basicConstraints=critical,CA:TRUE',
                  '-addext','keyUsage=critical,keyCertSign,cRLSign')
        for name,host,usage,days in [('server','server.test','serverAuth',1),('client','client.test','clientAuth',1),
                                     ('other','server.test','serverAuth,clientAuth',1),('expired','server.test','serverAuth',-1)]:
            self._run('req','-new','-newkey','ec','-pkeyopt','ec_paramgen_curve:P-256',
                      '-nodes','-keyout',name+'.key','-out',name+'.csr','-subj','/CN='+host)
            (self.path/(name+'.ext')).write_text('basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage='+usage+'\nsubjectAltName=DNS:'+host+'\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\n')
            if days < 0:
                (self.path/'index.txt').write_text('');(self.path/'serial').write_text('10\n')
                (self.path/'ca.cnf').write_text('[ca]\ndefault_ca=issuer\n[issuer]\ndatabase=index.txt\nserial=serial\nnew_certs_dir=.\ncertificate=ca.pem\nprivate_key=ca.key\ndefault_md=sha256\ndefault_days=1\npolicy=policy\n[policy]\ncommonName=supplied\n')
                self._run('ca','-batch','-config','ca.cnf','-in',name+'.csr','-out',name+'.pem',
                          '-startdate','20000101000000Z','-enddate','20010101000000Z','-extfile',name+'.ext','-notext')
            else:
                self._run('x509','-req','-in',name+'.csr','-CA','ca.pem','-CAkey','ca.key',
                          '-set_serial',str({'server':2,'client':3,'other':4}[name]),'-days',str(days),
                          '-extfile',name+'.ext','-out',name+'.pem')
        for key in self.path.glob('*.key'): key.chmod(0o600)
    def _run(self,*args):
        p=subprocess.run(['openssl',*args],cwd=self.path,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10)
        if p.returncode: raise RuntimeError('TEST_PKI_SETUP_FAILED: '+p.stderr.decode())
    def pin(self,name):
        return hashlib.sha256(ssl.PEM_cert_to_DER_cert((self.path/(name+'.pem')).read_text())).hexdigest()
    def config(self,module,side,**overrides):
        args=dict(server_side=side,ca_file=self.path/'ca.pem',cert_file=self.path/('server.pem' if side else 'client.pem'),
                  key_file=self.path/('server.key' if side else 'client.key'),
                  peer_sha256=self.pin('client' if side else 'server'),server_hostname=None if side else 'server.test')
        args.update(overrides)
        return module.TLSConfig(**args)
    def close(self): self.temp.cleanup()

class API:
    @classmethod
    def setUpClass(cls):
        cls.pki=TestPKI()
    @classmethod
    def tearDownClass(cls): cls.pki.close()
    def load(self):
        self.assertIsNotNone(importlib.util.find_spec('product.wp09.par_secure_transport'),
                             'standard TLS transport implementation missing')
        self.m=importlib.import_module('product.wp09.par_secure_transport')
    async def pair(self,*,server=None,client=None,limits=None):
        a,b=socket.socketpair(); self.raw.extend((a,b))
        rows=await asyncio.gather(
            self.m.TLSStream.open(a,server or self.pki.config(self.m,True),limits=limits),
            self.m.TLSStream.open(b,client or self.pki.config(self.m,False),limits=limits),return_exceptions=True)
        for r in rows:
            if not isinstance(r,BaseException):self.streams.append(r)
        return rows
    async def good_pair(self,**kw):
        rows=await self.pair(**kw)
        for r in rows:
            if isinstance(r,BaseException):raise r
        return rows
    async def cleanup(self):
        await asyncio.gather(*(s.close() for s in self.streams),return_exceptions=True)
        for s in self.raw:s.close()
