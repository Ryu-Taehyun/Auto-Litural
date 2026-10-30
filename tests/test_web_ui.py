import asyncio
import contextlib
import http.client
import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock, call

ROOT = Path(__file__).resolve().parent.parent


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'web_ui' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


server = load('ui_server', 'server.py')
worker = load('ui_worker', 'worker.py')
ui_chrome = load('ui_chrome', 'ui_chrome.py')


class ChromeProfileTests(unittest.TestCase):
    def test_profile_path_matches_visible_and_persistent_headless(self):
        with patch.dict(os.environ,{'LOCALAPPDATA':str(ROOT/'test-appdata')}):
            self.assertEqual(ui_chrome.profile_path(),ROOT/'test-appdata'/'AutoLituralWebChrome')

    def test_only_accept_chrome_debug_endpoint_without_system_proxy(self):
        for content, expected in ((b'{"Browser":"Chrome/130"}',True), (b'{}',False), (b'not-json',False)):
            with patch.object(ui_chrome.urllib.request,'build_opener') as make:
                make.return_value.open.return_value = io.BytesIO(content)
                self.assertEqual(ui_chrome.is_open(),expected)
                self.assertEqual(make.call_args.args[0].proxies,{})
                make.return_value.open.assert_called_once_with('http://127.0.0.1:9223/json/version',timeout=1)


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.jobs = server.Jobs()
        self.http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.BaseHTTPRequestHandler)
        self.port = self.http.server_port
        self.http.RequestHandlerClass = server.make_handler(self.jobs, self.port, 'test-token')
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()

    def request(self, method, path, body=None, **headers):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        defaults = {'X-Control-Token': 'test-token', 'Origin': f'http://127.0.0.1:{self.port}', 'Content-Type':'application/json'}
        defaults.update(headers)
        connection.request(method, path, body, defaults)
        response = connection.getresponse()
        data = response.read()
        result = response.status, data, dict(response.getheaders())
        connection.close()
        return result

    def test_assets_and_session_token(self):
        code, body, headers = self.request('GET', '/')
        self.assertEqual(code, 200)
        self.assertIn(b'test-token', body)
        self.assertNotIn(b'__CONTROL_TOKEN__', body)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
        for asset in ('/app.js', '/style.css', '/theme.js'):
            self.assertEqual(self.request('GET', asset)[0], 200)

    def test_status_requires_token(self):
        self.assertEqual(self.request('GET', '/api/status', **{'X-Control-Token':''})[0], 403)
        code,body,_ = self.request('GET', '/api/status')
        self.assertEqual(code,200)
        self.assertEqual(json.loads(body)['speed_modes'],['humanize','instant','custom'])

    def test_reject_foreign_origin_and_host(self):
        self.assertEqual(self.request('POST','/api/start','{}', Origin='https://evil.example')[0],403)
        self.assertEqual(self.request('GET','/', Host='evil.example')[0],403)
        self.assertEqual(self.request('POST','/api/start','{}', Origin='null')[0],403)
        self.assertEqual(self.request('GET','/', **{'Sec-Fetch-Site':'cross-site'})[0],403)

    def test_validation_and_no_arbitrary_files(self):
        for payload in ({'mode':'anything','names':'a'}, {'mode':'morning','names':''},
                        {'mode':'close','names':'a b c d'}, {'mode':'morning','names':[]}, [],
                        {'mode':'morning','names':'a'*31}):
            self.assertEqual(self.request('POST','/api/start',json.dumps(payload))[0],400)
        self.assertEqual(self.request('POST','/api/start','{broken')[0],400)
        self.assertEqual(self.request('POST','/api/start','{}', **{'Content-Type':'text/plain'})[0],415)
        self.assertEqual(self.request('GET','/../chrome.py')[0],404)
        self.assertEqual(self.request('GET','/api/stop')[0],404)

    def test_dispatch_allowed_values(self):
        with patch.object(self.jobs, 'start', return_value={'status':'running'}) as start:
            self.assertEqual(self.request('POST','/api/start',json.dumps({'mode':'morning','names':'하늘, 바다'}))[0],200)
            start.assert_called_once_with('morning',['하늘','바다'],False,300,'custom')
        self.assertEqual(self.request('POST','/api/stop','{}')[0],200)

    def test_options_and_save_guards(self):
        for extra in ({'headless':'true'}, {'headless':1}, {'delay_ms':-1}, {'delay_ms':3001}, {'delay_ms':True}, {'delay_ms':1.5}):
            payload = {'mode':'morning','names':'test',**extra}
            self.assertEqual(self.request('POST','/api/start',json.dumps(payload))[0],400)
        with patch.object(self.jobs,'start',return_value={'status':'running'}) as start:
            self.assertEqual(self.request('POST','/api/start',json.dumps({'mode':'close','names':'test','headless':True,'delay_ms':1000}))[0],200)
            start.assert_called_once_with('close',['test'],True,1000,'custom')
        self.assertEqual(self.request('POST','/api/start',json.dumps({'mode':'login','headless':True}))[0],400)
        self.assertEqual(self.request('POST','/api/save','{}')[0],400)
        self.assertEqual(self.request('POST','/api/save','{}',Origin='https://evil.example')[0],403)
        self.assertEqual(self.request('GET','/api/preview',**{'X-Control-Token':''})[0],403)
        self.assertEqual(self.request('GET','/api/preview')[0],404)
        self.jobs.preview = b'jpeg-test'
        code, image, headers = self.request('GET','/api/preview')
        self.assertEqual((code,image),(200,b'jpeg-test'))
        self.assertEqual(headers['Content-Type'],'image/jpeg')

    def test_speed_modes_are_validated_and_forwarded(self):
        for speed in ('humanize','instant','custom'):
            with patch.object(self.jobs,'start',return_value={'status':'running'}) as start:
                code=self.request('POST','/api/start',json.dumps({'mode':'morning','names':'test','speed_mode':speed,'delay_ms':0}))[0]
                self.assertEqual(code,200)
                start.assert_called_once_with('morning',['test'],False,0,speed)
        for invalid in (None,[],{},'slow',True):
            self.assertEqual(self.request('POST','/api/start',json.dumps({'mode':'morning','names':'test','speed_mode':invalid}))[0],400)


