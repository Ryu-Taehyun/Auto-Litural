"""Isolated Playwright adapter; existing CLI source stays unchanged."""
import ast
import base64
import asyncio
import contextlib
import inspect
import io
import json
import secrets
from pathlib import Path
import sys
import threading
import types
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
WIRE = sys.stdout


def emit(**event):
    WIRE.write(json.dumps(event, ensure_ascii=False) + '\n')
    WIRE.flush()


class Logs(io.TextIOBase):
    def __init__(self):
        self.pending = ''

    def write(self, text):
        self.pending += text
        while '\n' in self.pending:
            line, self.pending = self.pending.split('\n', 1)
            if line.strip() and not line.startswith('입력 대상:'):
                emit(message=line[:1000])
        return len(text)

    def flush(self):
        pass


def load_automation(path):
    # Only declarations are loaded. ask_names / ensure_chrome / asyncio.run at
    # module level are intentionally excluded; importing the CLI would run it.
    tree = ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
    tree.body = [node for node in tree.body if isinstance(node, (
        ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef,
        ast.ClassDef, ast.Assign, ast.AnnAssign,
    )) and not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call))]
    module = types.ModuleType('ritual_automation')
    module.__file__ = str(path)
    exec(compile(tree, str(path), 'exec'), module.__dict__)
    if not inspect.iscoroutinefunction(module.find_button):
        raise RuntimeError('기존 자동화의 find_button 인터페이스가 변경되었습니다.')
    return module


def instrument(module, mode):
    steps = [('radio_check', '호흡 안내'), ('write_1', '편안했던 장면'),
             ('write_2', '강점과 가치'), ('write_3', '동료 인정'),
             ('write_4', '받은 인정'), ('write_final', '긍정 목표')] if mode == 'morning' else [
                 ('write_1', '강점 행동 돌아보기'), ('write_2', '감사 나누기'), ('write_final', '감사일기')]
    for index, (name, label) in enumerate(steps):
        original = getattr(module, name)

        async def wrapped(*args, _fn=original, _i=index, _label=label, **kwargs):
            emit(status='running', step=_i, phase=_label + ' 입력 중', message=_label + ' 단계를 시작합니다.')
            return await _fn(*args, **kwargs)

        setattr(module, name, wrapped)
    return len(steps)


def authenticated(url):
    parsed = urlsplit(url)
    path = parsed.path.removesuffix('.html')
    return parsed.scheme == 'https' and parsed.netloc == 'aleph-omega.vercel.app' and (
        path == '/tutorial' or path.startswith('/tutorial/') or
        path == '/cortex' or path.startswith('/cortex/'))


def existing_page(browser):
    """Prefer a logged-in portal tab over tutorial, login and unrelated tabs."""
    candidates = []
    for context in browser.contexts:
        for index, page in enumerate(context.pages):
            if page.is_closed():
                continue
            parsed = urlsplit(page.url)
            if authenticated(page.url):
                score = 100 if parsed.path.startswith('/cortex') else 90
            elif parsed.scheme == 'https' and parsed.hostname == 'accounts.google.com':
                score = 70
            elif parsed.scheme == 'https' and parsed.netloc == 'aleph-omega.vercel.app':
                score = 50
            else:
                continue
            candidates.append((score, index, context, page))
    if not candidates:
        return (browser.contexts[0], None) if browser.contexts else (None, None)
    _, _, context, page = max(candidates, key=lambda item: item[:2])
    return context, page


