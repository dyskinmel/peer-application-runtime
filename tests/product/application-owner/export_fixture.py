from pathlib import Path
import sys,json,asyncio
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R))
from tools import check_application_intent
sys.path.insert(0,str(R/'tests/product/application-owner'))
from test_application_owner import ApplicationOwnerTests
async def main():
 t=ApplicationOwnerTests();await t.asyncSetUp()
 try:
  f=t.f;f.simulate();data={'empty':t.s,'context':t.o.context(t.ch),'targets':[f.target.hex()]}
  data['prepared']=await t.prepare();data['observed']=await t.action('dispatch');data['inquired']=await t.action('inquire');data['retired']=await t.action('retire')
  print(json.dumps(data))
 finally:await t.o.close();t.doCleanups()
asyncio.run(main())