class SpeedTests(unittest.TestCase):
    def test_humanize_samples_a_fresh_delay_for_every_action(self):
        from playwright.async_api import Locator
        original=AsyncMock()
        sleep=AsyncMock()
        async def actions():
            await Locator.fill(None,'first')
            await Locator.fill(None,'second')
        with patch.object(Locator,'fill',original),patch.object(worker.asyncio,'sleep',sleep),patch.object(worker.random,'uniform',side_effect=[6.25,11.75]) as random_delay,patch.object(worker,'emit'):
            with worker.input_delay(0,'humanize'):
                asyncio.run(actions())
            self.assertIs(Locator.fill,original)
        self.assertEqual(sleep.await_args_list,[call(6.25),call(11.75)])
        self.assertEqual(random_delay.call_args_list,[call(6.0,12.0),call(6.0,12.0)])
        self.assertEqual(original.await_count,2)

    def test_instant_adds_no_sleep_even_if_legacy_delay_is_set(self):
        from playwright.async_api import Locator
        original=AsyncMock()
        with patch.object(Locator,'fill',original),patch.object(worker.asyncio,'sleep',new_callable=AsyncMock) as sleep,patch.object(worker.random,'uniform') as random_delay:
            with worker.input_delay(3000,'instant'):
                asyncio.run(Locator.fill(None,'text'))
        original.assert_awaited_once()
        sleep.assert_not_awaited()
        random_delay.assert_not_called()

    def test_humanize_wait_is_cancellable_before_typing(self):
        from playwright.async_api import Locator
        original=AsyncMock()
        with patch.object(Locator,'fill',original),patch.object(worker.asyncio,'sleep',new_callable=AsyncMock) as sleep,patch.object(worker,'emit'):
            sleep.side_effect=asyncio.CancelledError
            with self.assertRaises(asyncio.CancelledError):
                with worker.input_delay(0,'humanize'):
                    asyncio.run(Locator.fill(None,'text'))
            self.assertIs(Locator.fill,original)
        original.assert_not_awaited()


