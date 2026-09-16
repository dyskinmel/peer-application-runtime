import sys,time,json,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.dont_write_bytecode=True
for p in [ROOT,Path(__file__).parent,ROOT/'tests/product/auth-store',ROOT/'tests/product/space-auth']+[p for p in (ROOT/'experiments').iterdir() if p.is_dir()]:sys.path.insert(0,str(p))
from process_fixture import Peer,h
from product.wp04.exchange import Server,Client,transfer_one
from par_crypto import objects
mode,root,sock,marker=sys.argv[1:];marker=Path(marker)
pin=json.loads(marker.read_text())['pin'] if mode=='finish' else None
p=Peer(root,expected_pin=pin);server=None
try:
 if mode=='serve':
  for pair in p.chain():p.box.receive(*pair)
  server=Server(p.source,Path(sock));marker.write_text(json.dumps({'pid':os.getpid(),'identity':server.endpoint.identity}))
  while True:server.poll(.01)
 else:
  d=p.s.devices[1];client=Client(Path(sock),p.p,p.source.public,p.source.scope,d['cert'],d['seed'])
  target=h('inner:b') if mode=='partial' else h('inner:a')
  r=client.need([target]);receipt=transfer_one(client,p.box,r[0],r[1][0][1])
  if mode=='partial':
   marker.write_text(json.dumps({'pin':p.box.pin(),'receipt':receipt}))
   while True:time.sleep(.05)
  else:
   b=p.chain()[1];print(json.dumps({'pid':os.getpid(),'usage':p.box.usage(),'view':p.box.inspect(objects.envelope_id(b[0])),'core':p.box.validate(objects.envelope_id(b[0]))}),flush=True)
finally:
 if server:server.close()
 p.close()
