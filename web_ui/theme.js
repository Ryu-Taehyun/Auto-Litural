'use strict';
(() => {
  const read = key => { try { return localStorage.getItem(key); } catch { return null; } };
  function set(theme, persist = true) {
    if (!['dark', 'light'].includes(theme)) return;
    document.documentElement.dataset.theme = theme;
    if (persist) { try { localStorage.setItem('AutoLitural.theme', theme); } catch {} }
    const button = document.getElementById('theme-toggle');
    if (button) {
      const label = theme === 'dark' ? '라이트 모드' : '다크 모드';
      button.setAttribute('aria-label', label + '로 전환');
      button.setAttribute('aria-pressed', String(theme === 'dark'));
      document.getElementById('theme-label').textContent = label;
      document.getElementById('theme-icon').textContent = theme === 'dark' ? '☀' : '☾';
    }
  }
  const saved = read('AutoLitural.theme');
  const initial = ['dark', 'light'].includes(saved) ? saved : matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  set(initial, false);
  window.AutoLituralTheme = {set, read};
  document.addEventListener('DOMContentLoaded', () => set(document.documentElement.dataset.theme, false), {once:true});
})();
