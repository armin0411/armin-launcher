'use strict';
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let state = {apps: [], busy: false}, token = '', filter = 'all', prefsLoaded = false;
let view = localStorage.getItem('launchcraft-view') === 'list' ? 'list' : 'grid';
let zoom = Math.max(.75, Math.min(1.75, Number(localStorage.getItem('launchcraft-zoom')) || 1));
let events;
const terminal = ['Complete', 'Cancelled', 'Error'];
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
  $('#shown-count').textContent = `${apps.length} ${apps.length === 1 ? 'APP' : 'APPS'} SHOWN`;
}
function render() {
  const visible = state.apps.filter(a => !a.hidden);
  const installed = visible.filter(a => a.installed).length;
  const updates = visible.filter(a => a.update).length;
  $('#counts').innerHTML = `<div class="count"><strong>${visible.length.toString().padStart(2,'0')}</strong><span>IN LIBRARY</span></div><div class="count"><strong>${installed.toString().padStart(2,'0')}</strong><span>INSTALLED</span></div><div class="count update"><strong>${updates.toString().padStart(2,'0')}</strong><span>UPDATES</span></div>`;
  $('#all-count').textContent = visible.length;
  $('#update-count').textContent = updates || '';
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
