#!/usr/bin/env python3
"""Public synthetic fixture only. No network, persistent user DB or real secrets."""
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True
for rel in ['experiments/space-auth','experiments/g0-wire','experiments/g0-crypto']:sys.path.insert(0,str(ROOT/rel))
from par_auth.chain import AuthorityState
from par_auth.errors import AuthError
from par_auth.replay import export_public_replay,restore_public_replay
from par_crypto.provider import SodiumProvider
from par_crypto.primitives import hashed

def main():
    c=json.loads((ROOT/'experiments/space-auth/fixtures/authority-candidate.json').read_text());p=SodiumProvider(json.loads((ROOT/'policy/crypto-provider.json').read_text()),allow_legacy_experiment=True)
    state=AuthorityState(p,c['app'],bytes.fromhex(c['space']),bytes.fromhex(c['genesis']));events=[]
    for x in c['controls']:
        state.observe(bytes.fromhex(x['raw']));events.append(state.status());state.provide_membership([bytes.fromhex(v) for v in x['pages']])
    a=c['activation'];state.activate(bytes.fromhex(a['certificate']),bytes.fromhex(a['recipient_secret_public_fixture']),bytes.fromhex(a['package']),[bytes.fromhex(x) for x in a['package_ids']],bytes.fromhex(a['manifest']),{bytes.fromhex(k):bytes.fromhex(v) for k,v in a['blocks'].items()})
    active=state.status();permit=state.authorize(bytes.fromhex(a['certificate']),'write');state.validate_permit(permit)
    raw=export_public_replay(state)
    restored=restore_public_replay(p,c['app'],state.space_id,state.head,hashed('auth-local/replay',[raw]),raw,minimum_sequence=4)
    try:state.observe(bytes.fromhex(c['fork']))
    except AuthError as e:
        if e.code!='CONTROL_FORK':raise
    if not state.frozen:raise RuntimeError('fork not detected')
    print(json.dumps({'classification':'PUBLIC_SYNTHETIC_TEST_ONLY','observed_states':events,'activated':active,'restored_requires_reactivation':restored.status(),'fork':state.status(),'store_commit_implemented':False,'automerge_applied':False,'independent_review':'NOT_RUN'},indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