@contextlib.asynccontextmanager
async def headless_page(chromium, source):
    """Copy all relevant web session stores in memory; leave the source intact."""
    parsed = urlsplit(source.url)
    if not authenticated(source.url):
        raise RuntimeError('로그인한 리추얼 탭이 없습니다. 로그인 열기로 로그인을 완료한 뒤 헤드리스를 실행하세요.')
    origin = f'{parsed.scheme}://{parsed.netloc}'
    state = await export_storage(source)
    state['origins'] = [entry for entry in state.get('origins', []) if entry['origin'] == origin]
    state['cookies'] = [cookie for cookie in state.get('cookies', [])
                        if parsed.hostname == cookie['domain'].lstrip('.') or
                        parsed.hostname.endswith('.' + cookie['domain'].lstrip('.'))]
    tab_state = await source.evaluate('() => Object.fromEntries(Object.entries(sessionStorage))')
    hidden = await chromium.launch(channel='chrome', headless=True)
    try:
        context = await hidden.new_context(storage_state=state, viewport={'width': 1280, 'height': 900})
        await context.add_init_script('(()=>{const origin=' + json.dumps(origin) + ';const entries=' +
                                      json.dumps(tab_state, ensure_ascii=True) +
                                      ';if(location.origin===origin){for(const [k,v] of Object.entries(entries)){if(sessionStorage.getItem(k)===null)sessionStorage.setItem(k,v)}}})()')
        del state, tab_state
        page = await context.new_page()
        # Start at the existing portal path, never restart OAuth through /login.
        await page.goto(origin + parsed.path, wait_until='domcontentloaded', timeout=45000)
        yield page
    finally:
        await hidden.close()


async def export_storage(source):
    """Register existing CDP origins using a background, locally fulfilled page.

    A new CDP connection may not know origins from tabs opened by an earlier
    connection, so storage_state can omit their localStorage and IndexedDB.
    """
    context = source.context
    parsed = urlsplit(source.url)
    origin = f'{parsed.scheme}://{parsed.netloc}'
    state = await context.storage_state(indexed_db=True)
    if not any(entry['origin'] == origin for entry in state.get('origins', [])):
        session = await context.browser.new_browser_cdp_session()
        page_session = await context.new_cdp_session(source)
        info = await page_session.send('Target.getTargetInfo')
        await page_session.detach()
        probe_url = origin + '/__auto_litural_session_' + secrets.token_hex(8)
        target = None

        async def local_probe(route):
            await route.fulfill(status=200, content_type='text/html', body='<!doctype html><title>Local session snapshot</title>')

        await context.route(probe_url, local_probe)
        try:
            options = {'url': 'about:blank', 'background': True, 'newWindow': False}
            context_id = info.get('targetInfo', {}).get('browserContextId')
            if context_id:
                options['browserContextId'] = context_id
            async with context.expect_page(timeout=10000) as pending:
                target = await session.send('Target.createTarget', options)
            probe = await pending.value
            await probe.goto(probe_url, wait_until='domcontentloaded', timeout=10000)
            state = await context.storage_state(indexed_db=True)
        finally:
            if target:
                with contextlib.suppress(Exception):
                    await session.send('Target.closeTarget', {'targetId': target['targetId']})
            await context.unroute(probe_url, local_probe)
            await session.detach()
    entry = next((entry for entry in state.get('origins', []) if entry['origin'] == origin), None)
    if entry is None:
        raise RuntimeError('기존 로그인 탭의 저장소를 복사하지 못했습니다. 로그인 Chrome을 닫고 저장 프로필로 헤드리스를 다시 실행하세요.')
    # Read from the existing authenticated document as well, never from a blank tab.
    entry['localStorage'] = await source.evaluate('() => Object.entries(localStorage).map(([name,value])=>({name,value}))')
    return state


@contextlib.asynccontextmanager
async def persistent_headless_page(chromium, profile):
    if not profile.exists():
        raise RuntimeError('저장된 웹 UI 로그인 프로필이 없습니다. 로그인 열기에서 먼저 로그인하세요.')
    from playwright.async_api import Error as PlaywrightError
    try:
        context = await chromium.launch_persistent_context(str(profile), channel='chrome', headless=True,
                                                          viewport={'width': 1280, 'height': 900})
    except PlaywrightError:
        raise RuntimeError('저장된 프로필을 헤드리스로 열지 못했습니다. 같은 전용 프로필을 사용하는 Chrome이 남아 있는지 확인하고 다시 실행하세요.') from None
    try:
        _, page = existing_page(types.SimpleNamespace(contexts=[context]))
        if page is None:
            page = context.pages[0] if context.pages else await context.new_page()
        if not authenticated(page.url):
            await page.goto('https://aleph-omega.vercel.app/cortex', wait_until='domcontentloaded', timeout=45000)
        yield page
    finally:
        await context.close()


