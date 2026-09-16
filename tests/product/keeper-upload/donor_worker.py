"""Separate donor, supplied public synthetic key material only."""
import sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'tools'));sys.dont_write_bytecode=True
import keeper_upload_host
from par_crypto.provider import SodiumProvider
from par_keeper.contract import pin_from
from par_wire.codec import decode
from par_keeper_upload.client import Client
from par_crypto.primitives import hashed

def main():
    j=json.loads(Path(sys.argv[1]).read_text());b=lambda k:bytes.fromhex(j[k])
    p=SodiumProvider(json.loads((ROOT/'policy/crypto-provider.json').read_text()),allow_legacy_experiment=True)
    c=Client(Path(j['socket']),p,b('keeper'),b('seed'),b('cap'))
    lid,receipt=c.upload_bundle(b('index'),pin_from(decode(b('pin'))),{bytes.fromhex(k):bytes.fromhex(v) for k,v in j['objects'].items()},30,hashed('test/upload',[b('index')]))
    print(json.dumps({'lease':lid.hex(),'receipt':receipt.hex(),'product_qualified':False}))
if __name__=='__main__':main()
