#!/usr/bin/env python3
"""Offline Chromium + live test-only owned SQLite bridge; NOT production HTTP/IPC.
Browser plugin is not listed in this environment. No browser policies modified.
"""
from __future__ import annotations
import argparse,asyncio,json,re,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
from tools.check_reference_browser import module_url
async def run(out):
 from playwright.async_api import async_playwright
 out.mkdir(parents=True,exist_ok=True);cases=[];errors=[]
 worker=await asyncio.create_subprocess_exec(sys.executable,'-I','-S','-B',str(ROOT/'tests/product/runtime-binding/owner_worker.py'),stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
 async def call(action,operation_id=None):
  worker.stdin.write((json.dumps({'action':action,'operationId':operation_id})+'\n').encode());await worker.stdin.drain()
  line=await asyncio.wait_for(worker.stdout.readline(),15);r=json.loads(line)
  if 'error'in r:raise RuntimeError(r['error'])
  return r
 try:
  first=await call('inspect');cache={};binding=module_url(ROOT/'product/wp11/lib/runtime-binding.js',cache);renderer=module_url(ROOT/'product/wp11/lib/renderer.js',cache)
  html='<!doctype html><html lang="ja"><head><title>PAR · Store observation</title></head><body><main id="reference-root"></main></body></html>'
  async with async_playwright() as p:
   browser=await p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
   page=await browser.new_page(viewport={'width':1400,'height':1000});page.set_default_timeout(5000)
   page.on('pageerror',lambda e:errors.append(str(e)));page.on('console',lambda m:errors.append(m.text) if m.type=='error' else None)
   await page.expose_function('ownerInspect',lambda op:call('inspect',op))
   await page.set_content(html);await page.add_style_tag(content=(ROOT/'product/wp11/app/style.css').read_text())
   await page.evaluate('''async ({b,r,first})=>{const {RuntimeBinding}=await import(b);const {mountReference}=await import(r);window.binding=new RuntimeBinding({scope:first.scope,deviceId:first.deviceId,storeGeneration:first.storeGeneration,streamId:first.streamId},first,{observe:ownerInspect,inspectOperation:ownerInspect});window.view=mountReference(document.querySelector('main'),binding.current,{effectPort:i=>binding.execute(i)});window.editor=document.querySelector('textarea');}''',{'b':binding,'r':renderer,'first':first})
   async def test(name,fn):
    try:await fn();cases.append({'id':'runtime.browser.'+name,'status':'PASS'})
    except Exception as e:
     cases.append({'id':'runtime.browser.'+name,'status':'FAIL','error':str(e)});await page.screenshot(path=str(out/('failure-'+name+'.png')),full_page=True)
   async def identity():
    assert await page.title()=='PAR · Store observation';assert await page.locator('textarea').count()==1;assert await page.locator('[data-command=inspect-operation]').is_enabled()
   await test('identity_inspect_available',identity)
   async def unknown():
    assert await page.evaluate('binding.current.local.state')=='unknown';assert '結果を確認' in await page.locator('main').inner_text()
    assert await page.evaluate('binding.current.connection.state')=='unknown'
   await test('unobserved_not_disconnected_or_failed',unknown)
   async def commit_query():
    await call('commit-fixture');await page.locator('[data-command=inspect-operation]').click();await page.wait_for_function("binding.current.local.state==='committed'");assert 'この端末に保存済み' in await page.locator('main').inner_text();assert 'Storeの保存結果を照合' in await page.locator('[data-test=effect-result]').inner_text()
   await test('live_commit_then_user_inquiry',commit_query)
   async def unchanged_body():
    assert await page.locator('textarea').input_value()=='';assert not await page.evaluate('binding.current.document.applied');assert 'opaque inner' not in await page.locator('main').inner_text()
   await test('no_unverified_body_or_crdt_promotion',unchanged_body)
   async def no_write():
    assert await page.locator('[data-command=export]').is_disabled();assert await page.locator('[data-test=private-save]').is_disabled();assert not await page.evaluate('binding.current.authority.sharedWriteAllowed');assert await page.evaluate('binding.current.protection.observations.length')==0;assert 'reason.unsupported' not in await page.locator('main').inner_text();assert '他端末での保管は未確認' in await page.locator('main').inner_text()
   await test('no_write_or_replication_claim',no_write)
   async def composition():
    await page.locator('textarea').fill('未共有の下書き😀');await page.evaluate("editor.setSelectionRange(2,4);editor.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));")
    await call('authority-update');await page.evaluate('async()=>view.update(await binding.refresh())');assert await page.locator('textarea').input_value()=='未共有の下書き😀';assert await page.evaluate('view.getDraft().composing');assert await page.evaluate('editor===document.querySelector("textarea")');assert await page.evaluate('editor.selectionStart')==2
   await test('live_authority_update_keeps_composition',composition)
   async def locale():
    await page.evaluate("view.setLocale('en')");assert await page.locator('textarea').input_value()=='未共有の下書き😀';assert 'Connection state has not been observed' in await page.locator('main').inner_text();await page.evaluate("view.setLocale('ja')")
   await test('locale_keeps_live_view_and_draft',locale)
   async def details():
    await page.get_by_role('button',name='状態の詳細',exact=True).click();txt=await page.locator('.par-details').inner_text();assert 'authenticated-local-store' in txt;assert 'crdtApplied' in txt;await page.get_by_role('button',name='状態の詳細',exact=True).click()
   await test('provenance_visible',details)
   async def desktop():
    assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth');await page.screenshot(path=str(out/'desktop.png'),full_page=True)
   await test('desktop_layout',desktop)
   async def mobile():
    await page.set_viewport_size({'width':390,'height':844});assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth');await page.screenshot(path=str(out/'mobile.png'),full_page=True)
   await test('mobile_layout',mobile)
   async def rtl():
    await page.evaluate("document.body.dir='rtl'");assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth');await page.evaluate("document.body.dir='ltr'")
   await test('rtl_layout',rtl)
   async def closed():
    await page.evaluate('binding.close()');assert await page.evaluate("binding.refresh().then(()=>false,e=>e.code==='RUNTIME_CLOSED')")
   await test('closed_port_refuses_refresh',closed)
   await browser.close()
 finally:
  worker.stdin.close()
  try:await asyncio.wait_for(worker.wait(),10)
  except asyncio.TimeoutError:worker.kill();await worker.wait()
 result={'scope':'OFFLINE_CHROMIUM_LIVE_SYNTHETIC_SQLITE_TEST_BRIDGE_ONLY','http_origin_tested':False,'indexeddb_tested':False,'browser_plugin':'not listed; Playwright fallback','cases':cases,'console_errors':errors,'result':'PASS' if cases and all(c['status']=='PASS' for c in cases) and not errors else 'FAIL'}
 (out/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False));return result['result']=='PASS'
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--output',type=Path,required=True);args=a.parse_args();raise SystemExit(0 if asyncio.run(run(args.output)) else 1)