async def login(page, headless=False):
    from playwright.async_api import TimeoutError as PlaywrightTimeout
    if authenticated(page.url):
        emit(status='running', phase='기존 로그인 탭 재사용', message='로그인한 탭을 그대로 사용합니다. 로그인 페이지를 다시 열지 않습니다.')
        return
    account_denied = False

    def failed_request(request):
        host = urlsplit(request.url).hostname or ''
        if host == 'esm.sh' or host.endswith('.supabase.co') or host == 'accounts.google.com':
            # Never log full OAuth URLs, query strings, cookies or auth codes.
            emit(message=f'로그인 관련 연결 실패: {host} (네트워크·보안 프로그램의 연결 차단 여부를 확인하세요.)')

    def auth_response(response):
        nonlocal account_denied
        parsed = urlsplit(response.url)
        host = parsed.hostname or ''
        if response.status >= 400 and (host == 'esm.sh' or host.endswith('.supabase.co') or host == 'accounts.google.com'):
            known_paths = {'/rest/v1/rpc/get_my_account_context_v1', '/auth/v1/authorize',
                           '/auth/v1/user/identities/authorize', '/auth/v1/user'}
            endpoint = parsed.path if parsed.path in known_paths else '인증 관련 요청'
            emit(message=f'로그인 서비스 응답 오류: {host} · {endpoint} · HTTP {response.status}')
            if response.status == 403 and parsed.path == '/rest/v1/rpc/get_my_account_context_v1':
                account_denied = True

    def navigation(frame):
        if frame == page.main_frame:
            url = urlsplit(frame.url)
            # The host alone identifies the OAuth hop without exposing state.
            if url.hostname:
                emit(message=f'로그인 화면 이동: {url.hostname}')

    page.on('requestfailed', failed_request)
    page.on('response', auth_response)
    page.on('framenavigated', navigation)
    try:
        resume_google = urlsplit(page.url).hostname == 'accounts.google.com'
        emit(status='waiting_login', phase='로그인 상태를 확인하는 중', message='기존 Google 인증 화면을 계속 사용합니다.' if resume_google else '로그인 페이지 요청을 시작합니다.')
        try:
            if not resume_google:
                await page.goto('https://aleph-omega.vercel.app/login', wait_until='domcontentloaded', timeout=45000)
        except PlaywrightTimeout:
            # An unrelated resource can delay DOMContentLoaded. Only continue
            # when the intended origin and its actual login button are present.
            parsed = urlsplit(page.url)
            if authenticated(page.url):
                emit(status='running', phase='로그인 확인됨', message='기존 로그인 세션이 확인되었습니다.')
                return
            if parsed.scheme != 'https' or parsed.netloc != 'aleph-omega.vercel.app' or not await page.locator('#googleBtn').is_visible():
                raise RuntimeError('로그인 페이지 로딩 45초를 초과했습니다. Chrome에서 사이트 접속과 네트워크를 확인하세요.') from None
            emit(message='페이지 일부 리소스 로딩이 지연됩니다. 로그인 기능 준비 상태를 별도로 확인합니다.')

        emit(phase='사이트 로그인 기능이 준비될 때까지 기다리는 중', message='로그인 페이지를 열었습니다. Google 버튼의 초기화를 확인합니다.')
        loop = asyncio.get_running_loop()
        ready_deadline = loop.time() + 30
        clicked_at = None
        clicks = 0
        google_seen = False
        site_warning_seen = False
        overall_deadline = loop.time() + 300
        while loop.time() < overall_deadline:
            if page.is_closed():
                raise RuntimeError('로그인 Chrome 탭이 닫혔습니다. 로그인 열기를 다시 눌러 주세요.')
            if authenticated(page.url):
                emit(status='running', phase='로그인 확인됨', message='로그인이 확인되었습니다.')
                return
            host = urlsplit(page.url).hostname or ''
            if host == 'accounts.google.com':
                if not google_seen:
                    google_seen = True
                    emit(phase='Google 인증 화면에서 로그인을 완료해 주세요', message='Google 인증 화면으로 이동했습니다. 비밀번호와 인증 코드는 Chrome에서 직접 입력하세요.')
                if headless:
                    raise RuntimeError('헤드리스 세션에 재인증이 필요합니다. 로그인 열기에서 먼저 로그인하세요.')
            else:
                button = page.locator('#googleBtn')
                if await button.is_visible():
                    message = page.locator('#loginMsg')
                    text = ((await message.text_content(timeout=1000)) or '').strip() if await message.count() else ''
                    # The static HTML has an empty loginMsg. Its module imports
                    # esm.sh + auth helpers before installing click handlers.
                    # Visibility of googleBtn alone does not imply readiness.
                    if '로그인 상태를 확인하지 못했습니다' in text and not site_warning_seen:
                        site_warning_seen = True
                        emit(message='사이트가 기존 계정 상태를 확인하지 못했습니다. 사이트 안내를 유지한 채 Google 로그인을 시도합니다.')
                    if any(part in text for part in ('로그인 서비스에 연결하지 못했습니다', '로그인 과정에 문제가 있었습니다', '전환하지 못했습니다')):
                        raise RuntimeError('사이트가 로그인 서비스 오류를 표시했습니다. Chrome의 안내와 사이트 인증 서비스 상태를 확인하세요.')
                    if text and not text.startswith('Google 로그인으로 이동') and await button.is_enabled():
                        if headless:
                            raise RuntimeError('헤드리스 로그인 세션이 없습니다. 로그인 열기에서 먼저 로그인한 후 다시 실행하세요.')
                        if clicked_at is None or (loop.time() - clicked_at > 3 and clicks < 2):
                            await page.bring_to_front()
                            await button.click(timeout=10000)
                            clicked_at = loop.time()
                            clicks += 1
                            emit(phase='Google 로그인 화면으로 이동하는 중', message='준비된 Google 로그인 버튼을 눌렀습니다.')
                    elif clicked_at is None and loop.time() > ready_deadline:
                        raise RuntimeError('로그인 기능 초기화가 30초 안에 끝나지 않았습니다. esm.sh 스크립트·사이트 인증 서버 연결과 Chrome 안내를 확인하세요.')
                elif clicked_at is None and loop.time() > ready_deadline and not google_seen:
                    raise RuntimeError('Google 로그인 버튼을 찾지 못했습니다. Chrome 화면과 사이트 구조 변경 여부를 확인하세요.')
            if clicked_at is not None and not google_seen and loop.time() - clicked_at > 45:
                if account_denied:
                    raise RuntimeError('사이트 계정 정보 조회가 HTTP 403으로 거부되었고 Google 화면으로 이동하지 못했습니다. Chrome에서 직접 로그인해 같은 증상인지 확인하고 사이트 관리자에게 계정·세션 권한 확인을 요청하세요.')
                raise RuntimeError('Google 로그인 버튼을 눌렀지만 45초 동안 인증 화면으로 이동하지 못했습니다. Chrome에서 Google 버튼을 직접 눌러 보고 사이트 인증 서비스·네트워크를 확인하세요.')
            await asyncio.sleep(0.25)
        raise RuntimeError('로그인 대기 5분을 초과했습니다. Chrome에서 로그인 상태를 확인하고 다시 실행하세요.')
    finally:
        page.remove_listener('requestfailed', failed_request)
        page.remove_listener('response', auth_response)
        page.remove_listener('framenavigated', navigation)


