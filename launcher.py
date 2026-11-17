#!/usr/bin/env python3
"""LaunchCraft: an on-demand, standard-library-only local application launcher."""
import argparse
import copy
import fnmatch
import hashlib
import http.server
import json
import mimetypes
import os
from pathlib import Path
import queue
import re
import secrets
import shlex
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import zipfile
try:
    import fcntl
except ImportError:
    fcntl = None
try:
    import msvcrt
except ImportError:
    msvcrt = None

IS_WIN = sys.platform == 'win32'
IS_MAC = sys.platform == 'darwin'
ROOT = Path(__file__).resolve().parent


def detect_platform():
    if IS_WIN:
        return 'windows'
    if IS_MAC:
        return 'macos'
    try:
        text = Path('/etc/os-release').read_text().lower()
        if any(x in text for x in ('id=arch', 'id=omarchy', 'id_like=arch', 'id_like="arch')):
            return 'arch'
        if any(x in text for x in ('id=ubuntu', 'id=debian', 'id=kubuntu', 'id_like=debian', 'id_like=ubuntu')):
            return 'debian'
        if any(x in text for x in ('id=fedora', 'id_like=fedora')):
            return 'fedora'
    except OSError:
        pass
    return 'linux'
ID_RE = re.compile(r'^[a-z0-9][a-z0-9._-]*$')
PKG_RE = re.compile(r'^[a-zA-Z0-9@_+][a-zA-Z0-9@._+-]*$')


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as out:
            json.dump(value, out, indent=2, ensure_ascii=False)
            out.write('\n')
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def validate_catalog(data):
    """Raise ValueError with a useful path for invalid catalog data."""
    def require(ok, message):
        if not ok:
            raise ValueError(message)
    require(isinstance(data, dict), 'catalog must be an object')
    require(set(data) == {'version', 'apps'}, 'catalog fields must be version and apps')
    require(type(data.get('version')) is int and data['version'] == 1, 'version must be 1')
    require(isinstance(data.get('apps'), list), 'apps must be a list')
    seen = set()
    for i, app in enumerate(data['apps']):
        p = f'apps[{i}]'
        require(isinstance(app, dict), f'{p} must be an object')
        require(set(app) == {'id', 'name', 'publisher', 'category', 'tagline', 'accent', 'website', 'source', 'install', 'hidden'}, f'{p} has missing or unsupported fields')
        for key in ('id', 'name', 'publisher', 'category', 'tagline', 'accent', 'website'):
            require(isinstance(app.get(key), str) and bool(app[key].strip()), f'{p}.{key} must be a nonempty string')
        require(bool(re.fullmatch(r'[a-z0-9][a-z0-9-]*', app['id'])), f'{p}.id must contain lowercase letters, numbers, and hyphens')
        require(app['id'] not in seen, f'duplicate id: {app["id"]}')
        seen.add(app['id'])
        require(bool(re.fullmatch(r'#[0-9a-fA-F]{6}', app['accent'])), f'{p}.accent must be #rrggbb')
        u = urllib.parse.urlparse(app['website'])
        require(u.scheme == 'https' and bool(u.netloc), f'{p}.website must be an HTTPS URL')
        require(type(app.get('hidden')) is bool, f'{p}.hidden must be boolean')
        src, ins = app.get('source'), app.get('install')
        require(isinstance(src, dict), f'{p}.source must be an object')
        require(isinstance(ins, dict), f'{p}.install must be an object')
        require(src.get('type') in ('github_release', 'arch_repo', 'aur', 'winget', 'brew', 'apt', 'dnf', 'flatpak', 'local'), f'{p}.source.type is unsupported')
        require(ins.get('type') in ('pacman_pkg', 'appimage', 'tarball', 'pacman', 'aur', 'winget', 'zip', 'msi', 'exe', 'brew', 'dmg', 'apt', 'deb', 'dnf', 'rpm', 'flatpak', 'local'), f'{p}.install.type is unsupported')
        source_fields = {'github_release': {'type', 'repo', 'asset_pattern', 'prerelease'}, 'local': {'type', 'path'}}.get(src['type'], {'type', 'package'})
        install_fields = {'type', 'launch'} if ins['type'] == 'local' else {'type', 'launch', {'appimage': 'binary_name', 'tarball': 'bin', 'zip': 'bin'}.get(ins['type'], 'package')}
        require(set(src) <= source_fields, f'{p}.source has unsupported fields')
        require(set(ins) == install_fields, f'{p}.install has missing or unsupported fields')
        if src['type'] == 'github_release':
            require(isinstance(src.get('repo'), str) and bool(re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', src['repo'])), f'{p}.source.repo must be owner/repo')
            require(isinstance(src.get('asset_pattern'), str) and bool(src['asset_pattern']), f'{p}.source.asset_pattern is required (glob)')
            require(type(src.get('prerelease', False)) is bool, f'{p}.source.prerelease must be boolean')
            require(ins['type'] in ('pacman_pkg', 'appimage', 'tarball', 'zip', 'msi', 'exe', 'dmg', 'deb', 'rpm'), f'{p}: GitHub source requires a file installer')
        elif src['type'] == 'local':
            require(isinstance(src.get('path'), str) and bool(src['path'].strip()), f'{p}.source.path is required')
            require(ins['type'] == 'local', f'{p}: local source requires local installer')
        else:
            require(isinstance(src.get('package'), str) and bool(PKG_RE.fullmatch(src['package'])), f'{p}.source.package is invalid')
            require(ins['type'] == ('pacman' if src['type'] == 'arch_repo' else src['type']), f'{p}: source and installer do not match')
        if ins['type'] in ('pacman_pkg', 'pacman', 'aur', 'winget', 'msi', 'exe', 'brew', 'dmg', 'apt', 'deb', 'dnf', 'rpm', 'flatpak'):
            require(isinstance(ins.get('package'), str) and bool(PKG_RE.fullmatch(ins['package'])), f'{p}.install.package is invalid')
        if ins['type'] == 'appimage':
            b = ins.get('binary_name', '')
            require(isinstance(b, str) and bool(ID_RE.fullmatch(b.lower())) and b not in ('.', '..'), f'{p}.install.binary_name must be a filename')
        if ins['type'] in ('tarball', 'zip'):
            b = ins.get('bin', '')
            require(isinstance(b, str) and bool(b) and not Path(b).is_absolute() and '..' not in Path(b).parts, f'{p}.install.bin must be a relative path')
        launch = ins.get('launch')
        require(isinstance(launch, str) and bool(launch.strip()), f'{p}.install.launch must be a command string')
        try:
            require(bool(shlex.split(launch)), f'{p}.install.launch is empty')
        except ValueError as e:
            raise ValueError(f'{p}.install.launch: {e}') from e
    return data


class Catalog:
    def __init__(self, path):
        self.path = Path(path).resolve()

    def load(self):
        return validate_catalog(json.loads(self.path.read_text()))

    def mutate(self, action):
        # Shared lock used by the HTTP editor and launchcraft-ctl. Never held for downloads.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix(self.path.suffix + '.lock').open('a') as lock:
            if fcntl is not None:
                fcntl.flock(lock, fcntl.LOCK_EX)
            elif msvcrt is not None:
                msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
            try:
                before = self.path.read_bytes()
                data = validate_catalog(json.loads(before))
                action(data)
                validate_catalog(data)
                if self.path.read_bytes() != before:
                    raise ValueError('Catalog changed externally; retry your edit')
                atomic_json(self.path, data)
                return data
            finally:
                if msvcrt is not None and fcntl is None:
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


class Cancelled(Exception):
    pass


class Engine:
    def __init__(self, catalog, home=None, api_base='https://api.github.com', web_base='https://github.com'):
        self.catalog = Catalog(catalog)
        self.platform = detect_platform()
        self.home = Path(home or Path.home())
        if IS_WIN and home is None:
            local = Path(os.environ.get('LOCALAPPDATA') or self.home / 'AppData/Local')
            self.data = local / 'ArminLauncher'
            self.downloads = local / 'ArminLauncher/downloads'
        else:
            self.data = self.home / '.local/share/launchcraft'
            self.downloads = self.home / '.cache/launchcraft/downloads'
        self.state_path = self.data / 'state.json'
        self.lock = threading.RLock()
        try:
            self.state = json.loads(self.state_path.read_text())
        except (OSError, ValueError):
            self.state = {}
        for key in ('installed', 'releases', 'http', 'prefs'):
            self.state.setdefault(key, {})
        self.api_base, self.web_base = api_base.rstrip('/'), web_base.rstrip('/')
        self.gh_token = self._detect_gh_token() if self.api_base == 'https://api.github.com' else ''
        self.listeners = set()
        self.jobs = {}
        self.busy = False
        self.refreshing = False
        self.cancel = threading.Event()
        self.pkg_lock = threading.Lock()
        self.active_workers = 0
        self.worker = None
        self.notice = ''
        self.last_error = ''
        self.warnings = []

    def save(self):
        with self.lock:
            atomic_json(self.state_path, self.state)

    def emit(self, kind, data):
        with self.lock:
            for listener in tuple(self.listeners):
                try:
                    listener.put_nowait((kind, data))
                except queue.Full:
                    pass

    def status(self, appid, status, **fields):
        with self.lock:
            self.jobs[appid] = dict(status=status, **fields)
        self.emit('progress', dict(id=appid, **self.jobs[appid]))

    def command(self, argv, timeout=30):
        try:
            # Refresh helpers must not outlive the final browser connection.
            if self.refreshing and threading.current_thread() is self.worker:
                kw = {} if IS_WIN else {'start_new_session': True}
                process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **kw)
                deadline = time.monotonic() + timeout
                try:
                    while True:
                        if self.cancel.is_set():
                            raise Cancelled()
                        if time.monotonic() > deadline:
                            raise subprocess.TimeoutExpired(argv, timeout)
                        try:
                            stdout, stderr = process.communicate(timeout=.2)
                            return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
                        except subprocess.TimeoutExpired:
                            continue
                finally:
                    if process.poll() is None:
                        if IS_WIN:
                            process.terminate()
                        else:
                            os.killpg(process.pid, signal.SIGTERM)
                    process.communicate()
            return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as e:
            return subprocess.CompletedProcess(argv, 127, '', str(e))

    def installed(self, app):
        ins = app['install']
        record = self.state['installed'].get(app['id'], {})
        if ins['type'] in ('pacman_pkg', 'pacman', 'aur'):
            if IS_WIN:
                return None
            p = self.command(['pacman', '-Q', ins['package']])
            if p.returncode == 0:
                return p.stdout.strip().split(maxsplit=1)[-1]
            return None
        if ins['type'] == 'winget':
            if IS_WIN and shutil.which('winget'):
                p = self.command(['winget', 'list', '--id', ins['package'], '-e', '--accept-source-agreements'], timeout=15)
                if p.returncode == 0:
                    for line in reversed(p.stdout.splitlines()):
                        if ins['package'].lower() in line.lower():
                            parts = line.split()
                            return parts[-1] if len(parts) >= 2 else (record.get('version') or 'installed')
            return record.get('version')
        if ins['type'] in ('msi', 'exe'):
            if record.get('version'):
                return record['version']
            exe = shlex.split(ins['launch'], posix=not IS_WIN)[0]
            return 'installed' if shutil.which(exe) else None
        if ins['type'] == 'local':
            exe = shlex.split(ins['launch'], posix=not IS_WIN)[0]
            src_path = Path(app['source']['path']).expanduser()
            if shutil.which(exe) or Path(exe).expanduser().is_file() or src_path.exists():
                return 'local'
            return None
        target = (self.home / 'Applications' / ins['binary_name'] if ins['type'] == 'appimage'
                  else self.data / 'apps' / app['id'] / 'current' / ins['bin'])
        if target.is_file():
            return record.get('version') or 'unknown'
        return None

    def privilege_cmd(self):
        if os.environ.get('ARMIN_LAUNCHER_SUDO') == '1':
            return [] if hasattr(os, 'geteuid') and os.geteuid() == 0 else ['sudo', '-n']
        return ['pkexec']

    def is_compatible(self, app):
        t = app['install']['type']
        if t == 'local':
            return bool(self.installed(app))
        if self.platform == 'windows':
            return t in ('winget', 'msi', 'exe', 'zip')
        if self.platform == 'macos':
            return t in ('brew', 'dmg', 'tarball')
        if t in ('pacman_pkg', 'pacman', 'aur'):
            return self.platform == 'arch' or bool(shutil.which('pacman'))
        if t in ('apt', 'deb'):
            return self.platform == 'debian' or bool(shutil.which('apt-get'))
        if t in ('dnf', 'rpm'):
            return self.platform == 'fedora' or bool(shutil.which('dnf'))
        if t == 'flatpak':
            return bool(shutil.which('flatpak'))
        return t in ('appimage', 'tarball')

    def icon_url(self, appid):
        icons_dir = ROOT / 'ui' / 'icons'
        for ext in ('png', 'svg'):
            if (icons_dir / f'{appid}.{ext}').is_file():
                return f'/icons/{appid}.{ext}'
        return None

    def snapshot(self):
        # Disk reads ensure another agent's catalog changes appear without a restart.
        apps = copy.deepcopy(self.catalog.load()['apps'])
        with self.lock:
            for app in apps:
                release = self.state['releases'].get(app['id'], {})
                app['installed'] = self.installed(app)
                app['latest'] = release.get('tag')
                app['release'] = release
                app['update'] = bool(app['installed'] and app['latest'] and self.newer(app['latest'], app['installed']))
                app['job'] = self.jobs.get(app['id'])
                app['verification'] = self.state['installed'].get(app['id'], {}).get('verification')
                app['icon'] = self.icon_url(app['id'])
                app['compatible'] = self.is_compatible(app)
                app['data_paths'] = [str(p) for p in self.user_data_paths(app)]
            return dict(apps=apps, busy=self.busy, refreshing=self.refreshing, notice=self.notice, last_error=self.last_error, warnings=self.warnings, platform=self.platform, prefs=copy.deepcopy(self.state.get('prefs', {})), revision=time.monotonic())

    def newer(self, latest, installed):
        if installed == 'unknown':
            return True
        a, b = latest.lstrip('v'), installed.lstrip('v')
        if a == b:
            return False
        if shutil.which('vercmp'):
            p = self.command(['vercmp', a, b])
            if p.returncode == 0:
                return int(p.stdout.strip()) > 0
        # Handles ordinary semver and pacman package-release suffixes without dependencies.
        def parts(v):
            return tuple((1, int(x)) if x.isdigit() else (0, x) for x in re.findall(r'\d+|[A-Za-z]+', v))
        pa, pb = parts(a), parts(b)
        if pb[:len(pa)] == pa:
            return False
        return pa > pb

    def _detect_gh_token(self):
        for env_key in ('GITHUB_TOKEN', 'GH_TOKEN'):
            val = os.environ.get(env_key, '').strip()
            if val:
                return val
        if shutil.which('gh'):
            try:
                p = subprocess.run(['gh', 'auth', 'token'], capture_output=True, text=True, timeout=3)
                if p.returncode == 0 and p.stdout.strip():
                    return p.stdout.strip()
            except (OSError, subprocess.TimeoutExpired):
                pass
        return ''

    def request(self, url, headers=None, method='GET'):
        req_headers = {'User-Agent': 'ArminLauncher/1', **(headers or {})}
        if self.gh_token and url.startswith('https://api.github.com/'):
            req_headers.setdefault('Authorization', f'Bearer {self.gh_token}')
        return urllib.request.urlopen(urllib.request.Request(url, headers=req_headers, method=method), timeout=20)

    def github_release(self, app):
        src = app['source']
        url = f'{self.api_base}/repos/{src["repo"]}/releases' + ('?per_page=30' if src.get('prerelease') else '/latest')
        cached = self.state['http'].get(url, {})
        headers = {'Accept': 'application/vnd.github+json'}
        if cached.get('etag'):
            headers['If-None-Match'] = cached['etag']
        try:
            with self.request(url, headers) as response:
                body = json.load(response)
                self.state['http'][url] = {'etag': response.headers.get('ETag'), 'body': body}
        except urllib.error.HTTPError as e:
            e.close()
            if e.code == 304 and 'body' in cached:
                body = cached['body']
            elif e.code == 404:
                return dict(tag=None, notes='No releases published yet.', url=f'{self.web_base}/{src["repo"]}/releases', checked=time.time())
            elif e.code in (403, 429):
                return self.github_fallback(app)
            else:
                raise
        if isinstance(body, list):
            body = next((r for r in body if not r.get('draft')), None)
            if not body:
                raise ValueError('No published releases')
        tag = body['tag_name']
        pattern = src['asset_pattern'].replace('{tag}', tag).replace('{version}', tag.lstrip('v'))
        assets = body.get('assets', [])
        matches = [a for a in assets if fnmatch.fnmatchcase(a['name'], pattern)]
        # Stable selection, but tell the operator if the pattern needs narrowing.
        if len(matches) != 1:
            raise ValueError(f'Asset pattern {pattern!r} matched {len(matches)} files; choose exactly one')
        checksum = next((a for a in assets if a['name'].lower() in ('sha256sums.txt', 'sha256sums', 'sha256sum.txt')), None)
        return dict(tag=tag, asset=matches[0], checksum=checksum, notes=body.get('body') or '', url=body.get('html_url', app['website']), published_at=body.get('published_at'), checked=time.time())

    def github_fallback(self, app):
        src = app['source']
        with self.request(f'{self.web_base}/{src["repo"]}/releases/latest', method='HEAD') as response:
            final = response.url
        match = re.search(r'/releases/tag/(.+)$', final)
        if not match:
            raise ValueError('GitHub rate limited; latest release redirect unavailable')
        tag = urllib.parse.unquote(match[1])
        old = copy.deepcopy(self.state['releases'].get(app['id'], {}))
        if old.get('tag') != tag:
            old = dict(tag=tag, notes='', url=final)
            pattern = src['asset_pattern'].replace('{tag}', tag).replace('{version}', tag.lstrip('v'))
            if not any(c in pattern for c in '*?['):
                old['asset'] = dict(name=pattern, browser_download_url=f'{self.web_base}/{src["repo"]}/releases/download/{urllib.parse.quote(tag, safe="")}/{urllib.parse.quote(pattern)}')
            else:
                try:
                    exp_url = f'{self.web_base}/{src["repo"]}/releases/expanded_assets/{urllib.parse.quote(tag, safe="")}'
                    with self.request(exp_url) as r:
                        html = r.read(1024 * 1024).decode('utf-8', 'ignore')
                    hrefs = re.findall(r'href="(/[^"]+/releases/download/[^"]+)"', html)
                    for href in hrefs:
                        fname = urllib.parse.unquote(href.rsplit('/', 1)[-1])
                        if fnmatch.fnmatchcase(fname, pattern):
                            old['asset'] = dict(name=fname, browser_download_url=self.web_base.rstrip('/') + href)
                            break
                except Exception:
                    pass
        old.update(checked=time.time(), warning='GitHub rate limited; version from latest redirect. ' + ('Asset metadata unavailable; refresh later before installing.' if not old.get('asset') else 'Checksum metadata may be unavailable.'))
        return old

    def refresh(self):
        warnings = []
        rate_limited = []
        try:
            apps = self.catalog.load()['apps']
            updates = {}
            for source, argv in [('arch_repo', ['pacman', '-Qu']), ('aur', [shutil.which('yay') or shutil.which('paru'), '-Qua'])]:
                if not any(a['source']['type'] == source for a in apps):
                    continue
                if not argv[0] or not shutil.which(argv[0]):
                    warnings.append(f'{source}: package helper is not installed')
                    continue
                p = self.command(argv, timeout=90)
                # pacman returns 1 for no upgrades. Other failures carry stderr.
                if p.returncode and p.stderr.strip():
                    warnings.append(f'{source}: {p.stderr.strip()}')
                for line in p.stdout.splitlines():
                    fields = line.split()
                    if len(fields) >= 4 and fields[2] == '->':
                        updates[(source, fields[0])] = fields[3]
            for app in apps:
                if self.cancel.is_set():
                    raise Cancelled()
                try:
                    if app['source']['type'] == 'github_release':
                        release = self.github_release(app)
                    elif app['source']['type'] == 'local':
                        release = dict(tag='local', notes='Local user-built application.', url=app['website'], checked=time.time())
                    else:
                        src = app['source']
                        version = updates.get((src['type'], src['package']))
                        if not version and src['type'] == 'arch_repo':
                            p = self.command(['pacman', '-Si', src['package']])
                            m = re.search(r'^Version\s*:\s*(\S+)', p.stdout, re.M)
                            version = m[1] if m else None
                        elif not version and src['type'] == 'winget' and IS_WIN and shutil.which('winget'):
                            p = self.command(['winget', 'show', '--id', src['package'], '-e', '--accept-source-agreements'], timeout=20)
                            m = re.search(r'^Version:\s*(\S+)', p.stdout, re.M)
                            version = m[1] if m else None
                        release = dict(tag=version or self.installed(app), notes='Package updates use the configured package databases.', url=app['website'], checked=time.time())
                    with self.lock:
                        self.state['releases'][app['id']] = release
                    if release.get('warning'):
                        if 'GitHub rate limited' in release['warning']:
                            rate_limited.append(app['name'])
                            if 'Asset metadata unavailable' in release['warning']:
                                warnings.append(f'{app["name"]}: {release["warning"]}')
                        else:
                            warnings.append(f'{app["name"]}: {release["warning"]}')
                except Cancelled:
                    raise
                except Exception as e:
                    warnings.append(f'{app["name"]}: {e}')
            if rate_limited:
                warnings.insert(0, f'GitHub API rate limit reached ({len(rate_limited)} apps); versions fetched via release redirects.')
            self.save()
            self.notice = 'Refresh complete' if not warnings else 'Refresh complete with warnings'
        finally:
            self.warnings = warnings
            self.refreshing = False

    def start(self, action, ids=None, clean=False):
        terminal = ('Complete', 'Cancelled', 'Error')
        with self.lock:
            if action == 'refresh':
                if self.busy:
                    raise ValueError('Another task is running')
            else:
                if self.refreshing:
                    raise ValueError('Refresh is running')
                if ids and any(self.jobs.get(i, {}).get('status') not in (None, *terminal) for i in ids):
                    raise ValueError('This app already has an active task')
            self.active_workers += 1
            self.busy = True
            self.refreshing = action == 'refresh'
            self.last_error = ''
            if self.active_workers == 1:
                self.cancel.clear()
        def work():
            try:
                if action == 'refresh':
                    self.refresh()
                elif action == 'uninstall':
                    self.uninstall(ids[0], clean=clean)
                else:
                    self.install_many(ids)
            except Cancelled:
                self.notice = 'Cancelled. Partial downloads are kept for resume.'
            except Exception as e:
                self.notice = str(e)
                self.last_error = str(e)
                self.emit('error', {'message': str(e)})
            finally:
                with self.lock:
                    self.active_workers = max(0, self.active_workers - 1)
                    self.busy = self.active_workers > 0
                    if action == 'refresh':
                        self.refreshing = False
                try:
                    self.emit('state', self.snapshot())
                except (ValueError, OSError) as e:
                    self.emit('error', {'message': f'Catalog reload failed: {e}'})
        worker = threading.Thread(target=work, name='launchcraft-job', daemon=action == 'refresh')
        if action == 'refresh':
            self.worker = worker
        worker.start()
        self.emit('state', self.snapshot())

    def download(self, asset, checksum=None, appid='', cancel=None):
        cancel = cancel or self.cancel
        name = asset['name']
        if Path(name).name != name or name in ('.', '..'):
            raise ValueError('Unsafe asset filename')
        # Sidecar identity avoids resuming another release with the same filename.
        url = asset['browser_download_url']
        self.downloads.mkdir(parents=True, exist_ok=True)
        part, final = self.downloads / (name + '.part'), self.downloads / name
        metadata_path = self.downloads / (name + '.source.json')
        try:
            metadata = json.loads(metadata_path.read_text())
        except (OSError, ValueError):
            metadata = {}
        if metadata.get('url') and metadata['url'] != url:
            part.unlink(missing_ok=True)
            final.unlink(missing_ok=True)
            metadata = {}
        metadata['url'] = url
        atomic_json(metadata_path, metadata)
        expected = None
        digest = asset.get('digest') or ''
        if digest.startswith('sha256:'):
            expected = digest[7:].lower()
        elif checksum:
            with self.request(checksum['browser_download_url']) as response:
                sums = response.read(4 * 1024 * 1024).decode('utf-8')
            for line in sums.splitlines():
                m = re.match(r'^([0-9a-fA-F]{64})\s+\*?(.+?)\s*$', line)
                if m and m[2].removeprefix('./') == name:
                    expected = m[1].lower()
                    break
            if not expected:
                raise ValueError(f'{name} missing from published SHA256SUMS')
        if expected and not re.fullmatch('[0-9a-f]{64}', expected):
            raise ValueError('Invalid published SHA-256 digest')
        if final.exists():
            if expected and self.file_hash(final) == expected:
                return final, 'SHA-256 verified'
            final.unlink()
        offset = part.stat().st_size if part.exists() else 0
        headers = {'Range': f'bytes={offset}-'} if offset else {}
        if offset and metadata.get('validator'):
            headers['If-Range'] = metadata['validator']
        try:
            response = self.request(url, headers)
        except urllib.error.HTTPError as e:
            e.close()
            if e.code == 416:
                part.unlink(missing_ok=True)
                response = self.request(url)
                offset = 0
            else:
                raise
        with response:
            metadata['validator'] = response.headers.get('ETag') or response.headers.get('Last-Modified')
            atomic_json(metadata_path, metadata)
            if response.status == 206:
                m = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+|\*)', response.headers.get('Content-Range', ''))
                if not m or int(m[1]) != offset:
                    raise ValueError('Invalid server resume offset')
            else:
                offset = 0  # Servers may ignore Range: safely restart rather than append.
            length = response.headers.get('Content-Length')
            total = offset + int(length) if length else asset.get('size', 0)
            count, last = offset, 0
            with part.open('ab' if offset else 'wb') as out:
                while True:
                    if cancel.is_set():
                        raise Cancelled()
                    chunk = response.read(128 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    count += len(chunk)
                    if time.monotonic() - last > .1:
                        self.status(appid, 'Downloading', bytes=count, total=total, percent=round(count / total * 100, 1) if total else None)
                        last = time.monotonic()
            if total and count != total:
                raise ValueError('Download interrupted; retry to resume')
        self.status(appid, 'Verifying', bytes=count, total=total)
        actual = self.file_hash(part)
        if expected and actual != expected:
            part.unlink(missing_ok=True)
            raise ValueError(f'SHA-256 mismatch for {name}; download rejected')
        if cancel.is_set():
            raise Cancelled()
        os.replace(part, final)
        return final, 'SHA-256 verified' if expected else f'No publisher checksum; SHA-256 {actual}'

    @staticmethod
    def file_hash(path):
        h = hashlib.sha256()
        with Path(path).open('rb') as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b''):
                h.update(chunk)
        return h.hexdigest()

    def transaction(self, argv, ids):
        for appid in ids:
            self.status(appid, 'Queued', message='Waiting for package manager queue…')
        with self.pkg_lock:
            if self.cancel.is_set():
                raise Cancelled()
            for appid in ids:
                self.status(appid, 'Installing', message='Authentication may be required. Package transactions finish safely before cancellation.')
            # Do not terminate pacman in the middle of its database transaction.
            with tempfile.TemporaryFile(mode='w+') as output:
                process = subprocess.Popen(argv, stdout=output, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
                process.wait()
                output.seek(0)
                log = output.read()[-10000:]
                if process.returncode:
                    raise ValueError(f'Installer exited {process.returncode}: {log.strip()}')

    def app(self, appid):
        return next((a for a in self.catalog.load()['apps'] if a['id'] == appid), None)

    def install_many(self, ids=None):
        apps = self.catalog.load()['apps']
        if ids is None:
            snap = self.snapshot()
            ids = [a['id'] for a in snap['apps'] if a['update'] and not a['hidden']]
        chosen = [a for a in apps if a['id'] in ids]
        if len(chosen) != len(set(ids)):
            raise ValueError('Unknown app ID')
        packages = []
        for a in chosen:
            self.status(a['id'], 'Queued')
        try:
            for app in chosen:
                appid, ins = app['id'], app['install']
                if self.cancel.is_set():
                    raise Cancelled()
                if app['source']['type'] == 'github_release':
                    release = self.state['releases'].get(appid)
                    if not release or not release.get('asset'):
                        release = self.github_release(app)
                        self.state['releases'][appid] = release
                        self.save()
                    if not release.get('asset'):
                        raise ValueError(f'{app["name"]}: asset metadata unavailable; refresh after GitHub rate limit resets')
                    path, verification = self.download(release['asset'], release.get('checksum'), appid)
                    if ins['type'] == 'pacman_pkg':
                        packages.append((app, path, release['tag'], verification))
                        self.status(appid, 'Ready', message=verification)
                        continue
                    self.status(appid, 'Installing', message=verification)
                    if ins['type'] == 'appimage':
                        target = self.home / 'Applications' / ins['binary_name']
                        target.parent.mkdir(parents=True, exist_ok=True)
                        fd, staging = tempfile.mkstemp(prefix='.launchcraft-', dir=target.parent)
                        os.close(fd)
                        try:
                            shutil.copyfile(path, staging)
                            os.chmod(staging, 0o755)
                            if self.cancel.is_set():
                                raise Cancelled()
                            os.replace(staging, target)
                        finally:
                            Path(staging).unlink(missing_ok=True)
                    elif ins['type'] == 'zip':
                        target = self.install_zip(app, path, release['tag'])
                    elif ins['type'] == 'msi':
                        self.transaction(['msiexec', '/i', str(path), '/passive', '/norestart'], [appid])
                        target = path
                    elif ins['type'] == 'exe':
                        self.transaction([str(path), '/S'], [appid])
                        target = path
                    else:
                        target = self.install_tarball(app, path, release['tag'])
                    self.record(app, release['tag'], target, verification)
                    if IS_WIN and ins['type'] == 'zip':
                        install_windows_shortcut(app['name'], str(target))
                    elif not IS_WIN:
                        self.desktop(app, target)
                    self.sync_mcp(app)
                    self.cleanup_download(path)
                elif ins['type'] == 'winget':
                    if not shutil.which('winget'):
                        raise ValueError('winget is not installed on this Windows system')
                    self.transaction(['winget', 'install', '--id', ins['package'], '-e', '--accept-package-agreements', '--accept-source-agreements'], [appid])
                    self.sync_mcp(app)
                elif ins['type'] == 'pacman':
                    self.transaction([*self.privilege_cmd(), 'pacman', '-S', '--needed', '--noconfirm', ins['package']], [appid])
                    self.sync_mcp(app)
                elif ins['type'] == 'aur':
                    helper = shutil.which('yay') or shutil.which('paru')
                    if not helper:
                        raise ValueError('Install yay or paru to manage AUR applications')
                    priv = self.privilege_cmd()
                    sudo_args = ['--sudo', priv[0], '--sudoflags', ' '.join(priv[1:])] if priv else []
                    self.transaction([helper, '-S', '--needed', '--noconfirm', *sudo_args, ins['package']], [appid])
                    self.sync_mcp(app)
                else:
                    raise ValueError(f'Installer type {ins["type"]} is not yet implemented on {self.platform}')
                self.status(appid, 'Complete', message=verification if app['source']['type'] == 'github_release' else 'Package installation completed')
            if packages:
                self.transaction([*self.privilege_cmd(), 'pacman', '-U', '--noconfirm', *[str(p) for _, p, _, _ in packages]], [a['id'] for a, _, _, _ in packages])
                for app, path, tag, verification in packages:
                    self.record(app, tag, path, verification)
                    self.sync_mcp(app)
                    self.cleanup_download(path)
                    self.status(app['id'], 'Complete', message=verification)
            self.notice = 'All requested installs completed' if chosen else 'Everything is up to date'
        except Exception as e:
            for a in chosen:
                if self.jobs.get(a['id'], {}).get('status') != 'Complete':
                    self.status(a['id'], 'Cancelled' if isinstance(e, Cancelled) else 'Error', message=str(e) or 'Cancelled')
            raise

    def install_tarball(self, app, path, tag):
        base = self.data / 'apps' / app['id']
        releases = base / 'releases'
        releases.mkdir(parents=True, exist_ok=True)
        safe_tag = re.sub(r'[^a-zA-Z0-9._-]', '_', tag)
        if safe_tag in ('.', '..', ''):
            raise ValueError('Unsafe release tag')
        staging = Path(tempfile.mkdtemp(prefix='.extract-', dir=releases))
        dest = releases / safe_tag
        try:
            with tarfile.open(path, 'r:*') as archive:
                # Only files/directories: blocks path traversal, devices, and link chains.
                for member in archive:
                    if self.cancel.is_set():
                        raise Cancelled()
                    rel = Path(member.name)
                    if rel.is_absolute() or '..' in rel.parts or not (member.isfile() or member.isdir()):
                        raise ValueError(f'Unsafe archive member: {member.name}')
                    archive.extract(member, staging, filter='data')
            binary = staging / app['install']['bin']
            if not binary.is_file():
                raise ValueError(f'Archive does not contain {app["install"]["bin"]}')
            binary.chmod(binary.stat().st_mode | 0o111)
            if dest.exists():
                # Reuse a previously complete immutable release; never rewrite the active tree.
                if not (dest / app['install']['bin']).is_file():
                    raise ValueError('Existing release directory is incomplete')
            else:
                os.replace(staging, dest)
            link = base / ('.current-' + secrets.token_hex(5))
            try:
                link.symlink_to(Path('releases') / safe_tag)
                os.replace(link, base / 'current')
            finally:
                link.unlink(missing_ok=True)
            return base / 'current' / app['install']['bin']
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    def install_zip(self, app, path, tag):
        base = self.data / 'apps' / app['id']
        releases = base / 'releases'
        releases.mkdir(parents=True, exist_ok=True)
        safe_tag = re.sub(r'[^a-zA-Z0-9._-]', '_', tag)
        if safe_tag in ('.', '..', ''):
            raise ValueError('Unsafe release tag')
        staging = Path(tempfile.mkdtemp(prefix='.extract-', dir=releases))
        dest = releases / safe_tag
        try:
            with zipfile.ZipFile(path, 'r') as archive:
                for member in archive.infolist():
                    if self.cancel.is_set():
                        raise Cancelled()
                    rel = Path(member.filename)
                    if rel.is_absolute() or '..' in rel.parts:
                        raise ValueError(f'Unsafe archive member: {member.filename}')
                    archive.extract(member, staging)
            binary = staging / app['install']['bin']
            if not binary.is_file():
                raise ValueError(f'Archive does not contain {app["install"]["bin"]}')
            if not dest.exists():
                os.replace(staging, dest)
            current = base / 'current'
            if IS_WIN:
                if current.exists() or current.is_symlink():
                    shutil.rmtree(current, ignore_errors=True)
                shutil.copytree(dest, current)
            else:
                link = base / ('.current-' + secrets.token_hex(5))
                try:
                    link.symlink_to(Path('releases') / safe_tag)
                    os.replace(link, current)
                finally:
                    link.unlink(missing_ok=True)
            return current / app['install']['bin']
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    def mcp_spec(self, app):
        appid = app['id']
        # Known CLI/MCP binaries shipped by apps in the catalog.
        candidates = [f'{appid}-cli']
        launch = shlex.split(app['install']['launch'], posix=not IS_WIN)[0]
        if appid in ('fieldcraft', 'concat'):
            candidates.append(launch)
        for cmd in candidates:
            resolved = shutil.which(cmd)
            if resolved:
                return {'command': resolved, 'args': ['mcp']}
        return None

    def sync_mcp(self, app, remove=False):
        appid = app['id']
        spec = None if remove else self.mcp_spec(app)
        if not remove and not spec:
            return
        # 1. JSON-based MCP configs (Antigravity, Claude Code, Claude Desktop)
        json_configs = [
            self.home / '.gemini/config/mcp_config.json',
            self.home / '.claude.json',
        ]
        if IS_WIN and os.environ.get('APPDATA'):
            json_configs.append(Path(os.environ['APPDATA']) / 'Claude/claude_desktop_config.json')
        elif IS_MAC:
            json_configs.append(self.home / 'Library/Application Support/Claude/claude_desktop_config.json')
        else:
            json_configs.append(self.home / '.config/Claude/claude_desktop_config.json')

        for cfg in json_configs:
            if not cfg.is_file():
                continue
            try:
                data = json.loads(cfg.read_text())
                if not isinstance(data, dict):
                    continue
                servers = data.setdefault('mcpServers', {})
                if not isinstance(servers, dict):
                    continue
                if remove:
                    if appid in servers:
                        servers.pop(appid, None)
                        atomic_json(cfg, data)
                else:
                    servers[appid] = spec
                    atomic_json(cfg, data)
            except (OSError, ValueError):
                pass

        # 2. Codex TOML config (~/.codex/config.toml)
        codex_cfg = self.home / '.codex/config.toml'
        if codex_cfg.is_file():
            try:
                text = codex_cfg.read_text()
                header = f'[mcp_servers.{appid}]'
                pattern = re.compile(rf'(?ms)^\[mcp_servers\.{re.escape(appid)}\]\n.*?(?=^\[|\Z)')
                text = pattern.sub('', text).rstrip() + '\n'
                if not remove:
                    args_toml = ', '.join(json.dumps(a) for a in spec['args'])
                    block = f'\n{header}\ncommand = {json.dumps(spec["command"])}\nargs = [{args_toml}]\n'
                    text = text + block
                codex_cfg.write_text(text)
            except OSError:
                pass

    def record(self, app, version, path, verification):
        with self.lock:
            self.state['installed'][app['id']] = dict(version=version, path=str(path), verification=verification, date=time.time())
            self.save()

    def launch_argv(self, app, target=None):
        launch = app['install']['launch']
        argv = shlex.split(launch, posix=not IS_WIN) if isinstance(launch, str) else list(launch)
        ins = app['install']
        if ins['type'] in ('appimage', 'tarball', 'zip'):
            target = target or (self.home / 'Applications' / ins['binary_name'] if ins['type'] == 'appimage' else self.data / 'apps' / app['id'] / 'current' / ins['bin'])
            argv[0] = str(target)
        return [str(Path(x).expanduser()) if x.startswith('~/') else x for x in argv]

    def desktop(self, app, target):
        path = self.home / '.local/share/applications' / f'launchcraft-{app["id"]}.desktop'
        path.parent.mkdir(parents=True, exist_ok=True)
        def quote(arg):
            return '"' + arg.replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%') + '"'
        name = app['name'].replace('\n', ' ').replace('\r', ' ')
        path.write_text('[Desktop Entry]\nType=Application\nName=' + name + '\nExec=' + ' '.join(quote(x) for x in self.launch_argv(app, target)) + '\nTerminal=false\nCategories=Utility;\n')

    def open_app(self, appid):
        app = self.app(appid)
        if not app or not self.installed(app):
            raise ValueError('App is not installed')
        kw = {'creationflags': subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP} if IS_WIN else {'start_new_session': True}
        subprocess.Popen(self.launch_argv(app), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)

    def cleanup_download(self, path):
        if not path:
            return
        p = Path(path)
        for candidate in (p, p.parent / (p.name + '.part'), p.parent / (p.name + '.source.json')):
            candidate.unlink(missing_ok=True)

    def user_data_paths(self, app):
        appid = app['id']
        name = app['name']
        pkg = app['install'].get('package', '')
        candidates = []
        if IS_WIN:
            appdata = Path(os.environ.get('APPDATA') or self.home / 'AppData/Roaming')
            local = Path(os.environ.get('LOCALAPPDATA') or self.home / 'AppData/Local')
            custom_win = {
                'blender': [appdata / 'Blender Foundation/Blender', local / 'Blender Foundation/Blender'],
                'lemon-studio': [appdata / 'Lemon Studio', local / 'Lemon Studio'],
            }
            if appid in custom_win:
                candidates.extend(custom_win[appid])
            for key in {appid, name}:
                candidates.extend([appdata / key, local / key])
        else:
            cfg = self.home / '.config'
            share = self.home / '.local/share'
            cache = self.home / '.cache'
            custom_linux = {
                'krita': [cfg / 'kritarc', cfg / 'kritadisplayrc', share / 'krita', cache / 'krita'],
                'kdenlive': [cfg / 'kdenliverc', cfg / 'kdenlive', share / 'kdenlive', cache / 'kdenlive'],
                'lemon-studio': [cfg / 'lemonstudio', share / 'lemonstudio', cache / 'lemonstudio'],
                'solidcraft': [cfg / 'solidcraft', share / 'solidcraft', cache / 'solidcraft', cfg / 'io.tangencylabs.solidcraft', share / 'io.tangencylabs.solidcraft', cache / 'io.tangencylabs.solidcraft'],
            }
            if appid in custom_linux:
                candidates.extend(custom_linux[appid])
            for key in {appid, *( [pkg] if pkg and '.' in pkg else [] )}:
                candidates.extend([cfg / key, share / key, cache / key])
        seen = []
        for c in candidates:
            if c not in seen and c != self.home:
                seen.append(c)
        return seen

    def uninstall(self, appid, clean=False):
        app = self.app(appid)
        if not app:
            raise ValueError('Unknown app ID')
        ins = app['install']
        self.status(appid, 'Uninstalling')
        try:
            if ins['type'] in ('pacman_pkg', 'pacman', 'aur'):
                self.transaction([*self.privilege_cmd(), 'pacman', '-R', '--noconfirm', ins['package']], [appid])
            elif ins['type'] == 'winget':
                if not shutil.which('winget'):
                    raise ValueError('winget is not installed on this Windows system')
                self.transaction(['winget', 'uninstall', '--id', ins['package'], '-e'], [appid])
            elif ins['type'] == 'appimage':
                (self.home / 'Applications' / ins['binary_name']).unlink(missing_ok=True)
            else:
                base = self.data / 'apps' / appid
                if base.is_symlink():
                    raise ValueError('Refusing to remove linked application directory')
                if base.exists():
                    shutil.rmtree(base)
            if IS_WIN:
                appdata = os.environ.get('APPDATA')
                if appdata:
                    safe_name = re.sub(r'[<>:"/\\|?*]', '', app['name']).strip() or 'App'
                    (Path(appdata) / 'Microsoft/Windows/Start Menu/Programs' / f'{safe_name}.lnk').unlink(missing_ok=True)
            else:
                (self.home / '.local/share/applications' / f'launchcraft-{appid}.desktop').unlink(missing_ok=True)
            release_asset = self.state.get('releases', {}).get(appid, {}).get('asset', {}).get('name')
            if release_asset:
                self.cleanup_download(self.downloads / release_asset)
            if clean:
                for p in self.user_data_paths(app):
                    if p.is_symlink() or p.is_file():
                        p.unlink(missing_ok=True)
                    elif p.is_dir():
                        shutil.rmtree(p, ignore_errors=True)
            self.sync_mcp(app, remove=True)
            self.state['installed'].pop(appid, None)
            self.save()
            self.status(appid, 'Complete')
            self.notice = f'{app["name"]} clean-uninstalled' if clean else f'{app["name"]} uninstalled'
        except Exception as e:
            self.status(appid, 'Error', message=str(e))
            raise


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, engine, port=0, grace=3.5, startup_timeout=20):
        super().__init__(('127.0.0.1', port), Handler)
        self.engine = engine
        self.token = secrets.token_urlsafe(32)
        self.origin = f'http://127.0.0.1:{self.server_port}'
        self.grace, self.startup_timeout = grace, startup_timeout
        self.last_client = time.monotonic()
        self.ever_connected = False
        self.stopping = threading.Event()
        self.lifecycle = threading.RLock()

    def monitor(self):
        while not self.stopping.wait(.2):
            with self.lifecycle, self.engine.lock:
                if self.engine.listeners or (self.engine.busy and not self.engine.refreshing):
                    self.last_client = time.monotonic()
                    continue
                limit = self.grace if self.ever_connected else self.startup_timeout
                if time.monotonic() - self.last_client >= limit:
                    self.engine.cancel.set()
                    self.stopping.set()
                    break
        self.shutdown()

    def run(self):
        watcher = threading.Thread(target=self.monitor, name='launchcraft-lifetime', daemon=True)
        watcher.start()
        try:
            self.serve_forever(poll_interval=.1)
        finally:
            self.stopping.set()
            self.server_close()


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        pass

    def allowed(self):
        host = self.headers.get('Host')
        origin = self.headers.get('Origin')
        return host == self.server.origin.removeprefix('http://') and (not origin or origin == self.server.origin)

    def json(self, status, data):
        content = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(content)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        if not self.allowed():
            self.json(403, {'error': 'Local origin required'})
            return
        path = urllib.parse.urlparse(self.path).path
        if path == '/events':
            self.events()
        elif path == '/api/state':
            try:
                self.json(200, dict(self.server.engine.snapshot(), token=self.server.token))
            except (ValueError, OSError) as e:
                self.json(500, {'error': str(e)})
        elif path in ('/', '/index.html', '/style.css', '/app.js', '/details.json'):
            file = ROOT / 'ui' / ('index.html' if path == '/' else path[1:])
            body = file.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', mimetypes.guess_type(str(file))[0] or 'application/octet-stream')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; img-src 'self' data: https:; base-uri 'none'; frame-ancestors 'none'")
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            self.wfile.write(body)
        elif m := re.fullmatch(r'/icons/([a-z0-9-]+)\.(png|svg)', path):
            file = ROOT / 'ui' / 'icons' / f'{m.group(1)}.{m.group(2)}'
            if not file.is_file():
                self.json(404, {'error': 'Not found'})
                return
            body = file.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'image/svg+xml' if m.group(2) == 'svg' else 'image/png')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Cache-Control', 'public, max-age=86400')
            self.end_headers()
            self.wfile.write(body)
        elif m := re.fullmatch(r'/shots/([a-z0-9-]+)\.(png|jpg|jpeg|webp)', path):
            file = ROOT / 'ui' / 'shots' / f'{m.group(1)}.{m.group(2)}'
            if not file.is_file():
                self.json(404, {'error': 'Not found'})
                return
            body = file.read_bytes()
            ctype = {'png': 'image/png', 'webp': 'image/webp'}.get(m.group(2), 'image/jpeg')
            self.send_response(200)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Cache-Control', 'public, max-age=86400')
            self.end_headers()
            self.wfile.write(body)
        else:
            self.json(404, {'error': 'Not found'})

    def events(self):
        listener = queue.Queue(maxsize=256)
        engine = self.server.engine
        with self.server.lifecycle, engine.lock:
            if self.server.stopping.is_set():
                self.json(503, {'error': 'Server closing'})
                return
            engine.listeners.add(listener)
            self.server.ever_connected = True
        try:
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'close')
            self.send_header('X-Accel-Buffering', 'no')
            self.end_headers()
            self.connection.settimeout(3)
            self.wfile.write(b'event: connected\ndata: {}\n\n')
            self.wfile.flush()
            while not self.server.stopping.is_set():
                try:
                    kind, data = listener.get(timeout=.5)
                    msg = f'event: {kind}\ndata: {json.dumps(data)}\n\n'.encode()
                except queue.Empty:
                    msg = b': heartbeat\n\n'
                self.wfile.write(msg)
                self.wfile.flush()
        except (OSError, ConnectionError):
            pass
        finally:
            self.close_connection = True
            with self.server.lifecycle, engine.lock:
                engine.listeners.discard(listener)
                self.server.last_client = time.monotonic()

    def do_POST(self):
        if not self.allowed() or not secrets.compare_digest(self.headers.get('X-LaunchCraft-Token', ''), self.server.token):
            self.json(403, {'error': 'Invalid local request token'})
            self.close_connection = True
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 1024 * 1024:
                raise ValueError('JSON body required (max 1 MiB)')
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError('JSON body must be an object')
            engine = self.server.engine
            path = urllib.parse.urlparse(self.path).path
            if path == '/api/refresh':
                engine.start('refresh')
            elif path == '/api/install':
                ids = data.get('ids')
                if ids is not None and (not isinstance(ids, list) or not all(isinstance(i, str) for i in ids)):
                    raise ValueError('ids must be a list')
                engine.start('install', ids)
            elif path == '/api/cancel':
                engine.cancel.set()
                engine.notice = 'Cancellation requested. Active package transactions finish safely.'
            elif path == '/api/open':
                engine.open_app(data['id'])
            elif path == '/api/prefs':
                with engine.lock:
                    prefs = engine.state.setdefault('prefs', {})
                    if 'view' in data:
                        if data['view'] not in ('grid', 'list'):
                            raise ValueError('view must be grid or list')
                        prefs['view'] = data['view']
                    if 'theme' in data:
                        if data['theme'] not in ('dark', 'light'):
                            raise ValueError('theme must be dark or light')
                        prefs['theme'] = data['theme']
                    if 'zoom' in data:
                        z = float(data['zoom'])
                        if not 0.75 <= z <= 1.75:
                            raise ValueError('zoom out of range')
                        prefs['zoom'] = round(z, 2)
                    if 'profiles' in data:
                        profs = data['profiles']
                        if not isinstance(profs, list) or len(profs) > 20:
                            raise ValueError('profiles must be a list of up to 20 items')
                        cleaned = []
                        for item in profs:
                            if not isinstance(item, dict):
                                raise ValueError('profile must be an object')
                            label = str(item.get('label', '')).strip()
                            url = str(item.get('url', '')).strip()
                            kind = str(item.get('kind', 'github')).strip().lower()
                            u = urllib.parse.urlparse(url)
                            if not label or u.scheme not in ('https', 'http') or not u.netloc:
                                raise ValueError('profile requires label and http(s) url')
                            if kind not in ('github', 'website', 'x', 'discord', 'youtube', 'linkedin', 'custom'):
                                kind = 'custom'
                            cleaned.append({'label': label[:60], 'url': url[:300], 'kind': kind})
                        prefs['profiles'] = cleaned
                    engine.save()
                self.json(200, {'ok': True})
                return
            elif path == '/api/uninstall':
                if not engine.app(data['id']):
                    raise ValueError('Unknown app ID')
                engine.start('uninstall', [data['id']], clean=bool(data.get('clean', False)))
            elif path == '/api/catalog':
                def edit(cat):
                    op = data.get('op')
                    if op == 'add':
                        cat['apps'].append(data['app'])
                    elif op in ('edit', 'hide', 'remove'):
                        a = next((a for a in cat['apps'] if a['id'] == data['id']), None)
                        if a is None:
                            raise ValueError('Unknown app ID')
                        if op == 'hide':
                            if type(data.get('hidden')) is not bool:
                                raise ValueError('hidden must be boolean')
                            a['hidden'] = data['hidden']
                        elif op == 'remove':
                            cat['apps'].remove(a)
                        else:
                            a.update(data['app'])
                    else:
                        raise ValueError('Unknown catalog operation')
                engine.catalog.mutate(edit)
            else:
                self.json(404, {'error': 'Not found'})
                return
            snapshot = engine.snapshot()
            engine.emit('state', snapshot)
            self.json(200, snapshot)
        except (ValueError, KeyError, TypeError, OSError) as e:
            self.json(400, {'error': str(e)})


