#!/usr/bin/env python3
"""Small disposable seven-scenario example. Not the 140-round measurement."""
import asyncio,json,sys,tempfile
from pathlib import Path
R=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True;sys.path.insert(0,str(R))
from tools.run_provider_soak import run_campaign
async def main():
    with tempfile.TemporaryDirectory(prefix='par-soak-demo-')as tmp:
        r=await run_campaign(Path(tmp)/'campaign',rounds=7,seed=54)
        print(json.dumps(r,indent=2));return 0 if r['result']=='PASS'else 1
if __name__=='__main__':raise SystemExit(asyncio.run(main()))
