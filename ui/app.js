'use strict';
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const DEFAULT_PROFILES = [{label: 'armin0411', url: 'https://github.com/armin0411', kind: 'github'}];
let state = {apps: [], busy: false}, token = '', filter = 'all', prefsLoaded = false;
let view = localStorage.getItem('launchcraft-view') === 'list' ? 'list' : 'grid';
let zoom = Math.max(.75, Math.min(1.75, Number(localStorage.getItem('launchcraft-zoom')) || 1));
let profiles = DEFAULT_PROFILES.slice();
let appDetails = {};
let shownApps = [];
let events;
let aiRevision = 0;
let refreshProgress = null;
const aiFields = ['ai_running', 'ai_phase', 'ai_outcome', 'ai_report', 'pending_fixes', 'term_cwd'];
const terminal = ['Complete', 'Cancelled', 'Error'];
const PROFILE_ICONS = {
  github: '<svg viewBox="0 0 16 16" width="15" height="15" fill="currentColor" aria-hidden="true"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z"/></svg>',
  x: '<svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor" aria-hidden="true"><path d="M12.6.75h2.454l-5.36 6.142L16 15.25h-4.937l-3.867-5.07-4.425 5.07H.316l5.733-6.57L0 .75h5.063l3.495 4.633L12.601.75Zm-.86 13.028h1.36L4.323 2.145H2.865l8.875 11.633Z"/></svg>',
  youtube: '<svg viewBox="0 0 16 16" width="15" height="15" fill="currentColor" aria-hidden="true"><path d="M15.84 4.8a2 2 0 0 0-1.41-1.41C13.18 3.05 8 3.05 8 3.05s-5.18 0-6.43.34A2 2 0 0 0 .16 4.8 21 21 0 0 0 0 8a21 21 0 0 0 .16 3.2 2 2 0 0 0 1.41 1.41c1.25.34 6.43.34 6.43.34s5.18 0 6.43-.34a2 2 0 0 0 1.41-1.41A21 21 0 0 0 16 8a21 21 0 0 0-.16-3.2ZM6.4 10.12V5.88L10.56 8 6.4 10.12Z"/></svg>',
  discord: '<svg viewBox="0 0 16 16" width="15" height="15" fill="currentColor" aria-hidden="true"><path d="M13.545 2.907a13.2 13.2 0 0 0-3.257-1.011.05.05 0 0 0-.052.025c-.141.25-.297.577-.406.833a12.2 12.2 0 0 0-3.658 0 8 8 0 0 0-.412-.833.05.05 0 0 0-.052-.025c-1.125.194-2.22.534-3.257 1.011a.04.04 0 0 0-.021.018C.356 6.024-.213 9.047.066 12.032q.003.022.021.037a13.3 13.3 0 0 0 3.995 2.02.05.05 0 0 0 .056-.019q.463-.63.818-1.329a.05.05 0 0 0-.01-.059l-.018-.011a9 9 0 0 1-1.248-.595.05.05 0 0 1-.02-.066l.015-.019q.127-.095.248-.195a.05.05 0 0 1 .051-.007c2.619 1.196 5.454 1.196 8.041 0a.05.05 0 0 1 .053.007q.121.1.248.195a.05.05 0 0 1-.004.085 8 8 0 0 1-1.249.594.05.05 0 0 0-.03.03.05.05 0 0 0 .003.041c.24.465.515.909.817 1.329a.05.05 0 0 0 .056.019 13.2 13.2 0 0 0 4.001-2.02.05.05 0 0 0 .021-.037c.334-3.451-.559-6.449-2.366-9.106a.03.03 0 0 0-.02-.019m-8.198 7.307c-.789 0-1.438-.724-1.438-1.612s.637-1.613 1.438-1.613c.807 0 1.45.73 1.438 1.613 0 .888-.637 1.612-1.438 1.612m5.316 0c-.788 0-1.438-.724-1.438-1.612s.637-1.613 1.438-1.613c.807 0 1.451.73 1.438 1.613 0 .888-.631 1.612-1.438 1.612"/></svg>',
  linkedin: '<svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor" aria-hidden="true"><path d="M0 1.146C0 .513.526 0 1.175 0h13.65C15.474 0 16 .513 16 1.146v13.708c0 .633-.526 1.146-1.175 1.146H1.175C.526 16 0 15.487 0 14.854zm4.943 12.248V6.169H2.542v7.225zm-1.2-8.212c.837 0 1.358-.554 1.358-1.248-.015-.709-.52-1.248-1.342-1.248S2.4 3.226 2.4 3.934c0 .694.521 1.248 1.327 1.248zm4.908 8.212V9.359c0-.216.016-.432.08-.586.173-.431.568-.878 1.232-.878.869 0 1.216.662 1.216 1.634v3.865h2.401V9.25c0-2.22-1.184-3.252-2.764-3.252-1.274 0-1.845.7-2.165 1.193v.025h-.016l.016-.025V6.169h-2.4c.03.678 0 7.225 0 7.225z"/></svg>',
  website: '<svg viewBox="0 0 16 16" width="15" height="15" fill="currentColor" aria-hidden="true"><path d="M0 8a8 8 0 1 1 16 0A8 8 0 0 1 0 8m7.5-6.923c-.67.204-1.335.82-1.887 1.855A8 8 0 0 0 5.145 4H7.5zM4.09 4a9.3 9.3 0 0 1 .64-1.539 7 7 0 0 1 .597-.933A7.03 7.03 0 0 0 2.255 4zm-.582 3.5c.03-.877.138-1.718.312-2.5H1.674a7 7 0 0 0-.656 2.5zM4.847 5a12.5 12.5 0 0 0-.338 2.5H7.5V5zM8.5 5v2.5h2.99a12.5 12.5 0 0 0-.337-2.5zM4.51 8.5a12.5 12.5 0 0 0 .337 2.5H7.5V8.5zm3.99 0V11h2.653c.187-.765.306-1.608.338-2.5zM5.145 12q.208.58.468 1.068c.552 1.035 1.218 1.65 1.887 1.855V12zm.182 2.472a7 7 0 0 1-.597-.933A9.3 9.3 0 0 1 4.09 12H2.255a7 7 0 0 0 3.072 2.472M3.82 11a13.7 13.7 0 0 1-.312-2.5h-2.49c.062.89.291 1.733.656 2.5zm6.853 3.472A7 7 0 0 0 13.745 12H11.91a9.3 9.3 0 0 1-.64 1.539 7 7 0 0 1-.597.933M8.5 12v2.923c.67-.204 1.335-.82 1.887-1.855q.26-.487.468-1.068zm3.68-1h2.146c.365-.767.594-1.61.656-2.5h-2.49a13.7 13.7 0 0 1-.312 2.5m2.802-3.5a7 7 0 0 0-.656-2.5H12.18c.174.782.282 1.623.312 2.5zM11.27 2.461c.247.464.462.98.64 1.539h1.835a7 7 0 0 0-3.072-2.472c.218.284.418.598.597.933M10.855 4a8 8 0 0 0-.468-1.068C9.835 1.897 9.17 1.282 8.5 1.077V4z"/></svg>',
  custom: '<svg viewBox="0 0 16 16" width="15" height="15" fill="currentColor" aria-hidden="true"><path d="M4.715 6.542 3.343 7.914a3 3 0 1 0 4.243 4.243l1.828-1.829A3 3 0 0 0 8.586 5.5L8 6.086a1 1 0 0 0-.154.199 2 2 0 0 1 .861 3.337L6.88 11.45a2 2 0 1 1-2.83-2.83l.793-.792a4 4 0 0 1-.128-1.287z"/><path d="M6.586 4.672A3 3 0 0 0 7.414 9.5l.775-.776a2 2 0 0 1-.896-3.346L9.12 3.55a2 2 0 1 1 2.83 2.83l-.793.792c.112.42.155.855.128 1.287l1.372-1.372a3 3 0 1 0-4.243-4.243z"/></svg>',
};
function renderProfiles() {
  const el = $('#profile-links');
  if (!el) return;
  el.innerHTML = profiles.map((p, i) => `<a class="footer-icon" href="${escapeHTML(p.url)}" target="_blank" rel="noopener noreferrer" aria-label="${escapeHTML(p.label)}" title="${escapeHTML(p.label)} — ${escapeHTML(p.url)}">${PROFILE_ICONS[p.kind] || PROFILE_ICONS.custom}</a>`).join('');
}
function savePref(patch) {
  if (!token) return;
  fetch('/api/prefs', {method: 'POST', headers: {'Content-Type':'application/json', 'X-LaunchCraft-Token': token}, body: JSON.stringify(patch)}).catch(() => {});
}
const THEMES = [
  {id:'default', name:'Default Dark', light:false, bg:'#262a34', canvasEnd:'#1e222b', surface:'#0f1116', sunken:'#060607', hover:'#232833', ink:'#f4f4f6', inkSoft:'#b4b7c2', strong:'#ffffff', muted:'#93949d', line:'#3e424e', accent:'#2d81ff', green:'#7bd5a7', red:'#ff817e'},
  {id:'light', name:'Default Light', light:true, bg:'#dbd8d1', canvasEnd:'#d1cec6', surface:'#fdfcfa', sunken:'#e7e6e2', hover:'#f2f0ea', ink:'#1e1f24', inkSoft:'#494b54', strong:'#060607', muted:'#62636c', line:'#b8b6af', accent:'#2d81ff', green:'#167846', red:'#b32327'},
  {id:'catppuccin', name:'Catppuccin Mocha', light:false, bg:'#3b304c', canvasEnd:'#2f3352', surface:'#171524', sunken:'#100e1a', hover:'#38324c', ink:'#f2e7fc', inkSoft:'#dcd0eb', strong:'#ffffff', muted:'#cbbfd8', line:'#544968', accent:'#d8b5ff', green:'#ade4bc', red:'#f7b1c2'},
  {id:'nord', name:'Nord', light:false, bg:'#394150', canvasEnd:'#303846', surface:'#181d26', sunken:'#11151c', hover:'#3b4455', ink:'#eceff4', inkSoft:'#d8dee9', strong:'#ffffff', muted:'#aeb8cc', line:'#4e586d', accent:'#88c0d0', green:'#a3be8c', red:'#bf616a'},
  {id:'gruvbox', name:'Gruvbox', light:false, bg:'#39342c', canvasEnd:'#312c25', surface:'#171410', sunken:'#100e0b', hover:'#3b3429', ink:'#faebca', inkSoft:'#e6d2a9', strong:'#fff6e0', muted:'#cabb9c', line:'#605340', accent:'#f3bb61', green:'#b9ca79', red:'#ffa492'},
  {id:'tokyo-night', name:'Tokyo Night', light:false, bg:'#243a54', canvasEnd:'#342a4c', surface:'#101524', sunken:'#0b0f1a', hover:'#26314a', ink:'#e8edff', inkSoft:'#cad5f2', strong:'#ffffff', muted:'#b8c5e3', line:'#415272', accent:'#a7c5ff', green:'#a7d598', red:'#ffafb9'},
  {id:'dracula', name:'Dracula', light:false, bg:'#3d2b44', canvasEnd:'#2b2b42', surface:'#17121f', sunken:'#100c16', hover:'#3a2d43', ink:'#fff0fa', inkSoft:'#ebd6e6', strong:'#ffffff', muted:'#cfbcd2', line:'#5c425c', accent:'#e9a1f2', green:'#8ee6ae', red:'#ffa0aa'},
  {id:'miasma', name:'Miasma', light:false, bg:'#3d3827', canvasEnd:'#2c3b31', surface:'#161b13', sunken:'#0f130d', hover:'#363c2d', ink:'#f2edd1', inkSoft:'#d9cba5', strong:'#fffbe6', muted:'#cccdb9', line:'#545c44', accent:'#c8d282', green:'#b6d4ab', red:'#f4bfb2'},
  {id:'vscode-dark', name:'VS Code Dark', light:false, bg:'#242e3d', canvasEnd:'#202937', surface:'#0d131c', sunken:'#080c13', hover:'#223040', ink:'#edf4fb', inkSoft:'#c4d4e2', strong:'#ffffff', muted:'#b5c6d5', line:'#3f5065', accent:'#8acbff', green:'#91d4a8', red:'#ffb0a4'},
  {id:'solarized-dark', name:'Solarized Dark', light:false, bg:'#0f444f', canvasEnd:'#0c3d47', surface:'#031c22', sunken:'#021419', hover:'#0f4049', ink:'#f4eed8', inkSoft:'#d8d3bf', strong:'#fdf8e6', muted:'#a3b8b6', line:'#2a6068', accent:'#2aa198', green:'#859900', red:'#dc322f'},
  {id:'catppuccin-latte', name:'Catppuccin Latte', light:true, bg:'#e1d4de', canvasEnd:'#d3cfe8', surface:'#fcfafe', sunken:'#e4dceb', hover:'#f1ebf8', ink:'#40334f', inkSoft:'#554564', strong:'#251b30', muted:'#63546f', line:'#c4b8d1', accent:'#773999', green:'#336444', red:'#9a374d'},
  {id:'nord-light', name:'Nord Light', light:true, bg:'#d7e3eb', canvasEnd:'#c8d7e3', surface:'#fafcfe', sunken:'#dde7ee', hover:'#edf4f9', ink:'#22384b', inkSoft:'#354f63', strong:'#112230', muted:'#4a6171', line:'#afc3d0', accent:'#176479', green:'#406745', red:'#a43648'},
  {id:'gruvbox-light', name:'Gruvbox Light', light:true, bg:'#e3d2ab', canvasEnd:'#dac69b', surface:'#fef9ed', sunken:'#e5d5ae', hover:'#f4ebd2', ink:'#413321', inkSoft:'#57442e', strong:'#261d12', muted:'#69563d', line:'#c5b28b', accent:'#8a471c', green:'#4e601c', red:'#a13224'},
  {id:'tokyo-day', name:'Tokyo Day', light:true, bg:'#d0dfef', canvasEnd:'#d5ceeb', surface:'#fafbfe', sunken:'#dce3f2', hover:'#ecf1fc', ink:'#293956', inkSoft:'#435271', strong:'#141e33', muted:'#515e75', line:'#b3bfd8', accent:'#3b54a6', green:'#366744', red:'#a13853'},
  {id:'vscode-light', name:'VS Code Light', light:true, bg:'#d9e1ec', canvasEnd:'#d1dbe8', surface:'#fcfdff', sunken:'#dde4ee', hover:'#eef3fa', ink:'#1d3048', inkSoft:'#364c65', strong:'#0d1929', muted:'#4e6277', line:'#b7c5d8', accent:'#075da7', green:'#266637', red:'#b32f35'},
  {id:'miasma-light', name:'Miasma Light', light:true, bg:'#ded7bc', canvasEnd:'#cfd9c1', surface:'#fcfcf4', sunken:'#dde0cb', hover:'#f0f1e0', ink:'#353a25', inkSoft:'#4e543a', strong:'#1f2314', muted:'#575d45', line:'#b6bea0', accent:'#4c6121', green:'#356449', red:'#973e34'},
];
let currentTheme = localStorage.getItem('launchcraft-theme') || 'catppuccin';
if (!THEMES.some(t => t.id === currentTheme)) currentTheme = 'catppuccin';

