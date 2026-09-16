#!/usr/bin/env python3
"""Offline Chromium QA. Requires explicitly installed Playwright; NOT an isolated H0 check.
No browser policies are modified. Real-origin IndexedDB/HTTP are not qualified here.
"""
from __future__ import annotations
import argparse,asyncio,base64,hashlib,importlib.metadata,json,os,re,subprocess,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
STATES=json.loads((ROOT/'product/wp11/fixtures/states.json').read_text())
STORIES=json.loads((ROOT/'baseline/spec-00.02.00/ui/stories.json').read_text())
FLOW_IDS=['identity','unavailable_no_fake_success','stable_input_on_locale','composition_remote_retained','stale_snapshot_refused','preview_required','preview_stale_refused','dialog_escape_focus','dispatch_unknown_no_replay','text_not_html','details_toggle','mobile_no_overflow','rtl_no_overflow','zoom_reflow','dark_contrast','real_host_save','real_host_reload_restore','host_save_while_editing','bad_receipt_no_success','wrong_session_scope','destroy_pending_load','idb_unavailable_no_fallback','gallery_real_controls','gallery_decline_switch_keeps_draft']
IDS=['renderer.story.'+s['id'] for s in STORIES]+['renderer.'+i for i in FLOW_IDS]
def module_url(p:Path,cache:dict[Path,str]):
 p=p.resolve()
 if p in cache:return cache[p]
 if not p.is_relative_to(ROOT/'product/wp11'):raise ValueError('module outside generated library')
 code=p.read_text()
 def replace(m):return m[1]+module_url(p.parent/m[2],cache)+m[3]
 code=re.sub(r"(from\s*['\"])(\.{1,2}/[^'\"]+)(['\"])",replace,code)
 url='data:text/javascript;base64,'+base64.b64encode(code.encode()).decode();cache[p]=url;return url
