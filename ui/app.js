'use strict';
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const DEFAULT_PROFILES = [{label: 'armin0411', url: 'https://github.com/armin0411', kind: 'github'}];
let state = {apps: [], busy: false}, token = '', filter = 'all', prefsLoaded = false;
let view = localStorage.getItem('launchcraft-view') === 'list' ? 'list' : 'grid';
let zoom = Math.max(.75, Math.min(1.75, Number(localStorage.getItem('launchcraft-zoom')) || 1));
let profiles = DEFAULT_PROFILES.slice();
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
  return `<span class="version mono">${escapeHTML(a.installed || '—')}<span class="arrow">→</span><span class="latest">${escapeHTML(a.latest || 'not checked')}</span></span>`;
}
function statusBadge(a) {
  const job = a.job;
  if (job && !terminal.includes(job.status) && state.busy) {
    return `<span class="status-pill is-busy">${escapeHTML(job.status)}</span>`;
  }
  if (job?.status === 'Error') return '<span class="status-pill is-error">ERROR · RETRY</span>';
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
  const op = a.installed && !a.update ? 'open' : 'install';
  const cls = a.update ? 'is-update primary' : a.installed ? 'is-open' : 'is-install';
  const label = a.update ? 'UPDATE ' + a.latest : a.installed ? 'OPEN ↗' : 'INSTALL';
  return `<button class="action ${cls}" data-action="${op}" ${state.busy && op !== 'open' ? 'disabled' : ''}>${escapeHTML(label)}</button>`;
}
function menu(a) {
  const repo = a.source.type === 'github_release' ? 'https://github.com/' + a.source.repo : a.source.type === 'aur' ? 'https://aur.archlinux.org/packages/' + encodeURIComponent(a.source.package) : 'https://archlinux.org/packages/?q=' + encodeURIComponent(a.source.package);
  return `<div class="menu-wrap"><button class="menu-button" data-action="menu" aria-label="Menu for ${escapeHTML(a.name)}" aria-expanded="false">···</button><div class="app-menu" hidden><button data-action="details">Details / Release notes</button><a href="${escapeHTML(repo)}" target="_blank" rel="noopener noreferrer">Open Repo ↗</a><button data-action="hide">${a.hidden ? 'Unhide' : 'Hide'} app</button><button data-action="uninstall" class="danger" ${!a.installed || state.busy ? 'disabled' : ''}>Uninstall</button></div></div>`;
}
function appIdentity(a, withTagline = false) {
  const icon = a.icon
    ? `<div class="app-icon has-img" aria-hidden="true"><img src="${escapeHTML(a.icon)}" alt="" loading="lazy"></div>`
    : `<div class="app-icon" aria-hidden="true">${escapeHTML(a.name.slice(0,1).toUpperCase())}</div>`;
  const sub = withTagline
    ? `<p class="tagline" title="${escapeHTML(a.tagline)}">${escapeHTML(a.tagline)}</p>`
    : `<span class="publisher">${escapeHTML(a.publisher)}</span>`;
  return `<div class="app-top">${icon}<div class="app-title"><h3>${escapeHTML(a.name)}</h3>${sub}</div></div>`;
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
  apps.sort((a,b) => (sort === 'updates' ? Number(b.update) - Number(a.update) : sort === 'category' ? a.category.localeCompare(b.category) : 0) || a.name.localeCompare(b.name));
  const container = $('#apps');
  container.className = view;
  let html = view === 'list' && apps.length ? '<div class="table-head" aria-hidden="true"><span>APP</span><span>STATUS</span><span>CATEGORY / PUBLISHER</span><span>INSTALLED → LATEST</span><span style="text-align:right">ACTION</span><span></span></div>' : '';
  html += apps.map(a => {
    const accent = /^#[0-9a-f]{6}$/i.test(a.accent) ? a.accent : '#2d81ff';
    const badge = `<span class="badge">${escapeHTML(a.category)}</span>`;
    const tagline = `<p class="tagline">${escapeHTML(a.tagline)}</p>`;
    const content = view === 'list'
      ? `<div class="card-inner">${appIdentity(a, true)}<div class="status-cell">${statusBadge(a)}</div><div class="category-cell">${badge}<span class="publisher">${escapeHTML(a.publisher)}</span></div>${versions(a)}<div class="list-action">${action(a)}</div>${menu(a)}</div>`
      : `<div class="card-inner"><div class="app-top">${appIdentity(a, false).replace(/^<div class="app-top">|<\/div>$/g,'')}${menu(a)}</div>${tagline}<div class="app-meta">${badge}${versions(a)}</div></div><div class="card-bottom">${statusBadge(a)}${action(a)}</div>`;
    return `<article class="card" data-id="${escapeHTML(a.id)}" style="--app-accent:${accent}">${content}</article>`;
  }).join('');
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
function showModal(title, content) {
  $('#modal-title').textContent = title;
  $('#modal-body').replaceChildren();
  if (typeof content === 'string') $('#modal-body').innerHTML = content;
  else $('#modal-body').append(content);
  $('#modal').classList.toggle('add-modal', !!$('#add-form'));
  if (!$('#modal').open) $('#modal').showModal();
}
function details(a) {
  showModal(a.name, `<p class="muted">${escapeHTML(a.tagline)}</p><dl class="detail-grid"><dt>Publisher</dt><dd>${escapeHTML(a.publisher)}</dd><dt>Source</dt><dd>${escapeHTML(a.source.repo || a.source.package)}</dd><dt>Installed</dt><dd class="mono">${escapeHTML(a.installed || 'Not installed')}</dd><dt>Latest</dt><dd class="mono">${escapeHTML(a.latest || 'Not checked')}</dd><dt>Installer</dt><dd>${escapeHTML(a.install.type)}</dd><dt>Verification</dt><dd>${escapeHTML(a.verification || 'Not installed by LaunchCraft')}</dd></dl>${a.job?.message ? '<p class="muted">' + escapeHTML(a.job.message) + '</p>' : ''}<p><a href="${escapeHTML(a.release?.url || a.website)}" target="_blank" rel="noopener noreferrer">Release page ↗</a></p><h3>Release notes</h3><pre class="release-notes">${escapeHTML(a.release?.notes || 'No release notes cached. Refresh to fetch the latest release.')}</pre>`);
}
function confirmUninstall(a) {
  showModal('Uninstall ' + a.name + '?', `<p class="muted">This removes the installed application. Its catalog entry stays in your library.</p><div class="modal-actions"><button id="uninstall-cancel">Cancel</button><button id="uninstall-confirm" class="primary">Uninstall</button></div>`);
  $('#uninstall-cancel').onclick = () => $('#modal').close();
  $('#uninstall-confirm').onclick = async () => {
    $('#modal').close();
    try { await api('uninstall', {id:a.id}); } catch (error) { setNotice(error.message, true); }
  };
}
function addApp() {
  showModal('Add an app', $('#add-template').content.cloneNode(true));
  const form = $('#add-form');
  const source = form.elements.source_type;
  const install = form.elements.install_type;
  const updateFields = () => {
    const github = source.value === 'github_release';
    $$('[data-github]', form).forEach(el => {el.hidden = !github;});
    form.elements.repo.required = github;
    form.elements.asset_pattern.required = github;
    const type = github ? install.value : 'package';
    const field = $('#install-field');
    $('span', field).textContent = {appimage:'Binary filename', tarball:'Binary path inside archive', pacman_pkg:'Installed package name', package:'Package name'}[type];
    form.elements.target.placeholder = {appimage:'my-app.AppImage', tarball:'my-app/bin/my-app', pacman_pkg:'my-app', package:'my-app'}[type];
  };
  source.onchange = updateFields;
  install.onchange = updateFields;
  updateFields();
  $('#add-cancel').onclick = () => $('#modal').close();
  form.onsubmit = async event => {
    event.preventDefault();
    const f = Object.fromEntries(new FormData(form));
    const github = f.source_type === 'github_release';
    const ins = {type:github ? f.install_type : f.source_type === 'aur' ? 'aur' : 'pacman', launch:f.launch};
    ins[ins.type === 'appimage' ? 'binary_name' : ins.type === 'tarball' ? 'bin' : 'package'] = f.target;
    const src = github ? {type:f.source_type, repo:f.repo, asset_pattern:f.asset_pattern, prerelease:!!f.prerelease} : {type:f.source_type, package:f.target};
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
  if (!button) return;
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
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') closeMenus();
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
$('#modal').addEventListener('click', event => {if (event.target === $('#modal')) {const r = $('#modal').getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) $('#modal').close();}});
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
connect();
