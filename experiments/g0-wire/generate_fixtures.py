#!/usr/bin/env python3
"""Explicit fixture authoring, never invoked by verification. Review the diff before commit."""
from pathlib import Path
import argparse,hashlib,json,sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tests/product/g0-wire'))
sys.path.insert(0,str(ROOT/'experiments/g0-wire'))
from wire_support import BODIES,sample
from test_wire_interop import query,diagnostic
from par_wire.codec import encode

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--write',action='store_true');a=p.parse_args()
 if not a.write:p.error('explicit --write required; this changes reviewed fixtures/profile')
 answers=query([{'kind':'frame','op':'encode','value':diagnostic(sample(code))} for code in BODIES])
 frames=[]
 for code,answer in zip(BODIES,answers):
  if not answer['ok']:raise RuntimeError(answer)
  raw=bytes.fromhex(answer['hex']);frames.append({'id':f'GF-{code:03d}','message_code':code,'hex':raw.hex(),'sha256':hashlib.sha256(raw).hexdigest()})
 (ROOT/'experiments/g0-wire/fixtures/golden-frames.json').write_text(json.dumps({'schema_version':1,'assurance':'SAME_AUTHOR_SEPARATE_NODE_ENCODER; NOT EXTERNAL_ORACLE','frames':frames},indent=2)+'\n')
 inputs=['baseline/spec-00.02.00/protocol/par-v1.cddl','baseline/spec-00.02.00/protocol/registry.json','baseline/spec-00.02.00/protocol/limits.json','docs/decisions/ADR-WIRE-0001.ja.md','docs/decisions/ADR-WIRE-0002.ja.md']
 entries=[[rel,hashlib.sha256((ROOT/rel).read_bytes()).digest()] for rel in inputs]
 obj={'schema_version':1,'name':'par/1-draft-2+local-wire-00.04.00','inputs':inputs,'sha256':hashlib.sha256(encode(['PAR-EXPERIMENT-PROFILE',1,entries])).hexdigest(),'frozen':False,'production_qualified':False}
 (ROOT/'experiments/g0-wire/profile.json').write_text(json.dumps(obj,indent=2)+'\n')
 print('Wrote 26 Node-authored examples and candidate profile; review before use.')
if __name__=='__main__':main()