async def main(out:Path):
 from playwright.async_api import async_playwright
 out.mkdir(parents=True,exist_ok=True);cases=[];console=[];exceptions=[];started=time.time()
 html=(ROOT/'product/wp11/app/index.html').read_text()
 html=re.sub(r'<link[^>]+>','',html);html=re.sub(r'<script[\s\S]*?</script>','',html)
 css=(ROOT/'product/wp11/app/style.css').read_text();cache={};url=module_url(ROOT/'product/wp11/lib/renderer.js',cache)
 indexed=module_url(ROOT/'product/wp11/lib/indexeddb-drafts.js',cache)
 async with async_playwright() as p:
  browser=await p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
  page=await browser.new_page(viewport={'width':1400,'height':1080})
  page.set_default_timeout(7000)
  page.on('pageerror',lambda e:exceptions.append(str(e)))
  page.on('console',lambda m:console.append(m.text) if m.type=='error' else None)
  temp=tempfile.TemporaryDirectory(prefix='par-browser-draft-');store=Path(temp.name);os.chmod(store,0o700)
  async def host_draft(request):
   proc=await asyncio.create_subprocess_exec('node',str(ROOT/'tests/product/wp11/durable/bridge.mjs'),str(store),stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
   stdout,stderr=await proc.communicate(json.dumps(request,ensure_ascii=False).encode())
   if proc.returncode:raise RuntimeError(stderr.decode()[:1200])
   return json.loads(stdout)
  await page.expose_function('hostDraft',host_draft)
  base=json.loads(json.dumps(STATES[9]['state']))
  base['document'].update(title='週末の計画',text='やりたいことを、少しずつ。\n\n土曜日\n朝はコーヒーを淹れて、読みかけの本を読む。\n午後は散歩へ。気になった場所をここに書き留める。\n\n持っていくもの\n・ノート\n・カメラ\n・いつもの水筒',conflicts=[],privateDraft=False)
  base['authority'].update(state='ready',role='editor',sharedWriteAllowed=True)
  async def mount(state=None,effect=False):
   await page.evaluate('window.view?.destroy()')
   await page.set_content(html);await page.add_style_tag(content=css)
   await page.evaluate("""async({url,state,effect})=>{window.renderer=await import(url);window.current=structuredClone(state);window.effects=[];window.view=renderer.mountReference(document.querySelector('#reference-root'),state,effect?{effectPort:async i=>{effects.push(i);return {outcome:'accepted'}}}:{});window.editor=document.querySelector('[data-test=editor]');} """,{'url':url,'state':state or base,'effect':effect})
  async def case(name,fn):
   try:await fn();cases.append({'id':name,'status':'PASS'})
   except Exception as e:
    cases.append({'id':name,'status':'FAIL','error':str(e)[:2000]});await page.screenshot(path=str(out/('failure-'+name.replace('.','_')+'.png')),full_page=True)
  for row,story in zip(STATES,STORIES):
   async def story_check(row=row,story=story):
    await mount(row['state']);assert await page.locator('[data-test=primary]').inner_text()==story['required_text']
    for forbidden in story['forbidden_claims']:assert forbidden not in await page.locator('[data-test=primary]').inner_text()
   await case('renderer.story.'+story['id'],story_check)
  async def identity():
   await mount();assert await page.title()=='PAR · Shared notes';assert await page.locator('h1').inner_text()=='週末の計画';assert await page.locator('textarea').count()==1
  await case('renderer.identity',identity)
  async def unavailable():
   await mount();assert await page.locator('[data-test=private-save]').is_disabled();await page.locator('textarea').fill('まだ保存していない');assert 'まだ保存' in await page.locator('[data-test=primary]').inner_text();assert not await page.evaluate('effects.length')
  await case('renderer.unavailable_no_fake_success',unavailable)
  async def stable():
   await mount();await page.locator('textarea').fill('編集中😀');await page.evaluate("editor.setSelectionRange(2,2);view.setLocale('en')");assert await page.evaluate('editor===document.querySelector("textarea")');assert await page.locator('textarea').input_value()=='編集中😀';assert await page.evaluate('editor.selectionStart')==2
  await case('renderer.stable_input_on_locale',stable)
  async def composition():
   await mount();await page.locator('textarea').fill('変換途中');await page.evaluate("editor.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));current.sequence='2';current.revision='r2';current.document.text='remote';current.document.frontier='next';view.update(current)");assert await page.locator('textarea').input_value()=='変換途中';assert await page.evaluate('view.getDraft().composing');await page.evaluate("editor.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true}))");assert not await page.evaluate('view.getDraft().composing');assert await page.evaluate('view.getDraft().pendingRemote.text')=='remote'
  await case('renderer.composition_remote_retained',composition)
  async def stale():
   await mount();assert await page.evaluate("(()=>{const s=structuredClone(current);s.sequence='0';try{view.update(s);return false}catch{return true}})()")
  await case('renderer.stale_snapshot_refused',stale)
  async def preview_required():
   await mount(STATES[7]['state'],True);await page.locator('[data-command=approve-invite]').click();assert await page.locator('dialog').is_visible();assert await page.get_by_role('button',name='確認して続ける',exact=True).is_disabled();assert await page.evaluate('effects.length')==0
  await case('renderer.preview_required',preview_required)
  async def preview_stale():
   await preview_required();await page.evaluate("current.sequence='2';current.revision='r2';view.update(current)");await page.locator('dialog input[type=checkbox]').check();await page.get_by_role('button',name='確認して続ける',exact=True).click();assert await page.evaluate('effects.length')==0;assert '状態が変わり' in await page.locator('[data-test=effect-result]').inner_text()
  await case('renderer.preview_stale_refused',preview_stale)
  async def escape():
   await preview_required();await page.evaluate("current.sequence='2';current.revision='r2';view.update(current)");await page.keyboard.press('Escape');await page.wait_for_timeout(20);assert await page.evaluate('document.activeElement.textContent')=='状態の詳細'
  await case('renderer.dialog_escape_focus',escape)
  async def dispatch_unknown():
   await mount(base,True);await page.evaluate("view.destroy();effects=[];view=renderer.mountReference(document.querySelector('#reference-root'),current,{effectPort:async i=>{effects.push(i);throw Error('after handing off')}})");await page.locator('[data-command=export]').click();await page.wait_for_timeout(10);assert await page.evaluate('effects.length')==1;await page.evaluate("view.setLocale('en')");assert await page.locator('[data-command=export]').is_disabled();assert 'unknown' in await page.locator('[data-test=effect-result]').inner_text() or '確認' in await page.locator('[data-test=effect-result]').inner_text()
  await case('renderer.dispatch_unknown_no_replay',dispatch_unknown)
  async def text_only():
   s=json.loads(json.dumps(base));s['document']['title']='<img src=x onerror=alert(1)>';await mount(s);assert await page.locator('h1 img').count()==0;assert '<img' in await page.locator('h1').inner_text()
  await case('renderer.text_not_html',text_only)
  async def details():
   await mount();await page.get_by_role('button',name='状態の詳細',exact=True).click();assert await page.locator('.par-details').is_visible();assert 'space-1' in await page.locator('.par-details').inner_text();await page.get_by_role('button',name='状態の詳細',exact=True).click();assert not await page.locator('.par-details').is_visible()
  await case('renderer.details_toggle',details)
  async def mobile():
   await page.set_viewport_size({'width':390,'height':844});await mount();assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth');await page.screenshot(path=str(out/'mobile.png'),full_page=True)
  await case('renderer.mobile_no_overflow',mobile)
  async def rtl():
   await mobile();await page.evaluate("document.body.dir='rtl'");assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
  await case('renderer.rtl_no_overflow',rtl)
  async def zoom():
   await mount();await page.evaluate("document.documentElement.style.fontSize='32px'");assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth');await page.evaluate("document.documentElement.style.fontSize=''")
  await case('renderer.zoom_reflow',zoom)
  async def dark():
   await page.set_viewport_size({'width':1400,'height':1080});await mount();await page.evaluate("document.documentElement.dataset.theme='dark'");assert await page.evaluate("getComputedStyle(document.documentElement).colorScheme")=='dark';assert await page.evaluate("(()=>{const rgb=s=>s.match(/\\d+/g).slice(0,3).map(Number).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4});const l=s=>{const a=rgb(s);return .2126*a[0]+.7152*a[1]+.0722*a[2]};const a=l(getComputedStyle(document.querySelector('.par-primary')).color),b=l(getComputedStyle(document.documentElement).backgroundColor);return (Math.max(a,b)+.05)/(Math.min(a,b)+.05)>=4.5})()");await page.screenshot(path=str(out/'dark.png'),full_page=True);await page.evaluate("document.documentElement.dataset.theme='light'")
  await case('renderer.dark_contrast',dark)
  async def attach_bridge():
   await page.evaluate("""async()=>{const session={scope:current.scope,load:()=>hostDraft({action:'load'}),save:(draft,version,operationId)=>hostDraft({action:'save',draft,version,operationId}),reconcile:async()=>{throw Error('no unknown receipt')},close(){}};await view.attachDraftSession(session)}""")
  async def save_host():
   await mount();await attach_bridge();await page.locator('textarea').fill('再起動しても戻る、暗号化下書き🔐');await page.locator('[data-test=private-save]').click();await page.wait_for_function("document.querySelector('.par-private-status').textContent.includes('端末に保存しました')");assert (await host_draft({'action':'load'}))['draft']['text']=='再起動しても戻る、暗号化下書き🔐';assert all('再起動' not in f.read_text() for f in store.glob('*.json'))
  await case('renderer.real_host_save',save_host)
  async def restore_host():
   await mount();await attach_bridge();assert await page.locator('textarea').input_value()==base['document']['text'];await page.locator('[data-test=private-restore]').click();assert await page.locator('dialog').is_visible();await page.locator('dialog input[type=checkbox]').check();await page.get_by_role('button',name='確認して続ける',exact=True).click();assert await page.locator('textarea').input_value()=='再起動しても戻る、暗号化下書き🔐';assert await page.evaluate('effects.length')==0
  await case('renderer.real_host_reload_restore',restore_host)
  async def edit_during_save():
   await mount();await page.evaluate("""async()=>{window.completeSave=null;await view.attachDraftSession({scope:current.scope,load:async()=>({version:0,operationId:null,draft:null}),save:(draft,version,operationId)=>new Promise(resolve=>{window.completeSave=()=>resolve({version:version+1,operationId,slot:'a'.repeat(64),ciphertextHash:'b'.repeat(64),durability:'browser-best-effort',sharedSaved:false,replicated:false})}),reconcile:async()=> 'NOT_CONFIRMED',close(){}})}""");await page.locator('textarea').fill('first');await page.locator('[data-test=private-save]').click();await page.locator('textarea').fill('second');await page.evaluate('completeSave()');await page.wait_for_timeout(20);assert await page.locator('textarea').input_value()=='second';assert 'この下書きを端末に保存しました' not in await page.locator('.par-private-status').inner_text()
  await case('renderer.host_save_while_editing',edit_during_save)
  async def bad_receipt():
   await mount();await page.evaluate("""async()=>view.attachDraftSession({scope:current.scope,load:async()=>({version:0,operationId:null,draft:null}),save:async(d,v,o)=>({version:v+1,operationId:o,slot:'a'.repeat(64),ciphertextHash:'b'.repeat(64),durability:'browser-best-effort',sharedSaved:true,replicated:false}),reconcile:async()=> 'NOT_CONFIRMED',close(){}})""");await page.locator('textarea').fill('private');await page.locator('[data-test=private-save]').click();await page.wait_for_timeout(20);assert '結果を確認できません' in await page.locator('.par-private-status').inner_text()
  await case('renderer.bad_receipt_no_success',bad_receipt)
  async def wrong_scope():
   await mount();assert await page.evaluate("""async()=>{try{await view.attachDraftSession({scope:{...current.scope,documentId:'other'},load:async()=>({version:0,operationId:null,draft:null}),close(){}});return false}catch{return true}}""")
  await case('renderer.wrong_session_scope',wrong_scope)
  async def destroy_load():
   await mount();await page.evaluate("""()=>{window.finishLoad=null;window.attaching=view.attachDraftSession({scope:current.scope,load:()=>new Promise(r=>window.finishLoad=r),close(){},save(){},reconcile(){}});view.destroy();finishLoad({version:0,operationId:null,draft:null});}""");await page.evaluate('attaching');assert await page.locator('#reference-root').inner_text()==''
  await case('renderer.destroy_pending_load',destroy_load)
  async def idb_blocked():
   # about:blank has no storage origin. This verifies fail-closed behavior only.
   response=await page.evaluate("""async url=>{const m=await import(url);try{const p=await m.openIndexedDbDraftStore();p.close();return 'AVAILABLE'}catch(e){return e.code||e.name}}""",indexed)
   assert response!='AVAILABLE',response
  await case('renderer.idb_unavailable_no_fallback',idb_blocked)
  async def gallery_controls():
   await page.evaluate('window.view?.destroy()');await page.set_content(html);await page.add_style_tag(content=css)
   main_url=module_url(ROOT/'product/wp11/app/main.mjs',cache)
   await page.evaluate("""async({url,states})=>{window.fetch=async path=>{if(path!=='../fixtures/states.json')throw Error('Unexpected offline fixture path');return new Response(JSON.stringify(states),{status:200,headers:{'Content-Type':'application/json'}})};await import(url+'#gallery');window.galleryEditor=document.querySelector('textarea')}""",{'url':main_url,'states':STATES})
   assert await page.locator('#scenario option').count()==25
   await page.locator('textarea').fill('言語を変えても消えない');await page.locator('#locale').select_option('en')
   assert await page.locator('textarea').input_value()=='言語を変えても消えない';assert await page.evaluate('galleryEditor===document.querySelector("textarea")')
   await page.locator('#theme').select_option('dark');assert await page.evaluate('document.documentElement.dataset.theme')=='dark'
   await page.locator('#direction').select_option('rtl');assert await page.evaluate('document.body.dir')=='rtl'
  await case('renderer.gallery_real_controls',gallery_controls)
  async def decline():
   page.once('dialog',lambda d:asyncio.create_task(d.dismiss()))
   await page.locator('#scenario').select_option('1');assert await page.locator('#scenario').input_value()=='0';assert await page.locator('textarea').input_value()=='言語を変えても消えない'
  await case('renderer.gallery_decline_switch_keeps_draft',decline)
  # Final screenshots use the actual gallery entry module, only fixture fetch is injected.
  await page.locator('#locale').select_option('ja');await page.locator('#theme').select_option('light');await page.locator('#direction').select_option('ltr')
  await page.locator('textarea').fill(base['document']['text'])
  await page.set_viewport_size({'width':390,'height':844});await page.screenshot(path=str(out/'mobile.png'),full_page=True)
  await page.set_viewport_size({'width':1400,'height':1080});await page.screenshot(path=str(out/'desktop.png'),full_page=True)
  environment={'browser':browser.version,'driver':'Python Playwright '+importlib.metadata.version('playwright'),'browser_plugin':'not listed; Playwright fallback','mode':'OFFLINE_DOM_NO_POLICY_CHANGE','url':page.url,'real_origin_indexeddb':'NOT_RUN','http_navigation':'BLOCKED_BY_MANAGED_URLBLOCKLIST','persistent_ui_test':'explicit test-only Node host bridge (real encrypted file I/O); not production browser transport'}
  await browser.close();temp.cleanup()
 result={'schema_version':1,'scope':'OFFLINE_RENDERING_AND_NODE_HOST_BRIDGE_ONLY','result':'PASS' if len(cases)==len(IDS) and len(set(c['id'] for c in cases))==len(IDS) and sorted(c['id'] for c in cases)==sorted(IDS) and all(c['status']=='PASS' for c in cases) and not exceptions and not console else 'FAIL','cases':cases,'environment':environment,'console_errors':console,'page_errors':exceptions,'seconds':time.time()-started,'screenshots':['desktop.png','mobile.png','dark.png'],'not_established':['HTTP delivery','IndexedDB actual-origin writes/reload','native IME','screen reader','shared data persistence/CRDT','production security']}
 result['expected_case_ids']=IDS
 result['source_inputs']=[{'path':p.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted([*list((ROOT/'product/wp11/src').glob('*.ts')),*list((ROOT/'product/wp11/lib').glob('*')),*list((ROOT/'product/wp11/app').glob('*')),*list((ROOT/'product/wp11/adapters').glob('*')),ROOT/'tests/product/wp11/durable/bridge.mjs',Path(__file__).resolve()]) if p.is_file()]
 (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False,indent=2));return 0 if result['result']=='PASS' else 1
if __name__=='__main__':
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--output',type=Path,default=Path('/tmp/par-browser-qa'));ap.add_argument('--list',action='store_true');a=ap.parse_args()
 if a.list:print(json.dumps(IDS));raise SystemExit(0)
 raise SystemExit(asyncio.run(main(a.output)))
