# 크롬 디버깅 모드 실행 (9222 포트가 이미 열려 있으면 그대로 사용)
import os
import subprocess
import time
import urllib.request

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
DEBUG_URL = "http://127.0.0.1:9222/json/version"


def is_open():
    try:
        urllib.request.urlopen(DEBUG_URL, timeout=1)
        return True
    except OSError:
        return False


def ensure_chrome(timeout=15):
    if is_open():
        return

    if not os.path.exists(CHROME):
        raise SystemExit(f"[error] Chrome not found: {CHROME}")

    print("[setup] Starting Chrome in debugging mode...")
    user_data = os.path.join(os.environ["LOCALAPPDATA"], "ChromeDebug")
    subprocess.Popen([CHROME, "--remote-debugging-port=9222", f"--user-data-dir={user_data}"])

    for _ in range(timeout):
        if is_open():
            return
        time.sleep(1)
    raise SystemExit("[error] Chrome debugging port 9222 did not open.")