class JobTests(unittest.TestCase):
    def wait_done(self, jobs):
        deadline = time.monotonic()+8
        while jobs.proc is not None and time.monotonic()<deadline:
            time.sleep(.02)
        self.assertIsNone(jobs.proc)

    def test_completion_and_bounded_logs(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            (path/'worker.py').write_text('import sys,json\njson.loads(sys.stdin.readline())\nprint(json.dumps({"status":"review","step":6,"phase":"done"}),flush=True)\n',encoding='utf-8')
            with patch.object(server,'ASSETS',path):
                jobs = server.Jobs(path)
                jobs.start('morning',['a'])
                self.wait_done(jobs)
                self.assertEqual(jobs.snapshot()['status'],'review')
                self.assertEqual(jobs.snapshot()['step'],6)
                for i in range(400):
                    jobs.log(str(i))
                self.assertEqual(len(jobs.snapshot()['logs']),300)

    def test_single_job_and_cooperative_stop(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            (path/'worker.py').write_text('import sys\nsys.stdin.readline()\nsys.stdin.readline()\n',encoding='utf-8')
            with patch.object(server,'ASSETS',path):
                jobs = server.Jobs(path)
                jobs.start('login',[])
                with self.assertRaises(ValueError):
                    jobs.start('morning',['a'])
                jobs.stop()
                self.wait_done(jobs)
                self.assertEqual(jobs.snapshot()['status'],'stopped')
                jobs.stop()

    def test_unexpected_exit_is_error(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            (path/'worker.py').write_text('import sys\nsys.stdin.readline()\n',encoding='utf-8')
            with patch.object(server,'ASSETS',path):
                jobs = server.Jobs(path)
                jobs.start('login',[])
                self.wait_done(jobs)
                self.assertEqual(jobs.snapshot()['status'],'error')

    def test_headless_review_waits_for_explicit_save(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            (path/'worker.py').write_text('import sys,json\nc=json.loads(sys.stdin.readline())\nassert c["headless"] and c["delay_ms"]==1000\nprint(json.dumps({"status":"headless_review","preview":"aW1hZ2U="}),flush=True)\nassert sys.stdin.readline().strip()=="save"\nprint(json.dumps({"status":"submitted"}),flush=True)\n',encoding='utf-8')
            with patch.object(server,'ASSETS',path):
                jobs = server.Jobs(path)
                jobs.start('morning',['a'],True,1000)
                deadline = time.monotonic()+5
                while jobs.snapshot()['status']!='headless_review' and time.monotonic()<deadline:
                    time.sleep(.02)
                try:
                    self.assertEqual(jobs.snapshot()['status'],'headless_review')
                    self.assertTrue(jobs.snapshot()['active'])
                    self.assertEqual(jobs.preview,b'image')
                    with self.assertRaises(ValueError):
                        jobs.start('morning',['a'])
                    jobs.save()
                    self.wait_done(jobs)
                    self.assertEqual(jobs.snapshot()['status'],'submitted')
                    self.assertFalse(jobs.snapshot()['active'])
                finally:
                    jobs.shutdown()


class Locator:
    def __init__(self, page, selector):
        self.page, self.selector = page, selector
        self.last = self
        self.first = self
    def filter(self, **kw): return self
    def or_(self, other): return self
    async def wait_for(self, **kw): pass
    async def is_visible(self): return False
    async def count(self): return self.page.names
    async def fill(self, value): self.page.fills.append((self.selector,value))
    async def click(self): self.page.clicks.append(self.selector)
    async def check(self): pass


class Page:
    def __init__(self, names):
        self.names, self.clicks, self.fills = names, [], []
    def locator(self, selector, **kw): return Locator(self,selector)
    def get_by_role(self, role, name): return Locator(self,name)


class AdapterTests(unittest.TestCase):
    def test_dependencies_load_before_blocking_control_reader(self):
        if not (ROOT/'main.py').exists():
            self.skipTest('Requires the existing automation source.')
        code = '''import asyncio,importlib.util,sys
from pathlib import Path
root=Path(sys.argv[1])
s=importlib.util.spec_from_file_location('worker_probe',root/'web_ui/worker.py')
w=importlib.util.module_from_spec(s);s.loader.exec_module(w)
async def fake_execute(config,commands,automation):
    assert automation is not None
    assert hasattr(automation,'pd')
    assert not automation.pd.read_csv(root/'csv/Title.csv',header=None).empty
    w.emit(status='review',message='IMPORT_ORDER_OK')
w.execute=fake_execute
asyncio.run(w.run({'mode':'morning','names':['test']}))
'''
        # Keep stdin open and idle, exactly as the live server does while the
        # control reader waits. A regression hangs at the native NumPy import.
        proc=subprocess.Popen([sys.executable,'-u','-c',code,str(ROOT)],stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                              env={**os.environ,'PYTHONIOENCODING':'utf-8'})
        try:
            proc.wait(timeout=12)
            output=proc.stdout.read().decode('utf-8',errors='replace')
            self.assertEqual(proc.returncode,0,output)
            self.assertIn('IMPORT_ORDER_OK',output)
        finally:
            if proc.poll() is None:
                proc.kill();proc.wait()
            proc.stdin.close();proc.stdout.close()

    def test_existing_portal_tab_is_reused_before_tutorial_or_login(self):
        def page(url):
            return SimpleNamespace(url=url,is_closed=lambda:False)
        login=page('https://aleph-omega.vercel.app/login')
        tutorial=page('https://aleph-omega.vercel.app/tutorial')
        cortex=page('https://aleph-omega.vercel.app/cortex.html')
        google=page('https://accounts.google.com/v3/signin/identifier')
        context=SimpleNamespace(pages=[cortex,login,tutorial,google])
        selected_context,selected=worker.existing_page(SimpleNamespace(contexts=[context]))
        self.assertIs(selected_context,context)
        self.assertIs(selected,cortex)

    def test_login_does_not_navigate_authenticated_tab(self):
        page=SimpleNamespace(url='https://aleph-omega.vercel.app/cortex')
        with patch.object(worker,'emit'):
            # No goto/new_page/locator methods: calling any would fail this test.
            asyncio.run(worker.login(page))

    def test_unrelated_tabs_are_not_repurposed(self):
        context=SimpleNamespace(pages=[SimpleNamespace(url='https://example.com',is_closed=lambda:False)])
        self.assertEqual(worker.existing_page(SimpleNamespace(contexts=[context])),(context,None))

    def test_auth_url_is_exact_origin(self):
        self.assertTrue(worker.authenticated('https://aleph-omega.vercel.app/cortex'))
        self.assertFalse(worker.authenticated('https://evil.example/cortex'))
        self.assertFalse(worker.authenticated('https://aleph-omega.vercel.app.evil.example/tutorial'))
        self.assertFalse(worker.authenticated('https://aleph-omega.vercel.app/cortex-fake'))
        self.assertTrue(worker.authenticated('https://aleph-omega.vercel.app/cortex.html'))
        self.assertTrue(worker.authenticated('https://aleph-omega.vercel.app/tutorial.html?from=login'))
        self.assertFalse(worker.authenticated('https://aleph-omega.vercel.app/cortex.html-fake'))

    def test_cli_not_executed_when_loading(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'example.py'
            path.write_text('url="x"\nasync def find_button(*args): pass\ndef ask_names(): raise AssertionError()\nnames=ask_names()\nraise AssertionError()\n',encoding='utf-8')
            module = worker.load_automation(path)
            self.assertEqual(module.url,'x')
            self.assertFalse(hasattr(module,'names'))

    def test_existing_morning_and_close_without_saving(self):
        if not (ROOT/'main.py').exists():
            self.skipTest('Copy these tests into the original project to verify its functions.')
        previous = Path.cwd()
        os.chdir(ROOT)
        try:
            for mode, filename, total in [('morning','main.py',6),('close','close.py',3)]:
                for count in (1,3):
                    page = Page(count)
                    module = worker.load_automation(ROOT/filename)
                    events = []
                    with patch.object(worker,'emit',side_effect=lambda **e:events.append(e)), contextlib.redirect_stdout(__import__('io').StringIO()):
                        self.assertEqual(worker.instrument(module,mode),total)
                        asyncio.run(module.find_button(page,['test']*count))
                    self.assertTrue(page.fills)
                    self.assertFalse(any('저장' in click for click in page.clicks))
                    self.assertEqual([e['step'] for e in events],list(range(total)))
                    expected = '#planFirstAction' if mode=='morning' else f'#gratitude-person-{count-1}'
                    self.assertIn(expected,[selector for selector,value in page.fills])
        finally:
            os.chdir(previous)


if __name__ == '__main__':
    unittest.main()