@contextlib.contextmanager
def input_delay(milliseconds):
    # Patch the real Locator class in this isolated worker, preserving expect()
    # and chained locator types used by the unmodified automation scripts.
    from playwright.async_api import Locator
    originals = {name: getattr(Locator, name) for name in ('fill', 'click', 'check')}
    for name, original in originals.items():
        async def delayed(self, *args, _original=original, **kwargs):
            if milliseconds:
                await asyncio.sleep(milliseconds / 1000)
            return await _original(self, *args, **kwargs)
        setattr(Locator, name, delayed)
    try:
        yield
    finally:
        for name, original in originals.items():
            setattr(Locator, name, original)


async def preview(page):
    image = await page.screenshot(type='jpeg', quality=75, full_page=True, timeout=15000)
    if len(image) > 4_000_000:
        image = await page.screenshot(type='jpeg', quality=60, full_page=False, timeout=15000)
    emit(preview=base64.b64encode(image).decode('ascii'))


async def ritual_menu(page, headless=False):
    emit(status='running', phase='로그인한 화면의 리추얼 메뉴를 확인하는 중')
    from playwright.async_api import TimeoutError as PlaywrightTimeout
    try:
        await page.locator('summary').filter(has_text='학습 메뉴').wait_for(state='visible', timeout=15000)
    except PlaywrightTimeout:
        if headless:
            await preview(page)
        if urlsplit(page.url).path.startswith('/tutorial'):
            raise RuntimeError('로그인은 완료됐지만 튜토리얼 화면입니다. 열린 Chrome에서 튜토리얼을 마치고 학습 메뉴가 보이는 화면에서 다시 실행하세요.') from None
        if headless and (await page.locator('#googleBtn').is_visible() or
                         await page.get_by_role('heading', name='로그인이 필요합니다.', exact=True).is_visible()):
            raise RuntimeError('저장된 로그인 세션이 없거나 만료됐습니다. 로그인 열기에서 다시 로그인하고 학습 메뉴까지 이동한 뒤 실행하세요.') from None
        raise RuntimeError('로그인 화면에서 학습 메뉴를 찾지 못했습니다. 결과 화면이나 열린 Chrome에서 로그인 상태와 사이트 메뉴 변경 여부를 확인하세요.') from None


