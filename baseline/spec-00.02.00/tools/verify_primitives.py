#!/usr/bin/env python3
"""Verify two PUBLIC primitive KATs. This does not verify the PAR crypto protocol."""
import argparse,hashlib,hmac,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def run():
    try:
        import cryptography
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
        from cryptography.exceptions import InvalidSignature
    except ImportError:
        return {'scope':'PUBLIC_PRIMITIVE_KATS_ONLY','result':'BLOCKED','reason':'cryptography not installed','checks':[]}
    f=json.loads((ROOT/'fixtures/primitive-kats.json').read_text());x=f['ed25519'];hx=bytes.fromhex
    key=Ed25519PrivateKey.from_private_bytes(hx(x['secret_seed_hex']));pk=key.public_key();signature=key.sign(hx(x['message_hex']))
    checks=[{'name':'Ed25519 public key RFC8032 test1','pass':pk.public_bytes(Encoding.Raw,PublicFormat.Raw)==hx(x['public_key_hex'])},{'name':'Ed25519 signature RFC8032 test1','pass':signature==hx(x['signature_hex'])}]
    try:pk.verify(hx(x['signature_hex']),hx(x['message_hex']));verified=True
    except InvalidSignature:verified=False
    checks.append({'name':'Ed25519 verify RFC8032 test1','pass':verified})
    bad=bytearray(signature);bad[0]^=1
    try:pk.verify(bytes(bad),hx(x['message_hex']));rejected=False
    except InvalidSignature:rejected=True
    checks.append({'name':'Ed25519 altered signature rejected','pass':rejected})
    x=f['hkdf_sha256'];prk=hmac.new(hx(x['salt_hex']),hx(x['ikm_hex']),hashlib.sha256).digest();out=b'';last=b''
    for i in range(1,(x['length']+31)//32+1):
        last=hmac.new(prk,last+hx(x['info_hex'])+bytes([i]),hashlib.sha256).digest();out+=last
    checks += [{'name':'HKDF extract RFC5869 A.1','pass':prk==hx(x['prk_hex'])},{'name':'HKDF expand RFC5869 A.1','pass':out[:x['length']]==hx(x['okm_hex'])}]
    return {'scope':'PUBLIC_PRIMITIVE_KATS_ONLY','result':'PASS' if all(c['pass'] for c in checks) else 'FAIL','cryptography_version':cryptography.__version__,'checks':checks,'not_tested':['HPKE','XChaCha20-Poly1305','PAR domain separation integration','PAR authorization','strict cross-library Ed25519 edge cases']}
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--report',type=Path);a=p.parse_args()
    try:r=run()
    except Exception as exc:r={'scope':'PUBLIC_PRIMITIVE_KATS_ONLY','result':'FAIL','error':str(exc)}
    s=json.dumps(r,indent=2);print(s)
    if a.report:a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(s+'\n')
    return 0 if r['result']=='PASS' else 2 if r['result']=='BLOCKED' else 1
if __name__=='__main__':sys.exit(main())
