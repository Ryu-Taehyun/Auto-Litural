"""Chrome connection and manual Google login for the independent terminal app."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.parse import urlsplit
import urllib.request

PORT = 9224
CDP_URL = f'http://127.0.0.1:{PORT}'
LOGIN_URL = 'https://aleph-omega.vercel.app/login'


def profile_path():
    location = os.environ.get('LOCALAPPDATA')
    if not location:
        raise RuntimeError('이 실행기는 Windows용입니다. LOCALAPPDATA 환경 변수를 확인하세요.')
    return Path(location) / 'AutoLituralTerminalChrome'


def chrome_path():
    candidates = [os.environ.get('AUTO_LITURAL_CHROME')]
    for variable in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA'):
        if os.environ.get(variable):
            candidates.append(str(Path(os.environ[variable]) / 'Google/Chrome/Application/chrome.exe'))
    for candidate in candidates:
        if candidate and Path(candidate).is_file(): return Path(candidate)
    raise RuntimeError('Google Chrome을 찾지 못했습니다. 설치하거나 AUTO_LITURAL_CHROME에 chrome.exe 경로를 지정하세요.')


def is_open():
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(CDP_URL + '/json/version',timeout=1) as response:
            version = json.load(response)
        return str(version.get('Browser','')).startswith('Chrome/')
    except (OSError, ValueError):
        return False


def ensure_chrome():
    if is_open(): return
    subprocess.Popen([str(chrome_path()),f'--remote-debugging-port={PORT}',
                      '--remote-debugging-address=127.0.0.1',f'--user-data-dir={profile_path()}',
                      '--no-first-run','--no-default-browser-check'])
    for _ in range(80):
        if is_open(): return
        time.sleep(.25)
    raise RuntimeError('터미널용 Chrome 연결에 실패했습니다. Chrome 창과 9224 포트를 확인하세요.')


def authenticated(url):
    parsed = urlsplit(url)
    path = parsed.path.removesuffix('.html')
    return parsed.scheme == 'https' and parsed.netloc == 'aleph-omega.vercel.app' and any(
        path == name or path.startswith(name + '/') for name in ('/cortex','/tutorial','/ritual'))


def choose_page(browser):
    candidates = []
    for context in browser.contexts:
        for index,page in enumerate(context.pages):
            if page.is_closed(): continue
            parsed = urlsplit(page.url)
            if authenticated(page.url): score = 100 if not parsed.path.startswith('/tutorial') else 90
            elif parsed.scheme == 'https' and parsed.hostname == 'accounts.google.com': score = 70
            elif parsed.scheme == 'https' and parsed.netloc == 'aleph-omega.vercel.app': score = 50
            elif page.url in ('about:blank','chrome://newtab/'): score = 1
            else: continue
            candidates.append((score,index,page))
    return max(candidates,key=lambda entry:entry[:2])[2] if candidates else None


async def login(page, log=print):
    if authenticated(page.url):
        log('[LOGIN] 기존 로그인 탭을 재사용합니다.')
        return
    from playwright.async_api import TimeoutError as PlaywrightTimeout
    if urlsplit(page.url).hostname != 'accounts.google.com':
        log('[LOGIN] 사이트 로그인 화면을 여는 중...')
        try:
            await page.goto(LOGIN_URL,wait_until='domcontentloaded',timeout=45000)
        except PlaywrightTimeout:
            if not authenticated(page.url) and not await page.locator('#googleBtn').is_visible():
                raise RuntimeError('로그인 페이지 로딩 시간이 초과됐습니다. Chrome에서 접속 상태를 확인하세요.') from None
    loop = asyncio.get_running_loop()
    deadline = loop.time()+300
    ready_deadline = loop.time()+30
    clicked = False
    google_notice = False
    while loop.time() < deadline:
        if page.is_closed(): raise RuntimeError('로그인 탭이 닫혔습니다. 1번으로 다시 실행하세요.')
        if authenticated(page.url):
            log('[LOGIN] 로그인 확인 완료.')
            return
        if urlsplit(page.url).hostname == 'accounts.google.com':
            if not google_notice:
                log('[LOGIN] Chrome에서 Google 로그인과 추가 인증을 직접 완료하세요. 최대 5분 기다립니다.')
                google_notice = True
        elif not clicked:
            button = page.locator('#googleBtn')
            message = page.locator('#loginMsg')
            if await button.is_visible() and await message.count():
                text = ((await message.text_content(timeout=1000)) or '').strip()
                if text and await button.is_enabled():
                    await button.click(timeout=10000)
                    clicked = True
                    log('[LOGIN] Google 로그인으로 이동합니다. Chrome에서 직접 로그인하세요.')
            if not clicked and loop.time() > ready_deadline:
                raise RuntimeError('로그인 버튼이 준비되지 않았습니다. Chrome에서 로그인 안내와 네트워크 상태를 확인하세요.')
        await asyncio.sleep(.25)
    raise RuntimeError('로그인 대기 5분을 초과했습니다. Chrome에서 상태를 확인하고 다시 실행하세요.')


async def ready_menu(page):
    from playwright.async_api import TimeoutError as PlaywrightTimeout
    try:
        await page.locator('summary').filter(has_text='학습 메뉴').wait_for(state='visible',timeout=20000)
    except PlaywrightTimeout:
        raise RuntimeError('학습 메뉴가 보이지 않습니다. Chrome에서 로그인·튜토리얼·학생 권한을 확인하세요.') from None
