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
function applyState(next) {
  if ((next.revision || 0) < (state.revision || 0)) return;
  state = next;
  if (!prefsLoaded && next.prefs) {
    prefsLoaded = true;
    if (next.prefs.view === 'list' || next.prefs.view === 'grid') setView(next.prefs.view, false);
    if (next.prefs.theme === 'light' || next.prefs.theme === 'dark') {
      document.body.classList.toggle('light', next.prefs.theme === 'light');
      localStorage.setItem('launchcraft-theme', next.prefs.theme);
    }
    if (typeof next.prefs.zoom === 'number') applyZoom(next.prefs.zoom, false);
    if (Array.isArray(next.prefs.profiles) && next.prefs.profiles.length) {
      profiles = next.prefs.profiles;
      renderProfiles();
    }
  }
  render();
}
function setNotice(message, error = false) {
  $('#notice-text').textContent = message;
  $('#notice').classList.toggle('error', error);
}
async function api(path, data = {}) {
  const response = await fetch('/api/' + path, {method: 'POST', headers: {'Content-Type':'application/json', 'X-LaunchCraft-Token': token}, body: JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Request failed');
  applyState(result);
  return result;
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
  const job = a.job;
  if (job && !terminal.includes(job.status) && state.busy) {
    return `<span class="status-pill is-busy">${escapeHTML(job.status)}</span>`;
  }
  if (job?.status === 'Error') return '<span class="status-pill is-error">ERROR · RETRY</span>';
  if (a.source.type === 'local' && a.installed) return '<span class="status-pill is-local">LOCAL APP</span>';
  if (a.compatible === false) return '<span class="status-pill is-incompatible">NOT COMPATIBLE</span>';
  if (a.update) return '<span class="status-pill is-update">UPDATE AVAILABLE</span>';
  if (a.installed) return '<span class="status-pill is-installed">INSTALLED</span>';
  if (a.hidden) return '<span class="status-pill is-hidden">HIDDEN</span>';
  return '<span class="status-pill is-available">AVAILABLE TO INSTALL</span>';
}
function action(a) {
  const job = a.job;
  if (job && !terminal.includes(job.status) && state.busy) {
    const percent = typeof job.percent === 'number' ? Math.max(0, Math.min(100, job.percent)) : null;
    return `<div class="progress-group"><div class="progress-info"><div class="progress-text"><span>${escapeHTML(job.status)}</span><span>${percent === null ? '' : Math.round(percent) + '%'}</span></div><div class="progress-track" role="progressbar" aria-label="${escapeHTML(job.status)}" ${percent === null ? '' : 'aria-valuenow="' + percent + '"'} aria-valuemin="0" aria-valuemax="100"><div class="progress-fill ${percent === null ? 'indeterminate' : ''}" ${percent === null ? '' : 'style="width:' + percent + '%"'}></div></div></div><button class="cancel" data-action="cancel" title="Cancel pending work; active package transactions finish safely">Cancel</button></div>`;
  }
  if (a.compatible === false && !a.installed) {
    return '<button class="action is-incompatible" disabled>INSTALL</button>';
  }
  const op = a.installed && !a.update ? 'open' : 'install';
  const cls = a.update ? 'is-update primary' : a.installed ? 'is-open' : 'is-install';
  const label = a.update ? 'UPDATE ' + a.latest : a.installed ? 'OPEN ↗' : 'INSTALL';
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
    const fadeA = meta.accent2 ? '11%' : `${6 + (idx % 4)}%`;
    const fadeB = meta.accent2 ? '7%' : `${2 + (idx % 3)}%`;
    const badge = `<span class="badge">${escapeHTML(a.category)}</span>`;
    const released = formatReleased(a);
    const releasedLine = released ? `<span class="last-updated">Last updated: ${escapeHTML(released)}</span>` : '';
    const tagline = `<p class="tagline">${escapeHTML(a.tagline)}</p>`;
    const cardState = [a.installed ? 'is-installed' : 'is-not-installed', meta.accent2 ? 'has-duo-fade' : ''].filter(Boolean).join(' ');
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
  $('#refresh').disabled = state.busy;
  $('#update-all').disabled = state.busy || !updates;
  $('#refresh-icon').classList.toggle('spinning', !!state.refreshing);
  $('#warnings').hidden = !state.warnings?.length;
  $('#warnings pre').textContent = (state.warnings || []).join('\n\n');
  if (state.refreshing) setNotice('Refreshing release metadata and package updates…');
  else if (state.busy) setNotice('Working — keep this window open to follow progress.');
  else setNotice(state.notice || 'Ready. Refresh to check the latest releases.', !!state.last_error);
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
      try {
        if (op === 'install') { await api('install', {ids:[a.id]}); $('#modal').close(); }
        else if (op === 'open') { await api('open', {id:a.id}); }
        else if (op === 'cancel') { await api('cancel'); }
      } catch (error) { setNotice(error.message, true); }
    };
  }
}
function confirmUninstall(a) {
  showModal('Uninstall ' + a.name + '?', `<p class="muted">This removes the installed application. Your settings, data, and catalog entry stay intact.</p><div class="modal-actions"><button id="uninstall-cancel">Cancel</button><button id="uninstall-confirm" class="primary">Uninstall</button></div>`);
  $('#uninstall-cancel').onclick = () => $('#modal').close();
  $('#uninstall-confirm').onclick = async () => {
    $('#modal').close();
    try { await api('uninstall', {id:a.id}); } catch (error) { setNotice(error.message, true); }
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
    try { await api('uninstall', {id:a.id, clean:true}); } catch (error) { setNotice(error.message, true); }
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
  try {
    if (op === 'hide') await api('catalog', {op:'hide', id:a.id, hidden:!a.hidden});
    else if (op === 'install') await api('install', {ids:[a.id]});
    else if (op === 'cancel') await api('cancel');
    else if (op === 'open') await api('open', {id:a.id});
  } catch (error) { setNotice(error.message, true); }
});
function closeMenus() {
  $$('.app-menu').forEach(menu => {menu.hidden = true;});
  $$('.menu-button').forEach(button => button.setAttribute('aria-expanded','false'));
}
document.addEventListener('click', event => {if (!event.target.closest('.menu-wrap')) closeMenus();});
document.addEventListener('mousedown', event => {
  if ($('#modal').open || $('#lightbox').open || document.activeElement !== $('#search')) return;
  if (!event.target.closest('input, select, textarea, a, #modal, #lightbox')) event.preventDefault();
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') closeMenus();
  if (!event.ctrlKey && !event.metaKey && !event.altKey && !$('#modal').open && !$('#lightbox').open && (event.key.length === 1 || event.key === 'Backspace') && !event.target.closest('input, select, textarea, #modal, #lightbox')) {
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
$('#theme').onclick = () => {
  document.body.classList.toggle('light');
  const theme = document.body.classList.contains('light') ? 'light' : 'dark';
  localStorage.setItem('launchcraft-theme', theme);
  savePref({theme});
};
if (localStorage.getItem('launchcraft-theme') === 'light') document.body.classList.add('light');
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
$('#refresh').onclick = async () => {try {await api('refresh');} catch (e) {setNotice(e.message,true);}};
$('#update-all').onclick = async () => {try {await api('install');} catch (e) {setNotice(e.message,true);}};
applyZoom(zoom, false);
setView(view, false);
async function connect() {
  try {
    events = new EventSource('/events');
    events.addEventListener('state', event => applyState(JSON.parse(event.data)));
    events.addEventListener('progress', event => {
      const job = JSON.parse(event.data);
      const a = state.apps.find(a => a.id === job.id);
      if (a) {a.job = job; renderApps();}
    });
    events.addEventListener('error', event => {
      if (event.data) setNotice(JSON.parse(event.data).message, true);
      else setNotice('Connection interrupted. Reconnecting… Relaunch LaunchCraft if the server has closed.', true);
    });
    events.addEventListener('connected', () => {if (token) setNotice('Connected to local launcher.');});
    const response = await fetch('/api/state');
    const result = await response.json();
    if (!response.ok) throw new Error(result.error);
    token = result.token;
    applyState(result);
  } catch (error) {setNotice(error.message, true);}
}
window.addEventListener('pagehide', () => events?.close());
fetch('/details.json').then(r => r.ok ? r.json() : {}).then(d => { appDetails = d; }).catch(() => {});
connect();
if (!$('#modal').open) $('#search').focus({preventScroll: true});
