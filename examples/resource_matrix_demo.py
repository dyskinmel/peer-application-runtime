#!/usr/bin/env python3
"""Short private two-owner matrix demonstration, not a public network test."""
from pathlib import Path
import asyncio,json,sys,tempfile
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
from tools.run_resource_matrix import run_campaign
async def main():
    with tempfile.TemporaryDirectory(prefix='par-matrix-demo-')as tmp:
        r=await run_campaign(Path(tmp)/'campaign',cells=[{'participants':2,'max_active':2,'rounds_per_peer':1}])
        summary={'result':r['result'],'source':r['binding']['source'],'cells':[{k:c[k]for k in('participants','max_active','peak_active','queue_full_rejections','other_progress_before_slow_cancel','readonly_unchanged','child_exit_codes','violations')}for c in r['cells']],'product_qualified':False}
        print(json.dumps(summary,indent=2));return 0 if r['result']=='PASS'else 1
if __name__=='__main__':raise SystemExit(asyncio.run(main()))
