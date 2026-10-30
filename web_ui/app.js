'use strict';
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="control-token"]').content;
// An already-running older server cannot serve theme.js until restarted.
// Keep the restart notice and stop controls usable during that transition.
if (!window.AutoLituralTheme) {
  const read = key => { try { return localStorage.getItem(key); } catch { return null; } };
  const set = theme => {
    if (!['light','dark'].includes(theme)) return;
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem('AutoLitural.theme',theme); } catch {}
    const dark = theme === 'dark';
    $('theme-toggle').setAttribute('aria-pressed',String(dark));
    $('theme-toggle').setAttribute('aria-label',(dark ? '라이트 모드' : '다크 모드') + '로 전환');
    $('theme-label').textContent = dark ? '라이트 모드' : '다크 모드';
    $('theme-icon').textContent = dark ? '☀' : '☾';
  };
  window.AutoLituralTheme = {read,set};
  set(read('AutoLitural.theme') || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'));
}
function selectedSpeed() { return document.querySelector('input[name="speed"]:checked').value; }
function syncSpeed() {
  const speed = selectedSpeed();
  $('custom-delay').hidden = speed !== 'custom';
  $('delay').disabled = speed !== 'custom';
  $('speed-hint').textContent = ({humanize:'입력·클릭·체크마다 6~12초 사이에서 새로운 대기 시간을 무작위로 선택합니다. 대기 중에도 중지할 수 있습니다.',instant:'추가 대기 없이 진행합니다. 사이트 로딩과 입력 준비 시간은 기다립니다.',custom:'각 입력·클릭·체크 전에 지정한 시간만큼 기다립니다.'})[speed];
  try { localStorage.setItem('AutoLitural.speed', speed); } catch {}
}
$('theme-toggle').addEventListener('click', () => window.AutoLituralTheme.set(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'));
const savedSpeed = window.AutoLituralTheme.read('AutoLitural.speed');
if (['humanize','instant','custom'].includes(savedSpeed)) document.querySelector(`input[name="speed"][value="${savedSpeed}"]`).checked = true;
document.querySelectorAll('input[name="speed"]').forEach(input => input.addEventListener('change', syncSpeed));
syncSpeed();
let latest = {logs: []};
let pending = false;
let connected = false;
let lastLog = '';
let previewVersion = -1;
let previewUrl = null;
let previewReady = false;
let showingWarning = false;
let supportsSpeedModes = false;
const busyStates = new Set(['running', 'waiting_login', 'stopping', 'saving', 'headless_review']);
const labels = {idle:'대기 중', running:'실행 중', waiting_login:'로그인 대기', stopping:'중지 중', stopped:'중지됨', review:'확인 필요', headless_review:'결과 확인 대기', saving:'저장 요청 중', submitted:'결과 확인 필요', logged_in:'로그인 확인', error:'오류'};
function error(message) { $('error').textContent = message; $('error').hidden = !message; }
function controls() {
  const busy = latest.active || busyStates.has(latest.status) || pending || showingWarning;
  $('fields').disabled = busy || !connected || !supportsSpeedModes;
  $('login').disabled = busy || !connected;
  $('stop').disabled = !connected || pending || !latest.active || latest.status === 'stopping';
  $('save').disabled = !connected || pending || showingWarning || !previewReady || !latest.active || latest.status !== 'headless_review';
}
function render(state) {
  const previouslySupported = supportsSpeedModes;
  supportsSpeedModes = Array.isArray(state.speed_modes) && ['humanize','instant','custom'].every(mode => state.speed_modes.includes(mode));
  if (!supportsSpeedModes) error('새 입력 속도 기능을 사용하려면 기존 실행 콘솔을 종료한 뒤 web.cmd를 다시 실행해 주세요.');
  else if (!previouslySupported) error('');
  latest = state;
  $('badge').textContent = labels[state.status] || state.status;
  $('badge').className = 'badge' + (busyStates.has(state.status) ? ' active' : state.status === 'error' ? ' failed' : '');
  $('phase').textContent = state.status === 'idle' ? '준비되면 시작해 주세요' : state.phase;
  const descriptions = {idle:'리추얼을 선택하고 동료 이름을 입력하세요.',waiting_login:'Chrome 창에서 로그인하세요. 최대 5분 동안 기다립니다.',running:'자동 입력 중입니다. Chrome 화면을 함께 확인해 주세요.',review:'입력된 문장을 검토한 뒤 Chrome에서 직접 저장하세요.',logged_in:'로그인이 확인되었습니다. 실행할 리추얼을 선택하세요.',stopped:'이미 입력된 내용은 유지됩니다. 필요하면 직접 수정하세요.',stopping:'진행 중인 작업을 취소하고 있습니다.',error:'아래 로그와 Chrome 화면을 확인한 뒤 다시 시도하세요.'};
  $('status-description').textContent = ({headless_review:'아래 결과 화면을 확인하고 직접 저장하거나 실행을 중지하세요.',saving:'사용자 요청으로 저장 버튼을 누르고 있습니다.',submitted:'아래 결과 화면에서 저장 성공 여부를 확인하세요.'})[state.status] || descriptions[state.status] || '';
  $('status-icon').textContent = ({review:'✓',logged_in:'✓',error:'!',stopped:'■',waiting_login:'↗',running:'↻'})[state.status] || '◷';
  const percent = state.total ? Math.min(100, Math.round(state.step / state.total * 100)) : 0;
  $('progress').value = percent;
  $('percent').textContent = percent + '%';
  $('progress-label').textContent = state.total ? `${state.step} / ${state.total} 단계 · ${state.status === 'review' ? '입력 완료' : '완료한 단계 기준'}` : '리추얼 입력 전';
  const stage = state.status === 'review' ? 3 : state.status === 'logged_in' ? 2 : state.step > 0 || state.status === 'running' && state.phase.includes('입력') ? 2 : state.status === 'waiting_login' ? 1 : 0;
  [...$('steps').children].forEach((el,i) => el.className = state.status === 'idle' ? '' : i < stage ? 'done' : i === stage ? 'active' : '');
  const logKey = state.logs.map(log => log.id).join(',');
  if (logKey !== lastLog) {
    const container = $('logs');
    const atBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 40;
    const lines = state.logs.map(log => {
      const line = document.createElement('div'); line.className = 'log-line';
      const time = document.createElement('span'); time.className = 'log-time'; time.textContent = log.time;
      const message = document.createElement('span'); message.className = 'log-message'; message.textContent = log.message;
      line.append(time, message); return line;
    });
    container.replaceChildren(...lines); if (atBottom) container.scrollTop = container.scrollHeight;
    lastLog = logKey;
  }
  controls();
  if (!state.has_preview) {
    previewReady = false;
    $('preview-card').hidden = true;
    previewVersion = state.preview_version;
    if (previewUrl) { URL.revokeObjectURL(previewUrl); previewUrl = null; $('preview').removeAttribute('src'); }
  } else if (state.preview_version !== previewVersion) {
    previewReady = false;
    previewVersion = state.preview_version;
    loadPreview(state.id, state.preview_version);
  }
  controls();
}
async function loadPreview(jobId, version) {
  try {
    const response = await fetch('/api/preview', {headers:{'X-Control-Token':token},cache:'no-store',signal:AbortSignal.timeout(10000)});
    if (!response.ok) throw new Error('결과 화면을 불러오지 못했습니다.');
    const blob = await response.blob();
    if (latest.id !== jobId || latest.preview_version !== version || !latest.has_preview) return;
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = URL.createObjectURL(blob);
    $('preview').onload = () => { previewReady = latest.id === jobId && latest.preview_version === version; controls(); };
    $('preview').onerror = () => { previewReady = false; previewVersion = -1; controls(); };
    $('preview').src = previewUrl;
    $('preview-card').hidden = false; $('preview-error').hidden = true;
  } catch (e) {
    if (latest.id !== jobId || latest.preview_version !== version) return;
    previewVersion = -1; $('preview-card').hidden = false;
    $('preview-error').textContent = e.message; $('preview-error').hidden = false;
  }
}
function askWarning(save, settings = '') {
  if (showingWarning) return Promise.resolve(false);
  showingWarning = true; controls();
  $('warning-title').textContent = save ? '입력 내용을 확인하셨나요?' : '실행 전 주의사항';
  $('warning-message').textContent = '이 프로그램 사용으로 평가 점수 하락 등 불이익이 발생하더라도 개발자는 책임을 지지 않습니다.';
  $('warning-detail').textContent = save ? '결과 화면을 검토해 주세요. 확인하면 해당 사이트의 최종 저장 버튼을 누릅니다.' : '사용 여부와 입력 내용 확인에 대한 책임은 사용자에게 있습니다.';
  $('warning-settings').textContent = settings;
  $('warning-confirm').textContent = save ? '확인한 내용 저장' : '확인하고 실행';
  const dialog = $('warning-dialog'); dialog.returnValue = '';
  return new Promise(resolve => {
    dialog.addEventListener('close', () => { showingWarning = false; controls(); resolve(dialog.returnValue === 'confirm'); }, {once:true});
    dialog.showModal();
  });
}
async function api(path, body) {
  const response = await fetch(path, {method:body === undefined ? 'GET':'POST', headers:{'X-Control-Token':token,...(body === undefined ? {} : {'Content-Type':'application/json'})}, body:body === undefined ? undefined:JSON.stringify(body), signal:AbortSignal.timeout(10000), cache:'no-store'});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '요청을 처리하지 못했습니다.');
  return data;
}
async function action(path, body) {
  if (pending) return;
  pending = true; controls(); error('');
  try { render(await api(path,body)); }
  catch (e) { error(e.message); }
  finally { pending = false; controls(); }
}
$('ritual-form').addEventListener('submit', async event => {
  event.preventDefault();
  const raw = $('names').value.trim();
  const names = raw.replaceAll(',', ' ').split(/\s+/u).filter(Boolean);
  if (names.length < 1 || names.length > 3 || names.some(n => n.length > 30)) { error('동료 이름을 1~3명, 각 30자 이내로 입력해 주세요.'); return; }
  const delay = Number($('delay').value);
  const speed = selectedSpeed();
  if (speed === 'custom' && ($('delay').value === '' || !Number.isInteger(delay) || delay < 0 || delay > 3000)) { error('딜레이를 0~3000ms 정수로 설정해 주세요.'); return; }
  const config = {mode:document.querySelector('input[name="mode"]:checked').value,names:raw,headless:$('headless').checked,delay_ms:speed === 'custom' ? delay : 0,speed_mode:speed};
  const speedLabel = ({humanize:'Humanize · 6~12초 무작위 대기',instant:'Instant · 추가 대기 없음',custom:`직접 설정 · ${delay}ms`})[speed];
  if (!await askWarning(false, `${config.headless ? '헤드리스' : 'Chrome 창'} 실행 · ${speedLabel}${config.headless ? ' · 결과 화면에서 직접 저장' : ''}`)) return;
  action('/api/start', config);
});
$('save').addEventListener('click', async () => { if (await askWarning(true)) action('/api/save',{}); });
$('login').addEventListener('click', () => action('/api/start',{mode:'login',names:''}));
$('stop').addEventListener('click', () => action('/api/stop',{}));
document.querySelectorAll('input[name="mode"]').forEach(input => input.addEventListener('change', () => {
  $('mode-note').textContent = input.value === 'close' ? '오늘 아침 리추얼을 먼저 저장해야 마무리를 실행할 수 있습니다.' : '기존 아침 리추얼의 호흡 단계는 시작 직후 종료됩니다.';
}));
$('download').addEventListener('click', () => {
  const text = latest.logs.map(log => `[${log.time}] ${log.message}`).join('\n');
  const url = URL.createObjectURL(new Blob(['\ufeff',text],{type:'text/plain;charset=utf-8'}));
  const a = document.createElement('a'); a.href = url; a.download = 'auto-litural-log.txt'; a.click();
  setTimeout(() => URL.revokeObjectURL(url),1000);
});
async function poll() {
  try { const state = await api('/api/status'); if (!connected) error(''); connected = true; render(state); }
  catch { connected = false; controls(); error('서버에 연결할 수 없습니다. web.cmd 실행 상태를 확인하고, 서버를 재시작했다면 화면을 새로 고쳐 주세요.'); }
  finally { setTimeout(poll,1000); }
}
controls(); poll();