function applyTheme(id, animate = true, persist = true) {
  const t = THEMES.find(x => x.id === id) || THEMES.find(x => x.id === 'catppuccin') || THEMES[0];
  const prevBg = getComputedStyle(document.documentElement).getPropertyValue('--bg').trim() || '#3b304c';
  const prevEnd = getComputedStyle(document.documentElement).getPropertyValue('--canvas-end').trim() || prevBg;
  if (animate && currentTheme !== t.id && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    let wipe = $('#theme-wipe');
    if (!wipe) {
      wipe = document.createElement('div');
      wipe.id = 'theme-wipe';
      wipe.innerHTML = '<div class="wipe-half wipe-left"></div><div class="wipe-half wipe-right"></div>';
      document.body.appendChild(wipe);
    }
    const bg = `linear-gradient(135deg, ${prevBg}, ${prevEnd})`;
    wipe.querySelectorAll('.wipe-half').forEach(el => { el.style.background = bg; });
    wipe.classList.remove('active');
    void wipe.offsetWidth;
    wipe.classList.add('active');
  }
  currentTheme = t.id;
  document.body.classList.toggle('light', t.light);
  const root = document.documentElement.style;
  if (t.id === 'default' || t.id === 'light') {
    ['--bg','--canvas-end','--surface','--sunken','--hover','--ink','--ink-soft','--strong','--muted','--line','--accent','--green','--red'].forEach(k => root.removeProperty(k));
  } else {
    root.setProperty('--bg', t.bg);
    root.setProperty('--canvas-end', t.canvasEnd);
    root.setProperty('--surface', t.surface);
    root.setProperty('--sunken', t.sunken);
    root.setProperty('--hover', t.hover);
    root.setProperty('--ink', t.ink);
    root.setProperty('--ink-soft', t.inkSoft);
    root.setProperty('--strong', t.strong);
    root.setProperty('--muted', t.muted);
    root.setProperty('--line', t.line);
    root.setProperty('--accent', t.accent);
    root.setProperty('--green', t.green);
    root.setProperty('--red', t.red);
  }
  localStorage.setItem('launchcraft-theme', t.id);
  if (persist) savePref({theme: t.id});
}

function openThemePicker() {
  const saved = currentTheme;
  const lightThemes = THEMES.filter(t => t.light);
  const darkThemes = THEMES.filter(t => !t.light);
  const ordered = [...lightThemes, ...darkThemes];
  let idx = Math.max(0, ordered.findIndex(t => t.id === currentTheme));
  const renderOption = (t, i) => `
    <button type="button" class="theme-option ${i === idx ? 'selected' : ''}" data-idx="${i}" data-theme-id="${t.id}">
      <span class="theme-swatches" aria-hidden="true">
        <i style="background:${t.bg}"></i><i style="background:${t.surface}"></i><i style="background:${t.ink}"></i><i style="background:${t.accent}"></i>
      </span>
      <span class="theme-name">${escapeHTML(t.name)}</span>
      <span class="badge">${t.light ? 'LIGHT' : 'DARK'}</span>
    </button>`;
  const lightHTML = lightThemes.map((t, i) => renderOption(t, i)).join('');
  const darkHTML = darkThemes.map((t, i) => renderOption(t, lightThemes.length + i)).join('');
  showModal('Choose theme', `<p class="muted" style="margin:0 0 12px">Use arrow keys to preview and Enter to save, or click a theme to apply.</p><div class="theme-list" id="theme-list"><div class="theme-col">${lightHTML}</div><div class="theme-col">${darkHTML}</div></div>`);
  const list = $('#theme-list');
  const buttons = $$('.theme-option', list);
  let committed = false;
  const selectIdx = (nextIdx, animate = true) => {
    idx = (nextIdx + ordered.length) % ordered.length;
    buttons.forEach((b, i) => b.classList.toggle('selected', i === idx));
    buttons[idx]?.scrollIntoView({block: 'nearest'});
    applyTheme(ordered[idx].id, animate, false);
  };
  buttons[idx]?.scrollIntoView({block: 'nearest'});
  list.addEventListener('click', event => {
    const btn = event.target.closest('.theme-option');
    if (!btn) return;
    committed = true;
    applyTheme(ordered[Number(btn.dataset.idx)].id, true, true);
    $('#modal').close();
  });
  const onKey = event => {
    if (!$('#modal').open || !$('#theme-list')) return;
    if (event.key === 'ArrowDown') { event.preventDefault(); selectIdx(idx + 1, true); }
    else if (event.key === 'ArrowUp') { event.preventDefault(); selectIdx(idx - 1, true); }
    else if (event.key === 'ArrowRight') {
      event.preventDefault();
      if (idx < lightThemes.length) selectIdx(Math.min(lightThemes.length + idx, ordered.length - 1), true);
      else selectIdx(Math.min(idx - lightThemes.length, lightThemes.length - 1), true);
    } else if (event.key === 'ArrowLeft') {
      event.preventDefault();
      if (idx >= lightThemes.length) selectIdx(Math.min(idx - lightThemes.length, lightThemes.length - 1), true);
      else selectIdx(Math.min(lightThemes.length + idx, ordered.length - 1), true);
    } else if (event.key === 'Home') { event.preventDefault(); selectIdx(0, true); }
    else if (event.key === 'End') { event.preventDefault(); selectIdx(ordered.length - 1, true); }
    else if (event.key === 'Enter') { event.preventDefault(); committed = true; applyTheme(ordered[idx].id, true, true); $('#modal').close(); }
  };
  document.addEventListener('keydown', onKey);
  $('#modal').addEventListener('close', () => {
    document.removeEventListener('keydown', onKey);
    if (!committed) applyTheme(saved, false, false);
  }, {once: true});
}

