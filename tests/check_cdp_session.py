"""Offline Chrome regression for reconnecting to an already authenticated tab."""
import asyncio
import importlib.util
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

ROOT=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path(__file__).resolve().parent.parent
spec=importlib.util.spec_from_file_location('worker_cdp_test',ROOT/'web_ui/worker.py')
w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)
from chrome import CHROME
from playwright.async_api import async_playwright

HTML='''<script>(async()=>{
const r=indexedDB.open('cdp-auth',1);r.onupgradeneeded=()=>r.result.createObjectStore('tokens');
const db=await new Promise(ok=>r.onsuccess=()=>ok(r.result));const t=db.transaction('tokens');const q=t.objectStore('tokens').get('session');
const token=await new Promise(ok=>q.onsuccess=()=>ok(q.result));db.close();
if(localStorage.getItem('auth-local')==='ok'&&sessionStorage.getItem('auth-tab')==='ok'&&token==='ok'&&document.cookie.includes('auth_cookie=ok')){
document.body.innerHTML='<summary>학습 메뉴</summary><h1 id="ready">ready</h1>'}
})()</script>'''


async def route(r):
    await r.fulfill(status=200,content_type='text/html',body='<body>'+HTML)


class Destination:
    def __init__(self,browser):self.browser=browser
    async def new_context(self,**kw):
        context=await self.browser.new_context(**kw)
        await context.route('https://aleph-omega.vercel.app/cortex',route)
        return context
    async def close(self):await self.browser.close()


class Chromium:
    def __init__(self,impl):self.impl=impl
    async def launch(self,**kw):return Destination(await self.impl.launch(**kw))


async def main():
    with TemporaryDirectory(ignore_cleanup_errors=True) as temp:
        profile=Path(temp)/'profile'
        proc=subprocess.Popen([CHROME,'--headless=new','--remote-debugging-port=0',f'--user-data-dir={profile}',
                               '--no-first-run','--no-default-browser-check','about:blank'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            async with asyncio.timeout(15):
                while not (profile/'DevToolsActivePort').exists():await asyncio.sleep(.1)
            port=(profile/'DevToolsActivePort').read_text().splitlines()[0]
            async with async_playwright() as owner:
                browser=await owner.chromium.connect_over_cdp(f'http://127.0.0.1:{port}')
                try:
                    context=browser.contexts[0]
                    await context.route('https://aleph-omega.vercel.app/cortex',route)
                    source=context.pages[0]
                    await source.goto('https://aleph-omega.vercel.app/cortex')
                    await source.evaluate('''async()=>{
localStorage.setItem('auth-local','ok');sessionStorage.setItem('auth-tab','ok');document.cookie='auth_cookie=ok;Secure;Path=/;Max-Age=3600';
const r=indexedDB.open('cdp-auth',1);r.onupgradeneeded=()=>r.result.createObjectStore('tokens');
const db=await new Promise(ok=>r.onsuccess=()=>ok(r.result));const t=db.transaction('tokens','readwrite');t.objectStore('tokens').put('ok','session');
await new Promise(ok=>t.oncomplete=ok);db.close();}''')
                    await source.reload();await source.locator('#ready').wait_for()
                    before=len(context.pages)
                    async with async_playwright() as reconnected:
                        attached=await reconnected.chromium.connect_over_cdp(f'http://127.0.0.1:{port}')
                        _,existing=w.existing_page(attached)
                        initial=await existing.context.storage_state(indexed_db=True)
                        missing_origin=not any(o['origin']=='https://aleph-omega.vercel.app' for o in initial.get('origins',[]))
                        async with w.headless_page(Chromium(reconnected.chromium),existing) as hidden:
                            await hidden.locator('#ready').wait_for(timeout=10000)
                            assert not existing.is_closed()
                    assert len(context.pages)==before and source.url=='https://aleph-omega.vercel.app/cortex'
                    print('PASS: CDP reconnect restored all four session stores; source tab unchanged; temporary tab closed. Initially missing origin:',missing_origin)
                finally:
                    await browser.close()
        finally:
            try:proc.wait(timeout=5)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()


asyncio.run(main())