async def fill_ritual(page, config, commands, automation=None):
    mode = config['mode']
    module = automation if automation is not None else load_automation(ROOT / ('main.py' if mode == 'morning' else 'close.py'))
    total = instrument(module, mode)
    delay = config.get('delay_ms', 300)
    emit(message=f'입력·클릭 간 딜레이: {delay}ms')
    await ritual_menu(page, headless=config.get('headless', False))
    with input_delay(delay):
        await module.find_button(page, config['names'])
    if not config.get('headless'):
        emit(status='review', phase='입력 완료 · Chrome에서 확인 후 직접 저장하세요', step=total,
             message='모든 입력 함수가 완료되었습니다. 마지막 저장 버튼은 누르지 않았습니다.')
        return
    await preview(page)
    emit(status='headless_review', phase='입력 완료 · 아래 결과 화면을 확인해 주세요', step=total,
         message='헤드리스 입력 완료. 결과 화면을 검토하고 직접 저장하거나 중지하세요. 아직 저장하지 않았습니다.')
    while await commands.get() != 'save':
        pass
    emit(status='running', phase='사용자 요청으로 저장 버튼을 누르는 중')
    label = '계획 저장하고 아침 마치기' if mode == 'morning' else '저장하고 마무리'
    await page.get_by_role('button', name=label, exact=True).click(timeout=15000)
    # Do not claim server-side persistence: report the click and show the result.
    await asyncio.sleep(1)
    await preview(page)
    emit(status='submitted', phase='저장 버튼 클릭 완료 · 아래 결과 화면을 확인하세요',
         message='사용자 요청으로 저장 버튼을 눌렀습니다. 결과 화면에서 성공 여부를 확인하세요.')


