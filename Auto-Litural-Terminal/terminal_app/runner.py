import asyncio
import contextlib
import csv
import importlib.util
from pathlib import Path
import random
from .settings import validate, speed_label

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / 'Playwright'
_browser = None


def load_file(name, path):
    spec = importlib.util.spec_from_file_location(name,path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def browser_module():
    global _browser
    if _browser is None: _browser = load_file('litural_terminal_chrome',ENGINE/'chrome.py')
    return _browser


def prepare(ritual):
    if ritual not in ('morning','finish'): raise RuntimeError('리추얼 종류가 올바르지 않습니다. 2번을 다시 설정하세요.')
    required = ['Title.csv'] + [f'{i}.csv' for i in range(1,8)] if ritual == 'morning' else [
        'close_effort.csv','close_note.csv','close_share.csv','close_peer_story.csv','close_gratitude.csv']
    for name in required:
        path = ROOT/'csv'/name
        if not path.is_file(): raise RuntimeError(f'CSV 파일이 없습니다: csv/{name}')
        with path.open(encoding='utf-8-sig',newline='') as stream:
            rows = list(csv.reader(stream))
        if not rows or any(len(row)!=1 or not row[0].strip() for row in rows):
            raise RuntimeError(f'CSV는 비어 있지 않은 한 열 문장이어야 합니다: csv/{name}')
    # Load pandas/native dependencies before entering asyncio or reading any
    # execution-control input. There is no background stdin reader in this app.
    filename = 'main.py' if ritual == 'morning' else 'close.py'
    return load_file('litural_terminal_'+ritual,ENGINE/filename)


@contextlib.contextmanager
def writing_timing(settings, log):
    from playwright.async_api import Locator
    originals = {name:getattr(Locator,name) for name in ('fill','click','check')}
    for name,original in originals.items():
        async def action(self,*args,_fn=original,**kwargs):
            seconds = random.uniform(6,12) if settings.speed == 'humanize' else settings.delay_ms/1000 if settings.speed == 'custom' else 0
            if seconds:
                log(f'[WAIT] {seconds:.1f}초 대기 · Ctrl+C로 중지')
                await asyncio.sleep(seconds)
            return await _fn(self,*args,**kwargs)
        setattr(Locator,name,action)
    try:
        yield
    finally:
        for name,original in originals.items():setattr(Locator,name,original)


def instrument(module, ritual, log):
    steps = [('radio_check','호흡 안내'),('write_1','편안했던 장면'),('write_2','강점과 가치'),
             ('write_3','동료 인정'),('write_4','받은 인정'),('write_final','긍정 목표')] if ritual == 'morning' else [
                 ('write_1','강점 행동 돌아보기'),('write_2','감사 나누기'),('write_final','감사일기')]
    total = len(steps)
    for index,(name,label) in enumerate(steps,1):
        original = getattr(module,name)
        async def step(*args,_fn=original,_index=index,_label=label,**kwargs):
            log(f'[{_index}/{total}] {_label}')
            return await _fn(*args,**kwargs)
        setattr(module,name,step)


async def execute(settings, automation, chrome, log):
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(chrome.CDP_URL,timeout=15000)
        if not browser.contexts: raise RuntimeError('Chrome 프로필에 연결하지 못했습니다.')
        page = chrome.choose_page(browser)
        if page is None: page = await browser.contexts[0].new_page()
        await page.bring_to_front()
        await chrome.login(page,log)
        await chrome.ready_menu(page)
        instrument(automation,settings.ritual,log)
        with writing_timing(settings,log):
            await automation.find_button(page,settings.partners)
        log('[DONE] 입력 완료. Chrome에서 내용을 확인하고 마지막 저장을 직접 눌러 주세요.')
        # Disconnect the automation client; never close the user's Chrome.


def run_ritual(settings, log=print):
    if validate(settings): raise RuntimeError('설정값이 올바르지 않습니다. 2~4번을 다시 입력하세요.')
    log('[SETUP] 입력 모듈과 CSV를 확인합니다...')
    automation = prepare(settings.ritual)
    chrome = browser_module()
    log('[SETUP] 준비 완료 · ' + speed_label(settings))
    log('[CHROME] 터미널 전용 Chrome에 연결합니다. 처음 실행할 때는 직접 로그인해야 합니다.')
    chrome.ensure_chrome()
    asyncio.run(execute(settings,automation,chrome,log))
