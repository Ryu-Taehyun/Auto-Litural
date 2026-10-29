"""Dedicated UI profile; never reset or modify the legacy ChromeDebug profile."""
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request

PORT = 9223
CDP_URL = f'http://127.0.0.1:{PORT}'


def profile_path():
    return Path(os.environ['LOCALAPPDATA']) / 'AutoLituralWebChrome'


def is_open():
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(CDP_URL + '/json/version', timeout=1) as response:
            info = json.load(response)
        return str(info.get('Browser', '')).startswith(('Chrome/', 'HeadlessChrome/'))
    except (OSError, ValueError):
        return False


def ensure_chrome(timeout=20):
    if is_open():
        return
    from chrome import CHROME
    if not Path(CHROME).is_file():
        raise RuntimeError('Chrome이 없습니다. chrome.py의 CHROME 설치 경로를 확인하세요.')
    profile = profile_path()
    subprocess.Popen([CHROME, f'--remote-debugging-port={PORT}',
                      '--remote-debugging-address=127.0.0.1', f'--user-data-dir={profile}',
                      '--no-first-run', '--no-default-browser-check'])
    for _ in range(timeout * 4):
        if is_open():
            return
        time.sleep(.25)
    raise RuntimeError('웹 UI 전용 Chrome에 연결하지 못했습니다. 9223 포트와 Chrome 창을 확인하세요.')
