#!/usr/bin/env python3
"""Disposable synthetic data only. No real key files or user database accepted."""
from pathlib import Path
import sys,json,tempfile
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True
for rel in ('','experiments/g0-crypto','experiments/g0-wire','experiments/g0-store'):sys.path.insert(0,str(ROOT/rel))
from harness.common import read_json
from par_crypto.provider import SodiumProvider
from par_crypto.primitives import random_bytes,hashed
from par_crypto.objects import create_certificate,verify_certificate,certificate_id,seal_package,package_id,package_root,open_package
from par_crypto.store_writer import CryptoStoreWriter
from par_store.store import Store
from par_store.recovery import restore_snapshot

def main():
    p=SodiumProvider(read_json(ROOT/'policy/crypto-provider.json'),allow_legacy_experiment=True)
    app='org.example.notes';epoch,seed,local,account,authority,recipient=[random_bytes(32) for _ in range(6)]
    device=hashed('device-id',[app,p.sign_public(seed)]);space=random_bytes(32);control=random_bytes(32)
    cert=create_certificate(p,account,app,p.sign_public(seed),p.dh_public(recipient),random_bytes(16))
    verify_certificate(p,app,p.sign_public(account),cert)
    context={0:app,1:space,2:1,3:random_bytes(16),4:device,5:certificate_id(cert),6:random_bytes(32)}
    package=seal_package(p,authority,p.dh_public(recipient),context,epoch);ids=[package_id(package)];root=package_root(ids)
    recovered_epoch=open_package(p,recipient,p.sign_public(authority),context,package,ids,root)
    assert recovered_epoch==epoch
    payload='synthetic payload, not an Automerge document: 音楽'.encode();cache=b'synthetic local cache'
    h={0:app,1:space,2:1,3:random_bytes(32),4:1,5:device,6:random_bytes(16),7:1,8:None,
       9:random_bytes(32),10:[],11:len(payload),12:random_bytes(32),13:control,14:1,15:0};op=random_bytes(16)
    with tempfile.TemporaryDirectory(prefix='par-crypto-demo-') as d:
        d=Path(d)
        with Store.create(d/'store',allow_unpatched_sqlite=True) as store:
            store.configure_space(space,app,1,control);w=CryptoStoreWriter(p,store,epoch,seed,local)
            first=w.commit(op,h,payload,cache);second=w.commit(op,h,payload,cache)
            assert first==second;assert store.audit()['valid']
            issued=store.connection.execute('SELECT count(*) FROM issued_nonces').fetchone()[0]
            store.export_snapshot(d/'snapshot')
        restore_snapshot(d/'snapshot',d/'restored',allow_unpatched_sqlite=True)
        with Store.open(d/'restored',allow_unpatched_sqlite=True) as restored:
            r=CryptoStoreWriter(p,restored,epoch,seed,local).read_committed(op,h,payload,cache)
            assert r==first and restored.restore_read_only
    print(json.dumps({'result':'PASS','scope':'DISPOSABLE_SYNTHETIC_CRYPTO_STORE_DEMO',
        'saved_retry_equal':True,'issued_nonces':issued,'restored_receipt_verified':True,'restore_write_enabled':False,
        'epoch_package_decrypted':True,'membership_chain_verified':False,'automerge_verified':False,
        'production_qualified':False,'legacy_sodium_experiment':p.identity['legacy_experiment']},indent=2))
if __name__=='__main__':main()
