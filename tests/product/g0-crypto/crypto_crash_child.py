"""Disposable subprocess fixture; kills only itself at a requested checkpoint."""
import os,signal,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
for p in [ROOT/'experiments/g0-crypto',ROOT/'experiments/g0-wire',ROOT/'experiments/g0-store',ROOT/'tests/product/g0-crypto']:sys.path.insert(0,str(p))
import json
from par_crypto.provider import SodiumProvider
from par_crypto.store_writer import CryptoStoreWriter
from par_store.store import Store
from test_crypto_objects import header,EPOCH,SIGN,PAYLOAD
p=SodiumProvider(json.loads((ROOT/'policy/crypto-provider.json').read_text()),allow_legacy_experiment=True)
def observe(stage):
    if stage==sys.argv[2]:
        print(stage,flush=True);os.kill(os.getpid(),signal.SIGKILL)
with Store.open(Path(sys.argv[1]),allow_unpatched_sqlite=True) as store:
    store.observer=observe
    CryptoStoreWriter(p,store,EPOCH,SIGN,b'L'*32,observer=observe).commit(b'1'*16,header(p),PAYLOAD,b'private materialized snapshot test fixture')
raise SystemExit('requested crash checkpoint was not reached')