def install_windows_shortcut(name, target, args=''):
    if not IS_WIN:
        return
    appdata = os.environ.get('APPDATA')
    if not appdata:
        return
    programs = Path(appdata) / 'Microsoft/Windows/Start Menu/Programs'
    programs.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r'[<>:"/\\|?*]', '', name).strip() or 'App'
    lnk = programs / f'{safe_name}.lnk'
    ps = (
        f'$s=(New-Object -ComObject WScript.Shell).CreateShortcut({json.dumps(str(lnk))});'
        f'$s.TargetPath={json.dumps(str(target))};'
        f'$s.Arguments={json.dumps(str(args))};'
        f'$s.WorkingDirectory={json.dumps(str(Path(target).parent))};'
        f'$s.Save()'
    )
    subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', ps], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def ensure_home_menu_shortcut():
    try:
        if IS_WIN:
            appdata = os.environ.get('APPDATA')
            if appdata and not (Path(appdata) / 'Microsoft/Windows/Start Menu/Programs/Armin Launcher.lnk').exists():
                pyw = Path(sys.executable).with_name('pythonw.exe')
                exe = str(pyw if pyw.is_file() else sys.executable)
                install_windows_shortcut('Armin Launcher', exe, f'"{ROOT / "ArminLauncher.pyw"}"')
        elif not IS_MAC:
            entry = Path.home() / '.local/share/applications/ArminLauncher.desktop'
            installer = ROOT / 'install-desktop'
            if not entry.exists() and installer.is_file():
                subprocess.run([sys.executable, str(installer)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    except OSError:
        pass


def find_browser():
    if IS_WIN:
        for name in ('msedge', 'chrome', 'brave', 'chromium'):
            if found := shutil.which(name):
                return found
        for base in (os.environ.get('ProgramFiles'), os.environ.get('ProgramFiles(x86)'), os.environ.get('LOCALAPPDATA')):
            if not base:
                continue
            for rel in (
                'Microsoft/Edge/Application/msedge.exe',
                'Google/Chrome/Application/chrome.exe',
                'BraveSoftware/Brave-Browser/Application/brave.exe',
                'Chromium/Application/chrome.exe',
            ):
                p = Path(base) / rel
                if p.is_file():
                    return str(p)
        return None
    return next((shutil.which(x) for x in ('chromium', 'chromium-browser', 'google-chrome', 'brave') if shutil.which(x)), None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=0)
    default_catalog = ROOT / ('catalog.windows.json' if IS_WIN and (ROOT / 'catalog.windows.json').is_file() else 'catalog.json')
    parser.add_argument('--catalog', type=Path, default=default_catalog)
    parser.add_argument('--headless-server', '--no-browser', action='store_true', dest='no_browser')
    parser.add_argument('--grace', type=float, default=3.5, help='seconds after the last SSE disconnect')
    parser.add_argument('--startup-timeout', type=float, default=20, help='seconds to wait for the first SSE client')
    args = parser.parse_args()
    # Never create or replace a catalog at build time; missing runtime data is explicit.
    try:
        engine = Engine(args.catalog)
        engine.catalog.load()
        server = Server(engine, args.port, max(.1, args.grace), max(.1, args.startup_timeout))
    except (OSError, ValueError) as e:
        parser.exit(1, f'Armin Launcher: {e}\n')
    print(server.origin, flush=True)
    if not args.no_browser:
        ensure_home_menu_shortcut()
        browser = find_browser()
        if browser:
            kw = {'creationflags': subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP} if IS_WIN else {'start_new_session': True}
            argv = [browser, '--app=' + server.origin] + ([] if IS_WIN else ['--class=LaunchCraft'])
            subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
        elif IS_WIN:
            webbrowser.open(server.origin)
        else:
            server.server_close()
            parser.exit(1, 'Armin Launcher: install a Chromium browser or use --no-browser\n')
    def stop(signum, frame):
        engine.cancel.set()
        server.stopping.set()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    server.run()
    if engine.worker:
        engine.worker.join(timeout=.5 if engine.worker.daemon else None)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