function applyState(next) {
  if ((next.revision || 0) < (state.revision || 0)) return;
  if (next.revision < aiRevision) {
    for (const field of aiFields) next[field] = state[field];
  } else {
    aiRevision = next.revision || 0;
  }
  state = next;
  if (!state.refreshing) refreshProgress = null;
  if (!prefsLoaded && next.prefs) {
    prefsLoaded = true;
    if (next.prefs.view === 'list' || next.prefs.view === 'grid') setView(next.prefs.view, false);
    if (typeof next.prefs.theme === 'string' && THEMES.some(t => t.id === next.prefs.theme)) {
      applyTheme(next.prefs.theme, false, false);
    }
    if (typeof next.prefs.zoom === 'number') applyZoom(next.prefs.zoom, false);
    if (Array.isArray(next.prefs.profiles) && next.prefs.profiles.length) {
      profiles = next.prefs.profiles;
      renderProfiles();
    }
  }
  render();
}
function applyAiState(next) {
  if ((next.revision || 0) < aiRevision) return;
  aiRevision = next.revision || 0;
  for (const field of aiFields) {
    if (field in next) state[field] = next[field];
  }
  renderAi();
}
const pendingOps = new Map();
function setNotice(message, error = false) {
  $('#notice-text').textContent = message;
  $('#notice').classList.toggle('error', error);
}
async function post(path, data = {}, {timeoutMs = 5000} = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch('/api/' + path, {
      method: 'POST',
      headers: {'Content-Type':'application/json', 'X-LaunchCraft-Token': token},
      body: JSON.stringify(data),
      signal: controller.signal,
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Request failed');
    return result;
  } catch (error) {
    if (error.name === 'AbortError') {
      throw new Error(`Request timed out after ${Math.round(timeoutMs / 1000)}s — server did not respond in time.`);
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}
async function api(path, data, options) {
  const result = await post(path, data, options);
  if (Array.isArray(result.apps)) applyState(result);
  else if ('ai_running' in result) applyAiState(result);
  return result;
}
async function runAppOp(id, op, fn) {
  pendingOps.set(id, op);
  render();
  try {
    return await fn();
  } catch (error) {
    setNotice(error.message, true);
  } finally {
    pendingOps.delete(id);
    render();
  }
}
function applyZoom(value, persist = true) {
  zoom = Math.round(Math.max(.75, Math.min(1.75, value)) * 100) / 100;
  document.documentElement.style.setProperty('--zoom', zoom);
  localStorage.setItem('launchcraft-zoom', zoom);
  $('#zoom-reset').textContent = Math.round(zoom * 100) + '%';
  $('#zoom-out').disabled = zoom <= .75;
  $('#zoom-in').disabled = zoom >= 1.75;
  if (persist) savePref({zoom});
}
function setView(value, persist = true) {
  view = value;
  localStorage.setItem('launchcraft-view', view);
  $('#grid-view').setAttribute('aria-pressed', String(view === 'grid'));
  $('#list-view').setAttribute('aria-pressed', String(view === 'list'));
  if (persist) savePref({view});
  renderApps();
}
function versions(a) {
  if (a.source.type === 'local') {
    return `<span class="version mono">${a.installed ? 'local build' : 'not found'}</span>`;
  }
  return `<span class="version mono">${escapeHTML(a.installed || '—')}<span class="arrow">→</span><span class="latest">${escapeHTML(a.latest || 'not checked')}</span></span>`;
}
function statusBadge(a) {
  const pending = pendingOps.get(a.id);
  if (pending === 'cancel') return '<span class="status-pill is-busy">Cancelling…</span>';
  if (pending === 'install') return `<span class="status-pill is-busy">${a.update ? 'Updating…' : 'Starting…'}</span>`;
  if (pending === 'uninstall') return '<span class="status-pill is-busy">Uninstalling…</span>';
  const job = a.job;
  if (job && !terminal.includes(job.status)) {
    return `<span class="status-pill is-busy">${escapeHTML(job.status)}</span>`;
  }
  if (job?.status === 'Error') return '<span class="status-pill is-error">ERROR · RETRY</span>';
  if (a.source.type === 'local' && a.installed) return '<span class="status-pill is-local">LOCAL APP</span>';
  if (a.compatible === false) return '<span class="status-pill is-incompatible">NOT COMPATIBLE</span>';
  if (a.update) return '<span class="status-pill is-update">UPDATE AVAILABLE</span>';
  if (a.installed) return '<span class="status-pill is-installed">INSTALLED</span>';
  if (a.hidden) return '<span class="status-pill is-hidden">HIDDEN</span>';
  if (a.build_info?.from_source) return '<span class="status-pill is-build">REQUIRES BUILD</span>';
  return '<span class="status-pill is-available">AVAILABLE TO INSTALL</span>';
}
function action(a) {
  const pending = pendingOps.get(a.id);
  const job = a.job;
  if (pending === 'cancel') {
    return `<div class="progress-group"><div class="progress-info"><div class="progress-text"><span>Cancelling…</span><span></span></div><div class="progress-track" role="progressbar" aria-label="Cancelling" aria-valuemin="0" aria-valuemax="100"><div class="progress-fill indeterminate"></div></div></div><button class="cancel" data-action="cancel" disabled>Cancelling…</button></div>`;
  }
  if (pending === 'install') {
    const label = a.update ? 'Starting update…' : 'Starting…';
    return `<div class="progress-group"><div class="progress-info"><div class="progress-text"><span>${label}</span><span></span></div><div class="progress-track" role="progressbar" aria-label="${label}" aria-valuemin="0" aria-valuemax="100"><div class="progress-fill indeterminate"></div></div></div><button class="cancel" data-action="cancel" disabled>Cancel</button></div>`;
  }
  if (pending === 'open') {
    return '<button class="action is-open" data-action="open" disabled>OPENING…</button>';
  }
  if (pending === 'uninstall') {
    return '<button class="action" disabled>UNINSTALLING…</button>';
  }
  if (job && !terminal.includes(job.status)) {
    const percent = typeof job.percent === 'number' ? Math.max(0, Math.min(100, job.percent)) : null;
    return `<div class="progress-group"><div class="progress-info"><div class="progress-text"><span>${escapeHTML(job.status)}</span><span>${percent === null ? '' : Math.round(percent) + '%'}</span></div><div class="progress-track" role="progressbar" aria-label="${escapeHTML(job.status)}" ${percent === null ? '' : 'aria-valuenow="' + percent + '"'} aria-valuemin="0" aria-valuemax="100"><div class="progress-fill ${percent === null ? 'indeterminate' : ''}" ${percent === null ? '' : 'style="width:' + percent + '%"'}></div></div></div><button class="cancel" data-action="cancel" title="Cancel pending work; active package transactions finish safely">Cancel</button></div>`;
  }
  if (a.compatible === false && !a.installed) {
    return '<button class="action is-incompatible" disabled>INSTALL</button>';
  }
  const isBuild = !a.installed && !!a.build_info?.from_source;
  const op = a.installed && !a.update ? 'open' : isBuild ? 'build' : 'install';
  const cls = a.update ? 'is-update primary' : a.installed ? 'is-open' : isBuild ? 'is-build' : 'is-install';
  const label = a.update ? 'UPDATE ' + a.latest : a.installed ? 'OPEN ↗' : isBuild ? 'BUILD' : 'INSTALL';
  return `<button class="action ${cls}" data-action="${op}" ${state.refreshing && op !== 'open' ? 'disabled' : ''}>${escapeHTML(label)}</button>`;
}
function menu(a) {
  const isLocal = a.source.type === 'local';
  const repo = isLocal ? a.website : a.source.type === 'github_release' ? 'https://github.com/' + a.source.repo : a.source.type === 'aur' ? 'https://aur.archlinux.org/packages/' + encodeURIComponent(a.source.package) : a.source.type === 'winget' ? 'https://winstall.app/apps/' + encodeURIComponent(a.source.package) : 'https://archlinux.org/packages/?q=' + encodeURIComponent(a.source.package);
  const jobActive = a.job && !terminal.includes(a.job.status) && state.busy;
  return `<div class="menu-wrap"><button class="menu-button" data-action="menu" aria-label="Menu for ${escapeHTML(a.name)}" aria-expanded="false">···</button><div class="app-menu" hidden><button data-action="details">Details / Release notes</button><a href="${escapeHTML(repo)}" target="_blank" rel="noopener noreferrer">${isLocal ? 'Website ↗' : 'Open Repo ↗'}</a><button data-action="hide">${a.hidden ? 'Unhide' : 'Hide'} app</button><button data-action="uninstall" class="danger" ${isLocal || !a.installed || jobActive ? 'disabled' : ''}>Uninstall</button><button data-action="clean-uninstall" class="danger" ${isLocal || !a.installed || jobActive ? 'disabled' : ''}>Clean uninstall…</button></div></div>`;
}
function formatReleased(a) {
  const raw = a.release?.published_at;
  if (!raw) return '';
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleDateString('en-US', {month: 'short', day: 'numeric', year: 'numeric'});
}
function formatAppName(name) {
  const s = String(name ?? '');
  if (s.endsWith('Craft') && s.length > 5) {
    return `${escapeHTML(s.slice(0, -5))}<span class="name-accent">Craft</span>`;
  }
  return `<span class="name-main">${escapeHTML(s)}</span>`;
}
function appIdentity(a, withTagline = false) {
  const icon = a.icon
    ? `<div class="app-icon has-img" aria-hidden="true"><img src="${escapeHTML(a.icon)}" alt="" loading="lazy"></div>`
    : `<div class="app-icon" aria-hidden="true">${escapeHTML(a.name.slice(0,1).toUpperCase())}</div>`;
  const sub = withTagline
    ? `<p class="tagline" title="${escapeHTML(a.tagline)}">${escapeHTML(a.tagline)}</p>`
    : `<span class="publisher">${escapeHTML(a.publisher)}</span>`;
  return `<div class="app-top">${icon}<div class="app-title"><h3>${formatAppName(a.name)}</h3>${sub}</div></div>`;
}
function renderApps() {
  const query = $('#search').value.toLocaleLowerCase();
  const apps = state.apps.filter(a => {
    if (filter === 'hidden' ? !a.hidden : a.hidden) return false;
    if (filter === 'installed' && !a.installed) return false;
    if (filter === 'updates' && !a.update) return false;
    return [a.name, a.publisher, a.category, a.tagline, a.id].join(' ').toLocaleLowerCase().includes(query);
  });
  const sort = $('#sort').value;
  const cmp = (a,b) => (sort === 'updates' ? Number(b.update) - Number(a.update) : sort === 'category' ? a.category.localeCompare(b.category) : 0) || a.name.localeCompare(b.name);
  apps.sort(cmp);
  const split = filter === 'all';
  const installedList = split ? apps.filter(a => a.installed) : apps;
  const uninstalledList = split ? apps.filter(a => !a.installed) : [];
  shownApps = split ? [...installedList, ...uninstalledList] : apps;
  const container = $('#apps');
  container.className = view;
  const renderCard = (a, idx) => {
    const accent = /^#[0-9a-f]{6}$/i.test(a.accent) ? a.accent : '#2d81ff';
    const meta = appDetails[a.id] || {};
    const accent2 = /^#[0-9a-f]{6}$/i.test(meta.accent2 || '') ? meta.accent2 : accent;
    const fadeA = meta.accent2 ? '5%' : `${3 + (idx % 2)}%`;
    const fadeB = meta.accent2 ? '2%' : `${1 + (idx % 2)}%`;
    const badge = `<span class="badge">${escapeHTML(a.category)}</span>`;
    const released = formatReleased(a);
    const releasedLine = released ? `<span class="last-updated">Last updated: ${escapeHTML(released)}</span>` : '';
    const tagline = `<p class="tagline">${escapeHTML(a.tagline)}</p>`;
    const isDownloading = !!(a.job && !terminal.includes(a.job.status));
    const cardState = [a.installed ? 'is-installed' : 'is-not-installed', meta.accent2 ? 'has-duo-fade' : '', isDownloading ? 'is-downloading' : ''].filter(Boolean).join(' ');
    const content = view === 'list'
      ? `<div class="card-inner">${appIdentity(a, true)}<div class="status-cell">${statusBadge(a)}</div><div class="category-cell">${badge}<span class="publisher">${escapeHTML(released || a.publisher)}</span></div>${versions(a)}<div class="list-action">${action(a)}</div>${menu(a)}</div>`
      : `<div class="card-inner"><div class="app-top">${appIdentity(a, false).replace(/^<div class="app-top">|<\/div>$/g,'')}${menu(a)}</div>${tagline}${releasedLine}<div class="app-meta">${badge}${versions(a)}</div></div><div class="card-bottom">${statusBadge(a)}${action(a)}</div>`;
    return `<article class="card ${cardState}" data-id="${escapeHTML(a.id)}" style="--app-accent:${accent};--app-accent2:${accent2};--fade-a:${fadeA};--fade-b:${fadeB}">${content}</article>`;
  };
  let html = view === 'list' && shownApps.length ? '<div class="table-head" aria-hidden="true"><span>APP</span><span>STATUS</span><span>CATEGORY / RELEASED</span><span>INSTALLED → LATEST</span><span style="text-align:right">ACTION</span><span></span></div>' : '';
  if (split && installedList.length && uninstalledList.length) {
    html += installedList.map(renderCard).join('');
    html += `<div class="section-divider" aria-label="Not installed"><span>NOT INSTALLED</span><span>${uninstalledList.length}</span></div>`;
    html += uninstalledList.map(renderCard).join('');
  } else {
    html += shownApps.map(renderCard).join('');
  }
  container.innerHTML = html;
  $('#empty').hidden = apps.length !== 0;
}
function updateAppCard(a) {
  const card = $(`.card[data-id="${CSS.escape(a.id)}"]`, $('#apps'));
  if (!card) return;
  const active = !!(a.job && !terminal.includes(a.job.status));
  card.classList.toggle('is-downloading', active);
  const statusEl = $('.status-cell', card);
  if (statusEl) {
    statusEl.innerHTML = statusBadge(a);
  } else {
    const pill = $('.card-bottom .status-pill', card);
    if (pill) pill.outerHTML = statusBadge(a);
  }
  const job = a.job;
  const existingGroup = $('.progress-group', card);
  if (active && existingGroup && !pendingOps.get(a.id)) {
    const percent = typeof job.percent === 'number' ? Math.max(0, Math.min(100, job.percent)) : null;
    const spans = $$('.progress-text span', existingGroup);
    if (spans[0]) spans[0].textContent = job.status;
    if (spans[1]) spans[1].textContent = percent === null ? '' : Math.round(percent) + '%';
    const fill = $('.progress-fill', existingGroup);
    if (fill) {
      fill.classList.toggle('indeterminate', percent === null);
      fill.style.width = percent === null ? '' : percent + '%';
    }
    return;
  }
  const listAction = $('.list-action', card);
  if (listAction) {
    listAction.innerHTML = action(a);
  } else {
    const bottom = $('.card-bottom', card);
    if (bottom) bottom.innerHTML = statusBadge(a) + action(a);
  }
}
function formatCheckedAgo(apps) {
  const latest = apps.reduce((max, a) => Math.max(max, a.release?.checked || 0), 0);
  if (!latest) return 'NOT CHECKED YET · USING GITHUB API AND SYSTEM PACKAGES';
  const mins = Math.max(0, Math.floor((Date.now() / 1000 - latest) / 60));
  const ago = mins < 1 ? 'JUST NOW' : mins < 60 ? `${mins} MIN AGO` : `${Math.floor(mins / 60)} HR AGO`;
  return `CHECKED ${ago} · USING GITHUB API AND SYSTEM PACKAGES`;
}
function render() {
  const visible = state.apps.filter(a => !a.hidden);
  const installed = visible.filter(a => a.installed).length;
  const updates = visible.filter(a => a.update).length;
  $('#counts').innerHTML = `<div class="count"><strong>${visible.length.toString().padStart(2,'0')}</strong><span>IN LIBRARY</span></div><div class="count"><strong>${installed.toString().padStart(2,'0')}</strong><span>INSTALLED</span></div><div class="count update"><strong>${updates.toString().padStart(2,'0')}</strong><span>UPDATES</span></div>`;
  $('#all-count').textContent = visible.length;
  $('#update-count').textContent = updates || '';
  $('#checked-info').textContent = formatCheckedAgo(state.apps);
  renderRefresh();
  $('#update-all').disabled = state.busy || state.refreshing || !updates;
  $('#warnings').hidden = !state.warnings?.length;
  $('#warnings pre').textContent = (state.warnings || []).join('\n\n');
  renderAi();
  renderApps();
}
function showModal(title, content, wide = false) {
  $('#modal-title').textContent = title;
  $('#modal-body').replaceChildren();
  if (typeof content === 'string') $('#modal-body').innerHTML = content;
  else $('#modal-body').append(content);
  $('#modal').classList.toggle('add-modal', !!$('#add-form'));
  $('#modal').classList.toggle('details-modal', !!wide);
  if (!$('#modal').open) $('#modal').showModal();
}
function details(a) {
  const accent = /^#[0-9a-f]{6}$/i.test(a.accent) ? a.accent : '#2d81ff';
  const meta = appDetails[a.id] || {};
  const shots = (meta.shots || []).slice(0, 2);
  const features = meta.features || [];
  const repoUrl = a.source.type === 'github_release' ? 'https://github.com/' + a.source.repo : a.source.type === 'aur' ? 'https://aur.archlinux.org/packages/' + encodeURIComponent(a.source.package) : a.source.type === 'winget' ? 'https://winstall.app/apps/' + encodeURIComponent(a.source.package) : 'https://archlinux.org/packages/?q=' + encodeURIComponent(a.source.package);
  const iconHTML = a.icon ? `<div class="app-icon has-img details-icon"><img src="${escapeHTML(a.icon)}" alt=""></div>` : `<div class="app-icon details-icon">${escapeHTML(a.name.slice(0,1).toUpperCase())}</div>`;
  const idx = shownApps.findIndex(x => x.id === a.id);
  const prevApp = idx > 0 ? shownApps[idx - 1] : null;
  const nextApp = idx >= 0 && idx < shownApps.length - 1 ? shownApps[idx + 1] : null;

  const shotsHTML = shots.length
    ? `<div class="details-shots">${shots.map(s => `<figure class="details-shot"><img src="${escapeHTML(s.url)}" alt="${escapeHTML(s.caption || a.name)}" loading="lazy">${s.caption ? `<figcaption>${escapeHTML(s.caption.toUpperCase())}</figcaption>` : ''}</figure>`).join('')}</div>`
    : '';
  const aboutText = meta.about || a.tagline;
  const featuresHTML = features.length
    ? `<div class="details-features"><div class="details-section-label">01 / FEATURES</div>${features.map((f, i) => `<div class="feature-card"><span class="feature-num">${String(i + 1).padStart(2, '0')}</span><div><strong>${escapeHTML(f.title)}</strong><p>${escapeHTML(f.text)}</p></div></div>`).join('')}</div>`
    : `<div class="details-features"><div class="details-section-label">01 / TECHNICAL INFO</div><dl class="detail-grid"><dt>Publisher</dt><dd>${escapeHTML(a.publisher)}</dd><dt>Source</dt><dd>${escapeHTML(a.source.repo || a.source.package)}</dd><dt>Installed</dt><dd class="mono">${escapeHTML(a.installed || 'Not installed')}</dd><dt>Latest</dt><dd class="mono">${escapeHTML(a.latest || 'Not checked')}</dd><dt>Installer</dt><dd>${escapeHTML(a.install.type)}</dd><dt>Verification</dt><dd>${escapeHTML(a.verification || 'Not installed by Armin Launcher')}</dd></dl></div>`;

  const html = `
    <div class="details-shell" style="--app-accent:${accent}">
      <div class="details-hero">
        <div class="details-hero-top">
          <div class="details-hero-id">${iconHTML}<div><div class="details-app-name">${escapeHTML(a.name)}</div><p class="details-tagline">${escapeHTML(a.tagline)}</p><div class="details-meta-line">${escapeHTML(a.installed ? 'Installed ' + a.installed : a.latest ? 'Latest ' + a.latest : 'Not checked')} · ${escapeHTML(a.category)} · ${escapeHTML(a.publisher)}</div></div></div>
          <div class="details-hero-actions">
            <div class="details-nav"><button type="button" id="details-prev" ${prevApp ? '' : 'disabled'} aria-label="Previous app">‹</button><button type="button" id="details-next" ${nextApp ? '' : 'disabled'} aria-label="Next app">›</button></div>
            ${action(a)}
          </div>
        </div>
        <div class="details-links">
          <a class="details-link-pill" href="${escapeHTML(a.website)}" target="_blank" rel="noopener noreferrer">WEBSITE ↗</a>
          <a class="details-link-pill" href="${escapeHTML(repoUrl)}" target="_blank" rel="noopener noreferrer">SOURCE ↗</a>
          <a class="details-link-pill" href="${escapeHTML(a.release?.url || repoUrl)}" target="_blank" rel="noopener noreferrer">RELEASES ↗</a>
          ${statusBadge(a)}
        </div>
      </div>
      <div class="details-body">
        <div class="details-left">
          ${shotsHTML}
          <p class="details-about">${escapeHTML(aboutText)}</p>
          ${a.job?.message ? `<p class="muted">${escapeHTML(a.job.message)}</p>` : ''}
          <div class="details-section-label" style="margin-top:16px">02 / LATEST RELEASE</div>
          <pre class="release-notes">${escapeHTML(a.release?.notes || 'No release notes cached. Click Refresh to fetch the latest release.')}</pre>
        </div>
        <div class="details-right">
          ${featuresHTML}
        </div>
      </div>
    </div>`;

  showModal(a.name, html, true);
  $$('#modal-body .details-shot img').forEach(img => {
    img.onerror = () => { img.closest('.details-shot')?.remove(); };
    img.onclick = () => openLightbox(img.src, img.alt || a.name);
  });
  if (prevApp) $('#details-prev').onclick = () => details(prevApp);
  if (nextApp) $('#details-next').onclick = () => details(nextApp);
  const actBtn = $('#modal-body button[data-action]');
  if (actBtn) {
    actBtn.onclick = async () => {
      const op = actBtn.dataset.action;
      if (op === 'install') {
        actBtn.disabled = true;
        actBtn.textContent = a.update ? 'UPDATING…' : 'STARTING…';
        await runAppOp(a.id, 'install', async () => {
          await api('install', {ids:[a.id]});
          if ($('#modal').open) $('#modal').close();
        });
        if ($('#modal').open) details(state.apps.find(x => x.id === a.id) || a);
      } else if (op === 'open') {
        actBtn.disabled = true;
        actBtn.textContent = 'OPENING…';
        await runAppOp(a.id, 'open', () => api('open', {id:a.id}));
        if ($('#modal').open) details(state.apps.find(x => x.id === a.id) || a);
      } else if (op === 'cancel') {
        actBtn.disabled = true;
        actBtn.textContent = 'Cancelling…';
        await runAppOp(a.id, 'cancel', () => api('cancel'));
        if ($('#modal').open) details(state.apps.find(x => x.id === a.id) || a);
      }
    };
  }
}
function confirmUninstall(a) {
  showModal('Uninstall ' + a.name + '?', `<p class="muted">This removes the installed application. Your settings, data, and catalog entry stay intact.</p><div class="modal-actions"><button id="uninstall-cancel">Cancel</button><button id="uninstall-confirm" class="primary">Uninstall</button></div>`);
  $('#uninstall-cancel').onclick = () => $('#modal').close();
  $('#uninstall-confirm').onclick = async () => {
    $('#modal').close();
    await runAppOp(a.id, 'uninstall', () => api('uninstall', {id:a.id}));
  };
}
function confirmCleanUninstall(a) {
  const paths = a.data_paths || [];
  const pathList = paths.length
    ? `<div class="clean-paths mono">${paths.map(p => `<div>${escapeHTML(p)}</div>`).join('')}</div>`
    : '<p class="muted">No app-specific data paths configured.</p>';
  let step = 0;
  const labels = ['Yes, delete everything (1/3)', 'Yes — are you sure? (2/3)', 'Yes — permanently delete app & data (3/3)'];
  showModal('Clean uninstall ' + a.name + '?', `<p class="muted">This permanently removes <strong>${escapeHTML(a.name)}</strong> AND deletes all user settings, caches, and generated files in:</p>${pathList}<p class="text-danger" style="font-size:12px;margin:12px 0 0">Press <strong>Yes</strong> 3 times to confirm permanent deletion.</p><div class="modal-actions"><button id="clean-cancel">Cancel</button><button id="clean-confirm" class="danger-btn">${labels[0]}</button></div>`);
  $('#clean-cancel').onclick = () => $('#modal').close();
  $('#clean-confirm').onclick = async () => {
    step += 1;
    if (step < 3) {
      $('#clean-confirm').textContent = labels[step];
      return;
    }
    $('#modal').close();
    await runAppOp(a.id, 'uninstall', () => api('uninstall', {id:a.id, clean:true}));
  };
}
function confirmBuild(a) {
  const bi = a.build_info || {};
  const estGb = bi.estimated_gb ?? 2.5;
  const estMins = bi.estimated_minutes ?? 10;
  const cpu = state.cpu || {};
  const cpuLabel = cpu.model ? `${cpu.model} (${cpu.cores || '?'} cores)` : `${cpu.cores || '?'} CPU cores`;
  let step = 0;
  const labels = ['Yes, build from source (1/3)', 'Yes — are you sure? (2/3)', 'Yes — start building now (3/3)'];
  showModal(
    'Build ' + a.name + ' from source?',
    `<p class="muted">No pre-built binary is available for <strong>${escapeHTML(a.name)}</strong>, so it must be compiled from source.</p>` +
    `<div class="clean-paths">` +
    `<div><strong>Estimated temporary disk space:</strong> ~${escapeHTML(String(estGb))} GB during build</div>` +
    `<div><strong>Cleanup:</strong> Build cache and intermediate build files are removed automatically by default after building, leaving only the built, lean file/package.</div>` +
    `<div><strong>Estimated build time:</strong> ~${escapeHTML(String(estMins))} min on your CPU (${escapeHTML(cpuLabel)})</div>` +
    `</div>` +
    `<p class="text-danger" style="font-size:12px;margin:12px 0 0">Press <strong>Yes</strong> 3 times to confirm compiling from source.</p>` +
    `<div class="modal-actions"><button id="build-cancel">Cancel</button><button id="build-confirm" class="danger-btn">${labels[0]}</button></div>`
  );
  $('#build-cancel').onclick = () => $('#modal').close();
  $('#build-confirm').onclick = async () => {
    step += 1;
    if (step < 3) {
      $('#build-confirm').textContent = labels[step];
      return;
    }
    $('#modal').close();
    await runAppOp(a.id, 'install', () => api('install', {ids: [a.id], allow_build: true}));
  };
}
function addApp() {
  showModal('Add an app', $('#add-template').content.cloneNode(true));
  const form = $('#add-form');
  const source = form.elements.source_type;
  const install = form.elements.install_type;
  let idTouched = false;
  form.elements.id.addEventListener('input', () => { idTouched = !!form.elements.id.value; });
  form.elements.name.addEventListener('input', () => {
    if (!idTouched) {
      form.elements.id.value = form.elements.name.value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    }
  });
  form.elements.accent.addEventListener('input', () => {
    const hex = $('#accent-hex');
    if (hex) hex.textContent = form.elements.accent.value;
  });
  const updateFields = () => {
    const github = source.value === 'github_release';
    const isLocal = source.value === 'local';
    $$('[data-github]', form).forEach(el => {el.hidden = !github;});
    form.elements.repo.required = github;
    form.elements.asset_pattern.required = github;
    const type = github ? install.value : isLocal ? 'local' : 'package';
    const field = $('#install-field');
    $('span', field).textContent = {appimage:'Binary filename', tarball:'Binary path inside archive', zip:'Executable path inside zip', pacman_pkg:'Installed package name', msi:'Installed product name', local:'Executable or project path', package:'Package name'}[type];
    form.elements.target.placeholder = {appimage:'my-app.AppImage', tarball:'my-app/bin/my-app', zip:'my-app.exe', pacman_pkg:'my-app', msi:'My App', local:'~/.local/bin/my-app', package:'my-app'}[type];
  };
  source.onchange = updateFields;
  install.onchange = updateFields;
  updateFields();
  $('#add-cancel').onclick = () => $('#modal').close();
  form.onsubmit = async event => {
    event.preventDefault();
    const f = Object.fromEntries(new FormData(form));
    const github = f.source_type === 'github_release';
    const isLocal = f.source_type === 'local';
    const ins = {type:github ? f.install_type : isLocal ? 'local' : f.source_type === 'aur' ? 'aur' : f.source_type === 'winget' ? 'winget' : 'pacman', launch:f.launch};
    if (!isLocal) ins[ins.type === 'appimage' ? 'binary_name' : (ins.type === 'tarball' || ins.type === 'zip') ? 'bin' : 'package'] = f.target;
    const src = github ? {type:f.source_type, repo:f.repo, asset_pattern:f.asset_pattern, prerelease:!!f.prerelease} : isLocal ? {type:'local', path:f.target} : {type:f.source_type, package:f.target};
    const app = {id:f.id, name:f.name, publisher:f.publisher, category:f.category, tagline:f.tagline, accent:f.accent, website:f.website, source:src, install:ins, hidden:false};
    const submit = $('button[type=submit]', form);
    submit.disabled = true;
    try { await api('catalog', {op:'add', app}); $('#modal').close(); setNotice(f.name + ' added to your library.'); }
    catch (error) { $('#form-error').textContent = error.message; }
    finally { submit.disabled = false; }
  };
}
$('#apps').addEventListener('click', async event => {
  const button = event.target.closest('button[data-action]');
  if (!button) {
    if (event.target.closest('a, .app-menu')) return;
    const card = event.target.closest('.card[data-id]');
    if (!card) return;
    closeMenus();
    const app = state.apps.find(x => x.id === card.dataset.id);
    if (app) details(app);
    return;
  }
  const a = state.apps.find(a => a.id === button.closest('[data-id]').dataset.id);
  if (!a) return;
  const op = button.dataset.action;
  if (op === 'menu') {
    const menu = button.nextElementSibling;
    const willOpen = menu.hidden;
    closeMenus();
    menu.hidden = !willOpen;
    button.setAttribute('aria-expanded', String(willOpen));
    return;
  }
  closeMenus();
  if (op === 'details') return details(a);
  if (op === 'uninstall') return confirmUninstall(a);
  if (op === 'clean-uninstall') return confirmCleanUninstall(a);
  if (op === 'build') return confirmBuild(a);
  if (op === 'hide') {
    const prevHidden = a.hidden;
    a.hidden = !prevHidden;
    render();
    try {
      await api('catalog', {op:'hide', id:a.id, hidden:a.hidden});
    } catch (error) {
      a.hidden = prevHidden;
      render();
      setNotice(error.message, true);
    }
    return;
  }
  if (op === 'install' || op === 'cancel' || op === 'open') {
    await runAppOp(a.id, op, () =>
      op === 'install' ? api('install', {ids:[a.id]})
      : op === 'cancel' ? api('cancel')
      : api('open', {id:a.id})
    );
  }
});
function closeMenus() {
  $$('.app-menu').forEach(menu => {menu.hidden = true;});
  $$('.menu-button').forEach(button => button.setAttribute('aria-expanded','false'));
}
document.addEventListener('click', event => {if (!event.target.closest('.menu-wrap')) closeMenus();});
document.addEventListener('mousedown', event => {
  if ($('#modal').open || $('#lightbox').open || document.activeElement !== $('#search')) return;
  if (!event.target.closest('input, select, textarea, a, #modal, #lightbox, #ai-panel')) event.preventDefault();
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') closeMenus();
  if (!event.ctrlKey && !event.metaKey && !event.altKey && !$('#modal').open && !$('#lightbox').open && (event.key.length === 1 || event.key === 'Backspace') && !event.target.closest('input, select, textarea, #modal, #lightbox, #ai-panel')) {
    $('#search').focus({preventScroll: true});
  }
  if (!event.ctrlKey && !event.metaKey) return;
  if (['+', '=', '-', '0'].includes(event.key) || ['Equal','Minus','Digit0','NumpadAdd','NumpadSubtract','Numpad0'].includes(event.code)) {
    event.preventDefault();
    if (event.key === '0' || ['Digit0','Numpad0'].includes(event.code)) applyZoom(1);
    else if (event.key === '-' || ['Minus','NumpadSubtract'].includes(event.code)) applyZoom(zoom - .1);
    else applyZoom(zoom + .1);
  }
});
$('#filters').onclick = event => {
  const button = event.target.closest('button[data-filter]');
  if (!button) return;
  filter = button.dataset.filter;
  $$('#filters button').forEach(b => {b.classList.toggle('selected', b === button); b.setAttribute('aria-pressed', String(b === button));});
  renderApps();
};
$('#search').oninput = renderApps;
$('#sort').onchange = renderApps;
$('#grid-view').onclick = () => setView('grid');
$('#list-view').onclick = () => setView('list');
$('#zoom-out').onclick = () => applyZoom(zoom - .1);
$('#zoom-in').onclick = () => applyZoom(zoom + .1);
$('#zoom-reset').onclick = () => applyZoom(1);
$('#theme').onclick = openThemePicker;
applyTheme(currentTheme, false, false);
$('#add').onclick = addApp;
function manageProfiles() {
  const listHTML = () => profiles.map((p, i) => `<div class="profile-row"><span>${PROFILE_ICONS[p.kind] || PROFILE_ICONS.custom}</span><strong>${escapeHTML(p.label)}</strong><span class="muted profile-url">${escapeHTML(p.url)}</span>${profiles.length > 1 ? `<button type="button" data-remove="${i}">Remove</button>` : ''}</div>`).join('');
  showModal('Profiles', `<div class="profile-list" id="profile-list">${listHTML()}</div><form id="profile-form" class="form-grid" style="margin-top:16px"><label>Platform<select name="kind"><option value="github">GitHub</option><option value="website">Website</option><option value="x">X / Twitter</option><option value="discord">Discord</option><option value="youtube">YouTube</option><option value="linkedin">LinkedIn</option><option value="custom">Other link</option></select></label><label>Label / Handle<input name="label" required placeholder="armin0411"></label><label class="full">Profile URL<input name="url" type="url" required placeholder="https://github.com/armin0411"></label><div class="modal-actions full"><button type="button" id="profile-reset">Reset Default</button><button type="submit" class="primary">Add Profile</button></div></form>`);
  const list = $('#profile-list');
  list.onclick = event => {
    const btn = event.target.closest('button[data-remove]');
    if (!btn) return;
    profiles.splice(Number(btn.dataset.remove), 1);
    savePref({profiles});
    renderProfiles();
    list.innerHTML = listHTML();
  };
  $('#profile-reset').onclick = () => {
    profiles = DEFAULT_PROFILES.slice();
    savePref({profiles});
    renderProfiles();
    list.innerHTML = listHTML();
  };
  $('#profile-form').onsubmit = event => {
    event.preventDefault();
    const f = Object.fromEntries(new FormData(event.target));
    profiles.push({kind: f.kind, label: f.label.trim(), url: f.url.trim()});
    savePref({profiles});
    renderProfiles();
    list.innerHTML = listHTML();
    event.target.reset();
  };
}
$('#add-profile').onclick = manageProfiles;
renderProfiles();
$('#modal-close').onclick = () => $('#modal').close();
$('#modal').addEventListener('close', () => {
  if (!$('#lightbox').open) $('#search').focus({preventScroll: true});
});
$('#modal').addEventListener('click', event => {if (event.target === $('#modal')) {const r = $('#modal').getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) $('#modal').close();}});
let lbZoom = 1;
function applyLightboxZoom(value) {
  lbZoom = Math.round(Math.max(0.5, Math.min(4, value)) * 100) / 100;
  const img = $('#lightbox-img');
  img.style.transform = `scale(${lbZoom})`;
  img.classList.toggle('zoomed', lbZoom > 1);
  $('#lb-reset').textContent = Math.round(lbZoom * 100) + '%';
  $('#lb-out').disabled = lbZoom <= 0.5;
  $('#lb-in').disabled = lbZoom >= 4;
}
function openLightbox(src, caption = '') {
  $('#lightbox-img').src = src;
  $('#lightbox-img').alt = caption;
  $('#lightbox-caption').textContent = caption ? caption.toUpperCase() : 'SCREENSHOT';
  applyLightboxZoom(1);
  if (!$('#lightbox').open) $('#lightbox').showModal();
}
$('#lb-out').onclick = () => applyLightboxZoom(lbZoom - 0.25);
$('#lb-in').onclick = () => applyLightboxZoom(lbZoom + 0.25);
$('#lb-reset').onclick = () => applyLightboxZoom(1);
$('#lb-close').onclick = () => $('#lightbox').close();
$('#lightbox-img').onclick = () => applyLightboxZoom(lbZoom > 1 ? 1 : 2);
$('#lightbox-stage').addEventListener('wheel', event => {
  event.preventDefault();
  applyLightboxZoom(lbZoom + (event.deltaY < 0 ? 0.2 : -0.2));
}, {passive: false});
$('#lightbox').addEventListener('click', event => {
  if (event.target === $('#lightbox') || event.target === $('#lightbox-stage')) $('#lightbox').close();
});
let refreshRequest = false;
function renderRefresh() {
  const checking = refreshRequest || state.refreshing || !!refreshProgress;
  const button = $('#refresh');
  button.disabled = state.busy || checking;
  $('#refresh-icon').classList.toggle('spinning', !!checking);
  $('span', button).textContent = checking ? 'Checking…' : 'Refresh';
  if (checking) {
    const progress = refreshProgress;
    setNotice(progress?.total
      ? `Checking for updates (${progress.completed} of ${progress.total} apps)…`
      : 'Checking for updates…');
  } else if (state.busy) {
    setNotice('Working — keep this window open to follow progress.');
  } else {
    setNotice(state.notice || 'Ready. Refresh to check for updates.', !!state.last_error);
  }
}
$('#refresh').onclick = async () => {
  refreshRequest = true;
  renderRefresh();
  let error = '';
  try {
    await api('refresh');
  } catch (err) {
    error = err.message;
  } finally {
    refreshRequest = false;
    renderRefresh();
    if (error && !state.refreshing) setNotice(error, true);
  }
};

const renderAiTranscript = (() => {
  const recordStart = /^(You:|AI:|AI summary:|\$|Error:)(?: |$)/;
  const fenceStart = /^ {0,3}(\x60{3,}|~{3,})\s*([\w+#.-]*)\s*$/;
  const listItem = /^([ \t]*)([-+*]|\d{1,9}[.)])[ \t]+(.*)$/;
  const heading = /^ {0,3}(#{1,6})[ \t]+(.+)$/;
  const quote = /^ {0,3}> ?(.*)$/;
  const csi = /\x1b\[[0-?]*[ -/]*[@-~]/g;
  const labels = {
    'You:': ['user', 'You'],
    'AI:': ['assistant', 'AI'],
    'AI summary:': ['assistant', 'Audit summary'],
    '$': ['terminal', 'Terminal'],
    'Error:': ['error', 'Error'],
  };

  function element(tag, parent, text) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    parent.append(node);
    return node;
  }

  function closesFence(line, marker) {
    const trimmed = line.trim();
    return trimmed.length >= marker.length && [...trimmed].every(char => char === marker[0]);
  }

  function splitRecords(report) {
    const records = [];
    let record = {kind: 'status', lines: []};
    let fence = '';
    for (let line of report.split('\n')) {
      const start = !fence && line.match(recordStart);
      if (start || (!fence && line === 'Cancelled by user.')) {
        if (record.lines.length || record.command) records.push(record);
        const [kind, label] = start ? labels[start[1]] : ['status', 'Stopped'];
        if (start) line = line.slice(start[0].length);
        record = {kind, label, lines: []};
        if (kind === 'terminal') {
          record.command = '$ ' + line;
          continue;
        }
      }
      record.lines.push(line);
      if (record.kind === 'assistant') {
        if (fence && closesFence(line, fence)) fence = '';
        else if (!fence) fence = line.match(fenceStart)?.[1] || '';
      }
    }
    if (record.lines.length || record.command) records.push(record);
    return records;
  }

  function renderInline(parent, text) {
    if (text.includes('\x1b[')) {
      renderAnsi(parent, text);
      return;
    }
    const inline = /\x60([^\x60\n]+)\x60|\*\*([^*\n]+)\*\*|__([^_\n]+)__|\*([^*\n]+)\*|\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g;
    let end = 0;
    for (const match of text.matchAll(inline)) {
      parent.append(text.slice(end, match.index));
      const [, code, bold, boldAlt, italic, label, href] = match;
      if (code) element('code', parent, code);
      else if (bold || boldAlt) renderInline(element('strong', parent), bold || boldAlt);
      else if (italic) renderInline(element('em', parent), italic);
      else {
        const link = element('a', parent, label);
        link.href = href;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
      }
      end = match.index + match[0].length;
    }
    parent.append(text.slice(end));
  }

  function indentation(whitespace) {
    return whitespace.replaceAll('\t', '    ').length;
  }

  function renderList(parent, lines, start) {
    const levels = [];
    let i = start;
    for (; i < lines.length; i++) {
      const match = lines[i].match(listItem);
      if (!match) {
        const last = levels.at(-1);
        const spaces = lines[i].match(/^[ \t]*/)[0];
        const text = lines[i].slice(spaces.length);
        const indent = indentation(spaces);
        if (!text || indent <= last.indent) break;
        renderInline(last.item, '\n' + ' '.repeat(Math.max(0, indent - last.indent - 2)) + text);
        continue;
      }
      const [, spaces, marker, text] = match;
      const indent = indentation(spaces);
      const ordered = /^\d/.test(marker);
      while (levels.length && levels.at(-1).indent > indent) levels.pop();
      if (levels.at(-1)?.indent === indent && levels.at(-1).ordered !== ordered) levels.pop();
      if (!levels.length || levels.at(-1).indent < indent) {
        const list = element(ordered ? 'ol' : 'ul', levels.at(-1)?.item || parent);
        if (ordered) list.start = Number.parseInt(marker, 10);
        levels.push({indent, ordered, list});
      }
      const level = levels.at(-1);
      level.item = element('li', level.list);
      renderInline(level.item, text);
    }
    return i;
  }

  function renderMarkdown(parent, lines) {
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      const fence = line.match(fenceStart);
      const title = line.match(heading);
      if (!line.trim()) {
        i++;
      } else if (fence) {
        const [, marker, language] = fence;
        const code = [];
        i++;
        while (i < lines.length && !closesFence(lines[i], marker)) code.push(lines[i++]);
        i++;
        renderCode(parent, code.join('\n'), language);
      } else if (title) {
        renderInline(element(title[1].length === 1 ? 'h3' : 'h4', parent), title[2]);
        i++;
      } else if (listItem.test(line)) {
        i = renderList(parent, lines, i);
      } else if (quote.test(line)) {
        const quoted = [];
        while (i < lines.length && quote.test(lines[i])) quoted.push(lines[i++].match(quote)[1]);
        renderInline(element('blockquote', parent), quoted.join('\n'));
      } else {
        const paragraph = [line];
        i++;
        while (i < lines.length && lines[i].trim() && ![fenceStart, heading, listItem, quote].some(pattern => pattern.test(lines[i]))) {
          paragraph.push(lines[i++]);
        }
        renderInline(element('p', parent), paragraph.join('\n'));
      }
    }
  }

  function ansiColor(n) {
    if (!Number.isInteger(n) || n < 0 || n > 255) return '';
    if (n < 16) return 'var(--ai-ansi-' + n + ')';
    if (n >= 232) {
      const shade = 8 + (n - 232) * 10;
      return 'rgb(' + [shade, shade, shade].join(',') + ')';
    }
    const levels = [0, 95, 135, 175, 215, 255];
    const cube = n - 16;
    return 'rgb(' + [levels[Math.floor(cube / 36)], levels[Math.floor(cube / 6) % 6], levels[cube % 6]].join(',') + ')';
  }

  function applyAnsi(codes, style) {
    for (let i = 0; i < codes.length; i++) {
      const n = codes[i];
      if (n === 0) style = {};
      else if (n === 1) style.fontWeight = '700';
      else if (n === 2) style.opacity = '.72';
      else if (n === 3 || n === 23) style.fontStyle = n === 3 ? 'italic' : '';
      else if (n === 4 || n === 24) style.textDecoration = n === 4 ? 'underline' : '';
      else if (n === 22) Object.assign(style, {fontWeight: '', opacity: ''});
      else if (n === 39) style.color = '';
      else if (n === 49) style.backgroundColor = '';
      else if (n === 38 || n === 48) {
        const field = n === 38 ? 'color' : 'backgroundColor';
        const mode = codes[++i];
        if (mode === 5) style[field] = ansiColor(codes[++i]);
        else if (mode === 2) {
          const rgb = codes.slice(i + 1, i + 4);
          if (rgb.length === 3 && rgb.every(channel => Number.isInteger(channel) && channel >= 0 && channel <= 255)) {
            style[field] = 'rgb(' + rgb.join(',') + ')';
          }
          i += 3;
        }
      } else if (n >= 30 && n <= 37) style.color = ansiColor(n - 30);
      else if (n >= 40 && n <= 47) style.backgroundColor = ansiColor(n - 40);
      else if (n >= 90 && n <= 97) style.color = ansiColor(n - 82);
      else if (n >= 100 && n <= 107) style.backgroundColor = ansiColor(n - 92);
    }
    return style;
  }

  function renderAnsi(parent, text) {
    let end = 0;
    let style = {};
    const append = fragment => {
      if (!fragment) return;
      if (Object.values(style).some(Boolean)) Object.assign(element('span', parent, fragment).style, style);
      else parent.append(fragment);
    };
    for (const match of text.matchAll(csi)) {
      append(text.slice(end, match.index));
      const parameters = match[0].slice(2, -1);
      if (match[0].endsWith('m') && /^[0-9;]*$/.test(parameters)) {
        style = applyAnsi(parameters.split(';').map(Number), style);
      }
      end = match.index + match[0].length;
    }
    append(text.slice(end));
  }

  function renderCode(parent, text, language) {
    const block = element('div', parent);
    block.className = 'ai-code';
    if (language) element('div', block, language).className = 'ai-code-label';
    renderAnsi(element('code', element('pre', block)), text);
  }

  return (container, report) => {
    const transcript = document.createDocumentFragment();
    const content = report.replace(/\r\n?/g, '\n')
      .replace(/\x1b\][^\x07\x1b]*(?:\x07|\x1b\\|$)/g, '')
      .replace(/[\x00-\x08\x0b-\x1a\x1c-\x1f\x7f]/g, '');
    for (const {kind, label, lines, command} of splitRecords(content)) {
      const record = element('article', transcript);
      record.className = 'ai-record';
      record.dataset.kind = kind;
      if (label) element('div', record, label).className = 'ai-record-label';
      const body = element('div', record);
      body.className = 'ai-record-body';
      if (kind === 'terminal') {
        renderAnsi(element('code', body), command);
        if (lines.length) renderCode(body, lines.join('\n'));
      } else if (kind === 'assistant') {
        renderMarkdown(body, lines);
      } else {
        renderAnsi(element('p', body), lines.join('\n'));
      }
    }
    container.replaceChildren(transcript);
  };
})();

const aiPanel = $('#ai-panel');
const aiSettings = $('#ai-settings');
const aiSettingsFields = aiSettings.elements;
const aiComposer = $('#ai-composer');
const aiInput = $('#ai-input');
const aiOutput = $('#ai-output');
const aiLog = $('#ai-log');
const aiProvider = () => aiSettingsFields.provider.value;
const aiCli = () => aiSettingsFields.sub_cli.value;
const aiModelScope = () => aiProvider() === 'subscription' ? `subscription:${aiCli()}` : aiProvider();
let aiReady = false;
let aiRequest = false;
let aiMode = 'ask';
let aiModels = {};
let aiSelectedModels = {};
let aiModelRequest = 0;
let aiRenderedFixes = '';
let aiRenderedReport = '';

function setAiError(message = '') {
  const error = $('#ai-error');
  error.textContent = message;
  error.hidden = !message;
}

function renderAi() {
  const running = !!state.ai_running;
  const report = state.ai_report || '';
  const outcome = state.ai_outcome || '';
  const unavailable = !token || aiRequest || running;
  const status = running
    ? state.ai_phase || 'Working…'
    : ({complete: 'Complete', error: 'Needs attention', cancelled: 'Stopped'}[outcome] || (aiRequest ? 'Starting…' : 'Ready'));
  const indicator = $('.ai-toolbar-dot');
  indicator.hidden = !running && !outcome;
  indicator.dataset.status = running ? 'running' : outcome;
  $('#ai-maintain').title = running || outcome ? `AI Maintain · ${status}` : 'Open AI Maintain';
  const statusLabel = $('#ai-status');
  if (statusLabel.textContent !== status) statusLabel.textContent = status;
  statusLabel.dataset.status = running ? 'running' : outcome;
  const stopping = /^stopping/i.test(status);
  const working = $('#ai-working');
  working.hidden = !running || stopping;
  working.classList.toggle('has-phase', !!state.ai_phase);
  $('#ai-stop').hidden = !running;
  $('#ai-stop').disabled = aiRequest || stopping;
  $('#ai-clear').disabled = unavailable || !report;
  $('#ai-send').disabled = unavailable || (aiMode === 'ask' && !aiInput.value.trim());
  $('#ai-empty').hidden = !!report;
  aiLog.hidden = !report;
  if (aiRenderedReport !== report) {
    const atBottom = aiOutput.scrollHeight - aiOutput.scrollTop - aiOutput.clientHeight < 28;
    renderAiTranscript(aiLog, report);
    aiRenderedReport = report;
    if (atBottom) aiOutput.scrollTop = aiOutput.scrollHeight;
  }
  if (state.term_cwd) aiInput.title = `Local commands run in ${state.term_cwd}`;
  const fixes = state.pending_fixes || [];
  const signature = JSON.stringify(fixes);
  const fixList = $('#ai-fixes');
  fixList.hidden = !fixes.length;
  if (signature !== aiRenderedFixes) {
    aiRenderedFixes = signature;
    fixList.innerHTML = fixes.map(f => `<div class="ai-fix-row">
      <div><strong>${escapeHTML(f.title)}</strong><code>${escapeHTML(f.cmd)}</code></div>
      <button type="button" data-fix-id="${escapeHTML(f.id)}" data-admin="${f.needs_admin ? '1' : '0'}">${f.needs_admin ? 'Run as admin' : 'Run fix'}</button>
    </div>`).join('');
  }
  $$('button', fixList).forEach(button => {button.disabled = unavailable;});
}
function toggleAiSettings(show) {
  aiSettings.hidden = !show;
  $('#ai-settings-toggle').setAttribute('aria-expanded', String(show));
  if (show) aiSettingsFields.provider.focus();
}
function toggleAiPanel(show) {
  if (show && !token) return;
  const firstOpen = show && !aiReady;
  aiPanel.hidden = !show;
  const button = $('#ai-maintain');
  button.setAttribute('aria-expanded', String(show));
  if (!show) {
    button.focus({preventScroll: true});
    return;
  }
  if (firstOpen) initializeAi();
  renderAi();
  aiOutput.scrollTop = aiOutput.scrollHeight;
  (aiSettings.hidden ? aiInput : aiSettingsFields.provider).focus({preventScroll: true});
}
function setAiMode(mode) {
  aiMode = mode;
  const maintain = mode === 'maintain';
  $$('[data-ai-mode]', aiComposer).forEach(button => {
    button.setAttribute('aria-pressed', String(button.dataset.aiMode === mode));
  });
  aiInput.setAttribute('aria-label', maintain ? 'Catalog maintenance request' : 'Message to AI');
  aiInput.placeholder = maintain
    ? 'Describe an app to add or check…'
    : 'Ask about an app or type !command…';
  $('#ai-composer-hint').textContent = maintain
    ? 'Leave blank to audit the whole catalog'
    : 'Enter to send · Shift+Enter for a new line';
  $('#ai-send').textContent = maintain ? 'Run maintenance' : 'Send';
  renderAi();
}

async function aiAction(path, data) {
  if (aiRequest || !token) return false;
  setAiError();
  aiRequest = true;
  renderAi();
  try {
    await api(path, data);
    return true;
  } catch (err) {
    setAiError(err.message);
    return false;
  } finally {
    aiRequest = false;
    renderAi();
  }
}
function saveAiSettings(patch) {
  post('prefs', patch).catch(err => setAiError(err.message));
}
function aiOptions() {
  return {
    provider: aiProvider(),
    model: aiSettingsFields.model.value.trim(),
    thinking: aiSettingsFields.thinking.value,
    base_url: aiProvider() === 'subscription' ? aiCli() : aiSettingsFields.base_url.value.trim(),
    key_id: aiProvider() === 'subscription' || aiSettingsFields.key_select.value === '__new__' ? '' : aiSettingsFields.key_select.value,
  };
}
function renderAiModelList() {
  const list = aiModels[aiModelScope()] || [];
  $('#ai-models').replaceChildren(...list.map(model => new Option(model)));
}
function renderAiConnection() {
  const provider = aiProvider();
  const name = aiSettingsFields.provider.selectedOptions[0].textContent;
  const cli = aiSettingsFields.sub_cli.selectedOptions[0].textContent;
  const key = aiSettingsFields.key_select.value;
  let label = name;
  if (provider === 'subscription') label = state.ai_cli_tools?.[aiCli()] ? cli : `${cli} · CLI unavailable`;
  else if (provider !== 'custom') {
    label += key && key !== '__new__' ? ' · Key saved' : state.ai_keys?.[provider] ? ' · Key configured' : ' · Add an API key';
  }
  $('#ai-connection').textContent = label;
  $('#ai-sub-login').disabled = !state.ai_cli_tools?.[aiCli()];
}
function renderAiKeys() {
  const select = aiSettingsFields.key_select;
  const keys = state.ai_key_profiles?.[aiProvider()] || [];
  select.replaceChildren(...keys.map(key => new Option(key.label, key.id)), new Option('Add an API key…', '__new__'));
  const active = state.ai_active_keys?.[aiProvider()];
  select.value = keys.some(key => key.id === active) ? active : keys[0]?.id || '__new__';
  renderAiKeySelection();
}
function renderAiKeySelection() {
  const subscription = aiProvider() === 'subscription';
  const adding = aiSettingsFields.key_select.value === '__new__';
  $('#ai-new-key-wrap').hidden = subscription || !adding;
  $('#ai-key-delete').hidden = adding;
  renderAiConnection();
}
function resetAiModelLookup() {
  aiModelRequest++;
  $('#ai-refresh-models').disabled = false;
  $('#ai-model-hint').hidden = true;
}
function renderAiProvider() {
  const provider = aiProvider();
  const subscription = provider === 'subscription';
  $('#ai-sub-wrap').hidden = !subscription;
  $('#ai-key-wrap').hidden = subscription;
  $('#ai-base-wrap').hidden = provider !== 'custom';
  aiSettingsFields.api_key.value = '';
  aiSettingsFields.key_label.value = '';
  if (subscription) renderAiKeySelection();
  else renderAiKeys();
  aiSettingsFields.model.value = aiSelectedModels[aiModelScope()] || '';
  resetAiModelLookup();
  renderAiModelList();
}
function initializeAi() {
  let legacy = {};
  try { legacy = JSON.parse(localStorage.getItem('launchcraft-ai-prefs') || '{}') || {}; } catch {}
  const prefs = {...legacy, ...state.prefs};
  const available = ['codex', 'opencode', 'claude', 'gemini'].find(cli => state.ai_cli_tools?.[cli]);
  const providerWithKey = ['openai', 'anthropic', 'gemini', 'openrouter', 'custom'].find(provider => state.ai_keys?.[provider]);
  const chooseStoredOption = (field, value, fallback) => {
    field.value = [...field.options].some(option => option.value === value) ? value : fallback;
  };
  chooseStoredOption(aiSettingsFields.provider, prefs.ai_provider, providerWithKey || (available ? 'subscription' : 'openai'));
  chooseStoredOption(aiSettingsFields.sub_cli, prefs.ai_sub_cli, available || 'codex');
  aiSettingsFields.base_url.value = prefs.ai_base_url || '';
  chooseStoredOption(aiSettingsFields.thinking, prefs.ai_thinking, 'auto');
  aiModels = {...state.ai_models};
  aiSelectedModels = {...(state.prefs?.ai_selected_models ?? legacy.ai_selected_models)};
  if (aiSelectedModels.subscription && prefs.ai_sub_cli) {
    const oldScope = `subscription:${prefs.ai_sub_cli}`;
    aiSelectedModels[oldScope] ??= aiSelectedModels.subscription;
    if (state.prefs?.ai_selected_models?.subscription) {
      saveAiSettings({ai_selected_models: {[oldScope]: aiSelectedModels[oldScope], subscription: ''}});
    }
  }
  aiReady = true;
  renderAiProvider();
  const provider = aiProvider();
  if (!state.ai_running && !state.ai_report &&
      ((provider === 'subscription' && !state.ai_cli_tools?.[aiCli()]) ||
       (provider === 'custom' && !aiSettingsFields.base_url.value) ||
       (provider !== 'subscription' && provider !== 'custom' && !state.ai_keys?.[provider]))) {
    toggleAiSettings(true);
  }
}

$('#ai-maintain').onclick = () => toggleAiPanel(aiPanel.hidden);
$('#ai-hide').onclick = () => toggleAiPanel(false);
$('#ai-settings-toggle').onclick = () => {
  toggleAiSettings(aiSettings.hidden);
  if (aiSettings.hidden) aiInput.focus();
};
aiSettings.onsubmit = event => event.preventDefault();
aiSettingsFields.provider.onchange = () => {
  setAiError();
  saveAiSettings({ai_provider: aiProvider()});
  renderAiProvider();
};
aiSettingsFields.sub_cli.onchange = () => {
  setAiError();
  saveAiSettings({ai_sub_cli: aiCli()});
  renderAiProvider();
};
aiSettingsFields.base_url.onchange = () => {
  resetAiModelLookup();
  saveAiSettings({ai_base_url: aiSettingsFields.base_url.value.trim()});
};
aiSettingsFields.thinking.onchange = () => saveAiSettings({ai_thinking: aiSettingsFields.thinking.value});
aiSettingsFields.model.onchange = () => {
  const scope = aiModelScope();
  const model = aiSettingsFields.model.value.trim();
  aiSelectedModels[scope] = model;
  saveAiSettings({ai_selected_models: {[scope]: model}});
};
aiSettingsFields.key_select.onchange = async () => {
  setAiError();
  resetAiModelLookup();
  const {provider, key_id} = aiOptions();
  renderAiKeySelection();
  if (key_id && !await aiAction('ai_keys', {op: 'select', provider, key_id}) && provider === aiProvider()) renderAiKeys();
};
$('#ai-key-save').onclick = async () => {
  const provider = aiProvider();
  const api_key = aiSettingsFields.api_key.value.trim();
  if (!api_key) return setAiError('Enter an API key to save.');
  const label = aiSettingsFields.key_label.value.trim();
  if (await aiAction('ai_keys', {op: 'add', provider, api_key, label}) && provider === aiProvider()) renderAiProvider();
};
$('#ai-key-delete').onclick = async () => {
  const {provider, key_id} = aiOptions();
  if (key_id && await aiAction('ai_keys', {op: 'delete', provider, key_id}) && provider === aiProvider()) renderAiProvider();
};
$('#ai-sub-login').onclick = async () => {
  setAiError();
  try {
    await post('ai_sub_login', {cli: aiCli()});
    const hint = $('#ai-model-hint');
    hint.textContent = 'Finish signing in from the terminal window.';
    hint.hidden = false;
  } catch (err) {
    setAiError(err.message);
  }
};
$('#ai-refresh-models').onclick = async () => {
  const request = ++aiModelRequest;
  const button = $('#ai-refresh-models');
  const hint = $('#ai-model-hint');
  const {provider, key_id, base_url} = aiOptions();
  const scope = aiModelScope();
  button.disabled = true;
  hint.hidden = false;
  hint.textContent = 'Loading models…';
  try {
    const result = await post('ai_models', {provider, key_id, base_url}, {timeoutMs: 20000});
    if (request !== aiModelRequest) return;
    aiModels[scope] = result.models || [];
    renderAiModelList();
    hint.textContent = result.models?.length
      ? `${result.models.length} models available in the Model field.`
      : 'Enter a model ID or use the provider default.';
  } catch (err) {
    if (request === aiModelRequest) hint.textContent = err.message;
  } finally {
    if (request === aiModelRequest) button.disabled = false;
  }
};
$$('[data-ai-mode]', aiComposer).forEach(button => {
  button.onclick = () => {
    setAiMode(button.dataset.aiMode);
    aiInput.focus();
  };
});
aiComposer.onsubmit = async event => {
  event.preventDefault();
  if ($('#ai-send').disabled) return;
  const draft = aiInput.value;
  const input = draft.trim();
  const maintain = aiMode === 'maintain';
  const options = aiOptions();
  const accepted = await (maintain
    ? aiAction('ai_maintain', {...options, prompt: input})
    : aiAction('ai_terminal', {...options, input}));
  if (accepted && aiInput.value === draft) {
    aiInput.value = '';
    renderAi();
  }
};
aiInput.oninput = renderAi;
aiInput.onkeydown = event => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    aiComposer.requestSubmit();
  }
};
$('#ai-clear').onclick = () => aiAction('ai_terminal', {input: 'clear'});
$('#ai-stop').onclick = () => aiAction('ai_cancel');
$('#ai-fixes').onclick = event => {
  const button = event.target.closest('button[data-fix-id]');
  if (!button) return;
  if (button.dataset.admin === '1' && !window.confirm('Run this fix with administrator privileges?')) return;
  aiAction('ai_fix', {id: button.dataset.fixId});
};
aiPanel.onkeydown = event => {
  if (event.key === 'Escape' && !event.defaultPrevented) toggleAiPanel(false);
  if (event.key.toLowerCase() === 'l' && event.ctrlKey && !$('#ai-clear').disabled) {
    event.preventDefault();
    $('#ai-clear').click();
  }
};
$('#update-all').onclick = async () => {
  const btn = $('#update-all');
  const prevText = btn.textContent;
  const targets = state.apps.filter(a => a.update).map(a => a.id);
  btn.disabled = true;
  btn.textContent = 'Starting…';
  targets.forEach(id => pendingOps.set(id, 'install'));
  renderApps();
  try {
    await api('install');
  } catch (e) {
    setNotice(e.message, true);
  } finally {
    targets.forEach(id => pendingOps.delete(id));
    render();
    if (!state.busy && btn.textContent === 'Starting…') btn.textContent = prevText;
  }
};
applyTheme(currentTheme, false, false);
applyZoom(zoom, false);
setView(view, false);
async function syncState() {
  const response = await fetch('/api/state');
  const result = await response.json();
  if (!response.ok) throw new Error(result.error);
  token = result.token;
  applyState(result);
}
async function connect() {
  try {
    let reconnecting = false;
    events = new EventSource('/events');
    events.addEventListener('state', event => applyState(JSON.parse(event.data)));
    events.addEventListener('ai', event => applyAiState(JSON.parse(event.data)));
    events.addEventListener('refresh-progress', event => {
      refreshProgress = JSON.parse(event.data);
      renderRefresh();
    });
    events.addEventListener('progress', event => {
      const job = JSON.parse(event.data);
      const a = state.apps.find(a => a.id === job.id);
      if (a) {
        a.job = job;
        if (!terminal.includes(job.status)) state.busy = true;
        updateAppCard(a);
      }
    });
    events.addEventListener('error', event => {
      if (event.data) setNotice(JSON.parse(event.data).message, true);
      else {
        reconnecting = true;
        setNotice('Connection interrupted. Reconnecting… Reopen Armin Launcher if the server has closed.', true);
      }
    });
    events.addEventListener('connected', () => {
      if (!reconnecting) return;
      reconnecting = false;
      syncState().catch(error => setNotice(error.message, true));
    });
    await syncState();
  } catch (error) {setNotice(error.message, true);}
}
window.addEventListener('pagehide', () => events?.close());
fetch('/details.json').then(r => r.ok ? r.json() : {}).then(d => { appDetails = d; }).catch(() => {});
connect();
if (!$('#modal').open) $('#search').focus({preventScroll: true});