async def execute(config, commands, automation=None):
    import ui_chrome as chrome
    from playwright.async_api import async_playwright
    headless = config.get('headless', False)
    emit(phase='Chrome 연결 준비', message='웹 UI 전용 AutoLituralWebChrome 프로필을 사용합니다. 기존 ChromeDebug는 보존됩니다.')
    source_running = await asyncio.to_thread(chrome.is_open) if headless else True
    if not headless:
        await asyncio.to_thread(chrome.ensure_chrome)
    async with async_playwright() as p:
        if headless and not source_running:
            emit(message='로그인 Chrome이 닫혀 있어 저장된 전용 프로필을 헤드리스로 직접 사용합니다.')
            async with persistent_headless_page(p.chromium, chrome.profile_path()) as page:
                await login(page, headless=True)
                await fill_ritual(page, config, commands, automation)
            return
        browser = await p.chromium.connect_over_cdp(chrome.CDP_URL, timeout=15000)
        if not browser.contexts:
            raise RuntimeError('Chrome 기본 프로필에 연결하지 못했습니다.')
        context, selected = existing_page(browser)
        if headless:
            if selected is None or not authenticated(selected.url):
                raise RuntimeError('로그인한 탭을 찾지 못했습니다. 로그인 열기에서 로그인하고 학습 메뉴를 확인한 뒤 다시 실행하세요.')
            await ritual_menu(selected)
            emit(message='기존 로그인 탭의 쿠키·localStorage·sessionStorage·IndexedDB를 메모리로 복사합니다.')
            async with headless_page(p.chromium, selected) as page:
                await login(page, headless=True)
                await fill_ritual(page, config, commands, automation)
            return
        page = selected if selected is not None else await context.new_page()
        await page.bring_to_front()
        await login(page)
        if config['mode'] == 'login':
            emit(status='logged_in', phase='로그인 확인 완료', message='로그인 확인이 끝났습니다. 리추얼을 실행할 수 있습니다.')
            return
        await fill_ritual(page, config, commands, automation)
        # Exiting Playwright disconnects the client; never browser.close().


async def run(config):
    # Windows/NumPy native imports can block while another thread owns the
    # stdin read lock. Load the CLI declarations and dependencies before the
    # daemon control reader starts and before connecting the browser driver.
    automation = None
    if config['mode'] != 'login':
        emit(status='running', phase='자동 입력 모듈 준비 중', message='입력용 라이브러리를 먼저 준비합니다.')
        automation = load_automation(ROOT / ('main.py' if config['mode'] == 'morning' else 'close.py'))
        emit(message='입력용 라이브러리 준비가 완료되었습니다.')
    loop = asyncio.get_running_loop()
    stopped = asyncio.Event()
    commands = asyncio.Queue()

    def read_stop():
        for line in sys.stdin:
            try:
                command = line.strip()
                if command == 'stop':
                    loop.call_soon_threadsafe(stopped.set)
                    return
                if command == 'save':
                    loop.call_soon_threadsafe(commands.put_nowait, command)
            except RuntimeError:
                return

    threading.Thread(target=read_stop, daemon=True).start()
    task = asyncio.create_task(execute(config, commands, automation))
    stop_task = asyncio.create_task(stopped.wait())
    try:
        done, _ = await asyncio.wait((task, stop_task), timeout=900, return_when=asyncio.FIRST_COMPLETED)
        if task in done:
            await task
        else:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            if stop_task not in done:
                raise RuntimeError('전체 실행 제한 시간 15분을 초과했습니다.')
            emit(message='작업 취소가 처리되었습니다.')
    finally:
        stop_task.cancel()


def main():
    config = json.loads(sys.stdin.readline())
    try:
        with contextlib.redirect_stdout(Logs()), contextlib.redirect_stderr(Logs()):
            asyncio.run(run(config))
        return 0
    except BaseException as exc:
        if isinstance(exc, KeyboardInterrupt):
            return 1
        # Avoid printing traceback, cookies, URLs with auth query strings, or names.
        if isinstance(exc, ModuleNotFoundError):
            message = '필수 패키지가 없습니다. web.cmd로 실행해 설치해 주세요.'
        elif isinstance(exc, RuntimeError):
            message = str(exc)[:300]
        elif isinstance(exc, SystemExit):
            message = 'Chrome을 시작하지 못했습니다. chrome.py의 설치 경로와 웹 UI용 9223 포트를 확인하세요.'
        else:
            message = f'{type(exc).__name__}: 자동 입력을 완료하지 못했습니다. Chrome 화면, 로그인, 오늘 아침 기록 여부와 사이트 입력창을 확인하세요.'
        emit(status='error', phase='실행 실패', message=message)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
