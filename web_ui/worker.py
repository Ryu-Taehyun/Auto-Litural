"""Isolated Playwright adapter; existing CLI source stays unchanged."""
import ast
import base64
import asyncio
import contextlib
import inspect
import io
import json
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


async def login(page, headless=False):
    from playwright.async_api import TimeoutError as PlaywrightTimeout
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
        emit(status='waiting_login', phase='로그인 페이지를 불러오는 중', message='로그인 페이지 요청을 시작합니다.')
        try:
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


async def fill_ritual(page, config, commands):
    mode = config['mode']
    module = load_automation(ROOT / ('main.py' if mode == 'morning' else 'close.py'))
    total = instrument(module, mode)
    delay = config.get('delay_ms', 300)
    emit(message=f'입력·클릭 간 딜레이: {delay}ms')
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


async def execute(config, commands):
    import ui_chrome as chrome
    from playwright.async_api import async_playwright
    headless = config.get('headless', False)
    emit(phase='Chrome 연결 준비', message='웹 UI 전용 AutoLituralWebChrome 프로필을 사용합니다. 기존 ChromeDebug는 보존됩니다.')
    if headless:
        if not await asyncio.to_thread(chrome.is_open):
            raise RuntimeError('먼저 로그인 열기로 Chrome을 열고 로그인하세요. 헤드리스는 기존 세션이 필요합니다.')
    else:
        await asyncio.to_thread(chrome.ensure_chrome)
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(chrome.CDP_URL, timeout=15000)
        if not browser.contexts:
            raise RuntimeError('Chrome 기본 프로필에 연결하지 못했습니다.')
        context = browser.contexts[0]
        if headless:
            # Cookies and localStorage stay in memory, never exported to disk.
            state = await context.storage_state()
            hidden = await p.chromium.launch(channel='chrome', headless=True)
            try:
                isolated = await hidden.new_context(storage_state=state, viewport={'width': 1280, 'height': 900})
                del state
                page = await isolated.new_page()
                await login(page, headless=True)
                await fill_ritual(page, config, commands)
            finally:
                await hidden.close()
            return
        page = await context.new_page()
        await login(page)
        if config['mode'] == 'login':
            emit(status='logged_in', phase='로그인 확인 완료', message='로그인 확인이 끝났습니다. 리추얼을 실행할 수 있습니다.')
            return
        await fill_ritual(page, config, commands)
        # Exiting Playwright disconnects the client; never browser.close().


async def run(config):
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
    task = asyncio.create_task(execute(config, commands))
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
