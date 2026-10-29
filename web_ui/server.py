"""Loopback-only control panel. No third-party server dependencies."""
import argparse
import base64
from collections import deque
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time
import webbrowser

ROOT = Path(__file__).resolve().parent.parent
ASSETS = Path(__file__).resolve().parent


class Jobs:
    def __init__(self, root=ROOT):
        self.root = root
        self.lock = threading.RLock()
        self.proc = None
        self.logs = deque(maxlen=300)
        self.serial = 0
        self.preview = None
        self.preview_version = 0
        self.state = dict(id=None, status='idle', phase='실행 대기', step=0, total=0, mode=None)

    def snapshot(self):
        with self.lock:
            return {**self.state, 'active': self.proc is not None, 'preview_version': self.preview_version,
                    'has_preview': self.preview is not None, 'logs': list(self.logs)}

    def log(self, message):
        self.serial += 1
        self.logs.append(dict(id=self.serial, time=time.strftime('%H:%M:%S'), message=str(message)[:1000]))

    def start(self, mode, names, headless=False, delay_ms=300):
        with self.lock:
            if self.proc is not None:
                raise ValueError('현재 작업이 끝난 뒤 다시 실행하세요.')
            job_id = secrets.token_hex(8)
            env = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUNBUFFERED': '1'}
            proc = subprocess.Popen(
                [sys.executable, '-u', str(ASSETS / 'worker.py')],
                cwd=self.root, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding='utf-8', errors='replace', env=env,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
            self.proc = proc
            self.logs.clear()
            self.preview = None
            self.preview_version += 1
            self.state = dict(id=job_id, status='running', phase='Chrome 준비 중', step=0,
                              total={'morning': 6, 'close': 3, 'login': 0}[mode], mode=mode, headless=headless)
            self.log('작업을 시작했습니다. 최종 저장은 Chrome에서 직접 해 주세요.')
            try:
                proc.stdin.write(json.dumps({'mode': mode, 'names': names, 'headless': headless, 'delay_ms': delay_ms}, ensure_ascii=False) + '\n')
                proc.stdin.flush()
            except (OSError, ValueError):
                proc.kill()
                proc.wait()
                self.proc = None
                self.state.update(status='error', phase='작업 시작 실패')
                raise ValueError('작업을 시작하지 못했습니다.')
            threading.Thread(target=self.watch, args=(proc,), daemon=True).start()
            return self.snapshot()

    def watch(self, proc):
        terminal = False
        try:
            for line in proc.stdout:
                with self.lock:
                    try:
                        event = json.loads(line)
                        if not isinstance(event, dict):
                            continue
                    except ValueError:
                        self.log(line.strip())
                        continue
                    if event.get('message'):
                        self.log(event['message'])
                    if isinstance(event.get('preview'), str):
                        try:
                            image = base64.b64decode(event['preview'], validate=True)
                            if len(image) <= 4_000_000:
                                self.preview = image
                                self.preview_version += 1
                        except ValueError:
                            pass
                    if self.state['status'] != 'stopping':
                        for key in ('phase', 'step'):
                            if key in event:
                                self.state[key] = event[key]
                        if event.get('status') in ('waiting_login', 'running', 'review', 'headless_review', 'submitted', 'logged_in', 'error'):
                            self.state['status'] = event['status']
                            terminal = event['status'] in ('review', 'submitted', 'logged_in', 'error')
            code = proc.wait()
            with self.lock:
                if self.state['status'] == 'stopping':
                    self.state.update(status='stopped', phase='중지됨 · 이미 입력된 내용은 Chrome에 남아 있습니다')
                    self.log('자동 입력을 중지했습니다. 이미 실행된 입력은 되돌리지 않습니다.')
                elif code != 0 or not terminal:
                    self.state.update(status='error', phase='작업 실패 · 로그를 확인하세요')
                    self.log('작업이 종료되었습니다. Chrome 상태와 설치된 패키지를 확인하세요.')
        finally:
            for stream in (proc.stdin, proc.stdout):
                stream.close()
            with self.lock:
                if self.proc is proc:
                    self.proc = None

    def stop(self):
        with self.lock:
            proc = self.proc
            if proc is None:
                return self.snapshot()
            if self.state['status'] != 'stopping':
                self.state.update(status='stopping', phase='진행 중인 작업을 중지하는 중')
                self.log('중지를 요청했습니다.')
                try:
                    proc.stdin.write('stop\n')
                    proc.stdin.flush()
                except (OSError, ValueError):
                    pass
                threading.Thread(target=self.kill_later, args=(proc,), daemon=True).start()
            return self.snapshot()

    def save(self):
        with self.lock:
            if self.proc is None or self.state['status'] != 'headless_review':
                raise ValueError('헤드리스 입력 완료 후 결과를 확인하고 저장하세요.')
            self.state.update(status='saving', phase='사용자 요청으로 저장 버튼을 누르는 중')
            try:
                self.proc.stdin.write('save\n')
                self.proc.stdin.flush()
            except (OSError, ValueError):
                self.state.update(status='error', phase='저장 요청 전달 실패')
                raise ValueError('작업이 종료되어 저장 요청을 전달하지 못했습니다.')
            return self.snapshot()

    @staticmethod
    def kill_later(proc):
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except OSError:
                pass

    def shutdown(self):
        self.stop()
        with self.lock:
            proc = self.proc
        if proc:
            self.kill_later(proc)


def make_handler(jobs, port, token):
    allowed_hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
    allowed_origins = {'http://' + host for host in allowed_hosts}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, code, body, kind='application/json; charset=utf-8'):
            data = json.dumps(body, ensure_ascii=False).encode('utf-8') if isinstance(body, dict) else body
            self.send_response(code)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(data)

        def guard(self, api=False, mutation=False):
            if self.headers.get('Host') not in allowed_hosts:
                self.reply(403, {'error': '허용되지 않은 Host입니다.'})
                return False
            origin = self.headers.get('Origin')
            if (origin and origin not in allowed_origins) or (mutation and origin not in allowed_origins):
                self.reply(403, {'error': '같은 로컬 화면에서 요청하세요.'})
                return False
            if self.headers.get('Sec-Fetch-Site') == 'cross-site':
                self.reply(403, {'error': '외부 사이트 접근은 차단됩니다.'})
                return False
            if api and not hmac.compare_digest(self.headers.get('X-Control-Token', '').encode('utf-8'), token.encode('ascii')):
                self.reply(403, {'error': '화면을 새로 고친 뒤 다시 시도하세요.'})
                return False
            return True

        def do_GET(self):
            if not self.guard(api=self.path.startswith('/api/')):
                return
            if self.path == '/api/status':
                self.reply(200, jobs.snapshot())
                return
            if self.path == '/api/preview':
                with jobs.lock:
                    preview = jobs.preview
                if preview is None:
                    self.reply(404, {'error': '아직 결과 화면이 없습니다.'})
                else:
                    self.reply(200, preview, 'image/jpeg')
                return
            files = {'/': ('index.html', 'text/html; charset=utf-8'),
                     '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                     '/style.css': ('style.css', 'text/css; charset=utf-8')}
            item = files.get(self.path)
            if not item:
                self.reply(404, {'error': '찾을 수 없습니다.'})
                return
            data = (ASSETS / item[0]).read_bytes()
            if self.path == '/':
                data = data.replace(b'__CONTROL_TOKEN__', token.encode('ascii'))
            self.reply(200, data, item[1])

        def do_POST(self):
            if not self.guard(api=True, mutation=True):
                return
            if self.path not in ('/api/start', '/api/stop', '/api/save'):
                self.reply(404, {'error': '찾을 수 없습니다.'})
                return
            if self.headers.get('Content-Type', '').split(';')[0].strip() != 'application/json':
                self.reply(415, {'error': 'JSON 요청만 허용됩니다.'})
                return
            try:
                if self.headers.get('Transfer-Encoding'):
                    raise ValueError('지원하지 않는 요청입니다.')
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 4096:
                    raise ValueError('요청 크기가 올바르지 않습니다.')
                self.connection.settimeout(5)
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError('요청 형식이 올바르지 않습니다.')
                if self.path == '/api/stop':
                    self.reply(200, jobs.stop())
                    return
                if self.path == '/api/save':
                    self.reply(200, jobs.save())
                    return
                mode = data.get('mode')
                raw = data.get('names', '')
                headless = data.get('headless', False)
                delay_ms = data.get('delay_ms', 300)
                if type(headless) is not bool or type(delay_ms) is not int or not 0 <= delay_ms <= 3000:
                    raise ValueError('헤드리스는 켜기/끄기, 딜레이는 0~3000ms 정수로 설정하세요.')
                if mode == 'login' and headless:
                    raise ValueError('로그인은 Chrome 창에서 직접 완료해야 합니다.')
                if mode not in ('login', 'morning', 'close') or not isinstance(raw, str) or len(raw) > 120:
                    raise ValueError('실행 종류와 이름을 확인하세요.')
                names = raw.replace(',', ' ').split()
                if mode != 'login' and (not 1 <= len(names) <= 3 or any(len(n) > 30 or any(ord(c) < 32 for c in n) for n in names)):
                    raise ValueError('이름은 1~3명, 각 30자 이내로 입력하세요.')
                self.reply(200, jobs.start(mode, names if mode != 'login' else [], headless, delay_ms))
            except (ValueError, UnicodeError) as exc:
                self.reply(400, {'error': str(exc)[:200]})
            except OSError:
                self.reply(500, {'error': '작업을 처리하지 못했습니다. 서버 콘솔을 확인하세요.'})

    return Handler


def main():
    parser = argparse.ArgumentParser(description='Auto-Litural 로컬 웹 UI')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('포트는 1024~65535 사이여야 합니다.')
    jobs = Jobs()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), make_handler(jobs, args.port, secrets.token_hex(32)))
    server.daemon_threads = True
    server.block_on_close = False
    url = f'http://127.0.0.1:{args.port}'
    print(f'Auto-Litural: {url}\n종료: Ctrl+C (Chrome은 유지됩니다.)', flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        jobs.shutdown()


if __name__ == '__main__':
    main()
