#!/usr/bin/env python3
"""LaunchCraft: an on-demand, standard-library-only local application launcher."""
import argparse
import copy
import concurrent.futures
import contextlib
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
import ssl
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


APP_KEYS = ('id', 'name', 'publisher', 'category', 'tagline', 'accent', 'website', 'source', 'install', 'hidden')


class Catalog:
    def __init__(self, path):
        self.path = Path(path).resolve()

    def load(self):
        return validate_catalog(json.loads(self.path.read_text()))

    @contextlib.contextmanager
    def locked(self):
        # Shared by the HTTP editor, background audits and launchcraft-ctl.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix(self.path.suffix + '.lock').open('a') as lock:
            if fcntl is not None:
                fcntl.flock(lock, fcntl.LOCK_EX)
            elif msvcrt is not None:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                if msvcrt is not None and fcntl is None:
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)

    def mutate(self, action):
        with self.locked():
            before = self.path.read_bytes()
            data = validate_catalog(json.loads(before))
            action(data)
            validate_catalog(data)
            if self.path.read_bytes() != before:
                raise ValueError('Catalog changed externally; retry your edit')
            atomic_json(self.path, data)
            return data


class Cancelled(Exception):
    pass


class RefreshRun:
    WORKERS = 10
    TIMEOUT = 8
    REQUEST_TIMEOUT = 4

    def __init__(self, cancel, http):
        self.cancel = cancel
        self.done = threading.Event()
        self.deadline = time.monotonic() + self.TIMEOUT
        self.http = http.copy()
        self.http_updates = {}
        self.ssl_context = None

    def remaining(self):
        if self.cancel.is_set() or self.done.is_set():
            raise Cancelled()
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Refresh deadline reached')
        return remaining


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
        for key in ('installed', 'releases', 'release_sources', 'http', 'prefs', 'secrets'):
            self.state.setdefault(key, {})
        self.api_base, self.web_base = api_base.rstrip('/'), web_base.rstrip('/')
        self.gh_token = self._detect_gh_token() if self.api_base == 'https://api.github.com' else ''
        self.listeners = set()
        self.jobs = {}
        self.busy = False
        self.refreshing = False
        self.ai_running = False
        self.catalog_key = hashlib.sha256(str(self.catalog.path).encode()).hexdigest()[:16]
        self.ai_result_path = self.data / f'ai-result-{self.catalog_key}.json'
        try:
            ai_result = json.loads(self.ai_result_path.read_text())
        except (OSError, ValueError):
            ai_result = {}
        self.ai_report = ai_result.get('report', '')
        self.ai_outcome = ai_result.get('outcome', '')
        self.ai_phase = ''
        self.ai_cancel = threading.Event()
        self.ai_proc = None
        self.chat_history = []
        self.cancel = threading.Event()
        self.pkg_lock = threading.Lock()
        self.active_workers = 0
        self.worker = None
        self._refresh_context = threading.local()
        self._refresh_slots = threading.BoundedSemaphore(RefreshRun.WORKERS)
        self.notice = ''
        self.last_error = ''
        self.warnings = []
        self.term_cwd = ai_result.get('cwd') or str(self.catalog.path.parent)
        self.pending_fixes = ai_result.get('fixes', [])

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
            if run := getattr(self._refresh_context, 'run', None):
                run.remaining()
                kw = {} if IS_WIN else {'start_new_session': True}
                process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **kw)
                deadline = time.monotonic() + timeout
                completed = False
                try:
                    while True:
                        wait = min(.1, deadline - time.monotonic(), run.remaining())
                        if wait <= 0:
                            raise subprocess.TimeoutExpired(argv, timeout)
                        try:
                            stdout, stderr = process.communicate(timeout=wait)
                            completed = True
                            return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
                        except subprocess.TimeoutExpired:
                            continue
                finally:
                    if not completed:
                        try:
                            if IS_WIN:
                                process.kill()
                            else:
                                os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    process.wait()
                    process.stdout.close()
                    process.stderr.close()
            return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as e:
            return subprocess.CompletedProcess(argv, 127, '', str(e))

    def installed(self, app, pacman_versions=None):
        ins = app['install']
        record = self.state['installed'].get(app['id'], {})
        if ins['type'] in ('pacman_pkg', 'pacman', 'aur'):
            if IS_WIN:
                return None
            if pacman_versions is not None:
                return pacman_versions.get(ins['package'])
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

    def cpu_info(self):
        cores = os.cpu_count() or 4
        model = f'{cores}-core CPU'
        cpuinfo = Path('/proc/cpuinfo')
        if cpuinfo.is_file():
            try:
                for line in cpuinfo.read_text(errors='ignore').splitlines():
                    if line.lower().startswith('model name'):
                        model = line.split(':', 1)[1].strip()
                        break
            except OSError:
                pass
        return {'cores': cores, 'model': model}

    def load_details(self):
        det_path = ROOT / 'ui' / 'details.json'
        if det_path.is_file():
            try:
                return json.loads(det_path.read_text())
            except Exception:
                pass
        return {}

    def app_build_info(self, app, detail=None, cores=None):
        bi = (detail or {}).get('build_info')
        src = app.get('source') or {}
        if isinstance(bi, dict) and 'from_source' in bi:
            from_source = bool(bi['from_source'])
        else:
            from_source = src.get('type') == 'aur' and not str(src.get('package', '')).endswith('-bin')
        if not from_source:
            return None
        cores = cores or (os.cpu_count() or 4)
        est_gb = float((bi or {}).get('estimated_gb') or 2.5)
        base_mins = float((bi or {}).get('base_minutes_8core') or 10.0)
        est_mins = max(1, round(base_mins * (8.0 / max(1, cores))))
        return {
            'from_source': True,
            'estimated_gb': round(est_gb, 1),
            'base_minutes_8core': round(base_mins, 1),
            'estimated_minutes': est_mins,
        }

    def snapshot(self):
        # Disk reads ensure another agent's catalog changes appear without a restart.
        apps = copy.deepcopy(self.catalog.load()['apps'])
        details = self.load_details()
        cpu = self.cpu_info()
        pacman_versions = None
        if not IS_WIN and any(a['install']['type'] in ('pacman_pkg', 'pacman', 'aur') for a in apps):
            output = self.command(['pacman', '-Q']).stdout
            pacman_versions = dict(line.split(maxsplit=1) for line in output.splitlines() if len(line.split()) == 2)
        for app in apps:
            if pacman_versions is not None and app['install']['type'] in ('pacman_pkg', 'pacman', 'aur'):
                app['installed'] = self.installed(app, pacman_versions)
            else:
                app['installed'] = self.installed(app)
        with self.lock:
            for app in apps:
                release = self.cached_release(app)
                app['latest'] = release.get('tag')
                app['release'] = release
                app['update'] = bool(app['installed'] and app['latest'] and self.newer(app['latest'], app['installed']))
                app['job'] = self.jobs.get(app['id'])
                app['verification'] = self.state['installed'].get(app['id'], {}).get('verification')
                app['icon'] = self.icon_url(app['id'])
                app['compatible'] = self.is_compatible(app)
                app['data_paths'] = [str(p) for p in self.user_data_paths(app)]
                app['build_info'] = self.app_build_info(app, details.get(app['id']), cpu['cores'])
            return dict(apps=apps, busy=self.busy, refreshing=self.refreshing, **self.ai_state(), ai_configured=bool(self.get_ai_key('openai')), ai_keys={p: bool(self.get_ai_key(p)) for p in ('openai', 'anthropic', 'gemini', 'openrouter', 'custom', 'subscription')}, ai_cli_tools={c: bool(shutil.which(c)) for c in ('opencode', 'codex', 'claude', 'gemini')}, ai_key_profiles={p: self.public_ai_keys(p) for p in ('openai', 'anthropic', 'gemini', 'openrouter', 'custom')}, ai_active_keys={p: self.active_ai_key_id(p) for p in ('openai', 'anthropic', 'gemini', 'openrouter', 'custom')}, ai_models=copy.deepcopy(self.state.get('ai_models', {})), notice=self.notice, last_error=self.last_error, warnings=self.warnings, platform=self.platform, cpu=cpu, prefs=copy.deepcopy(self.state.get('prefs', {})))

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

    @staticmethod
    def _mask_key(key):
        s = (key or '').strip()
        if len(s) >= 10:
            return f'{s[:4]}…{s[-4:]}'
        return '••••' if s else ''

    def _ensure_key_profiles(self, provider):
        secrets_box = self.state.setdefault('secrets', {})
        profiles_box = secrets_box.setdefault('ai_key_profiles', {})
        entries = profiles_box.setdefault(provider, [])
        if not isinstance(entries, list):
            entries = []
            profiles_box[provider] = entries
        legacy = ''
        keys = secrets_box.get('ai_keys', {})
        if isinstance(keys, dict) and isinstance(keys.get(provider), str):
            legacy = keys[provider].strip()
        if not legacy and provider == 'openai':
            legacy = str(secrets_box.get('openai_api_key', '')).strip()
        if legacy and not any(e.get('key') == legacy for e in entries if isinstance(e, dict)):
            kid = hashlib.sha256(legacy.encode()).hexdigest()[:8]
            entries.insert(0, {'id': kid, 'label': f'Key 1 ({self._mask_key(legacy)})', 'key': legacy})
        active_box = secrets_box.setdefault('ai_active_key', {})
        if entries and active_box.get(provider) not in {e.get('id') for e in entries if isinstance(e, dict)}:
            active_box[provider] = entries[0]['id']
        return entries

    def public_ai_keys(self, provider):
        entries = self._ensure_key_profiles(provider)
        return [{'id': e['id'], 'label': e.get('label') or self._mask_key(e.get('key', '')), 'masked': self._mask_key(e.get('key', ''))} for e in entries if isinstance(e, dict) and e.get('key')]

    def active_ai_key_id(self, provider):
        self._ensure_key_profiles(provider)
        return self.state.get('secrets', {}).get('ai_active_key', {}).get(provider, '')

    def save_ai_key(self, provider, key, label=''):
        k = (key or '').strip()
        if not k:
            return ''
        with self.lock:
            entries = self._ensure_key_profiles(provider)
            existing = next((e for e in entries if e.get('key') == k), None)
            if existing:
                if label.strip():
                    existing['label'] = f'{label.strip()[:40]} ({self._mask_key(k)})'
                kid = existing['id']
            else:
                kid = hashlib.sha256(f'{provider}:{k}'.encode()).hexdigest()[:8]
                lbl = f'{label.strip()[:40]} ({self._mask_key(k)})' if label.strip() else f'Key {len(entries) + 1} ({self._mask_key(k)})'
                entries.append({'id': kid, 'label': lbl, 'key': k})
            self.state['secrets'].setdefault('ai_active_key', {})[provider] = kid
            self.state['secrets'].setdefault('ai_keys', {})[provider] = k
            self.save()
            return kid

    def select_ai_key(self, provider, key_id):
        with self.lock:
            entries = self._ensure_key_profiles(provider)
            found = next((e for e in entries if e.get('id') == key_id), None)
            if not found:
                raise ValueError('Saved API key not found')
            self.state['secrets'].setdefault('ai_active_key', {})[provider] = found['id']
            self.state['secrets'].setdefault('ai_keys', {})[provider] = found['key']
            self.save()

    def delete_ai_key(self, provider, key_id):
        with self.lock:
            entries = self._ensure_key_profiles(provider)
            kept = [e for e in entries if e.get('id') != key_id]
            self.state['secrets']['ai_key_profiles'][provider] = kept
            active_box = self.state['secrets'].setdefault('ai_active_key', {})
            keys_box = self.state['secrets'].setdefault('ai_keys', {})
            if kept:
                if active_box.get(provider) == key_id or active_box.get(provider) not in {e['id'] for e in kept}:
                    active_box[provider] = kept[0]['id']
                active_entry = next(e for e in kept if e['id'] == active_box[provider])
                keys_box[provider] = active_entry['key']
            else:
                active_box.pop(provider, None)
                keys_box.pop(provider, None)
                if provider == 'openai':
                    self.state['secrets'].pop('openai_api_key', None)
            self.save()

    def get_ai_key(self, provider='openai'):
        entries = self._ensure_key_profiles(provider)
        active_id = self.state.get('secrets', {}).get('ai_active_key', {}).get(provider)
        if active_id:
            found = next((e.get('key', '').strip() for e in entries if e.get('id') == active_id), '')
            if found:
                return found
        env_map = {'openai': 'OPENAI_API_KEY', 'anthropic': 'ANTHROPIC_API_KEY', 'gemini': 'GEMINI_API_KEY', 'openrouter': 'OPENROUTER_API_KEY'}
        env_var = env_map.get(provider, '')
        if env_var and os.environ.get(env_var, '').strip():
            return os.environ[env_var].strip()
        secrets_box = self.state.get('secrets', {})
        keys = secrets_box.get('ai_keys', {})
        if isinstance(keys, dict) and keys.get(provider, '').strip():
            return keys[provider].strip()
        if provider == 'openai':
            return secrets_box.get('openai_api_key', '').strip()
        return ''

    def ai_state(self):
        with self.lock:
            return dict(ai_running=self.ai_running, ai_phase=self.ai_phase,
                        ai_outcome=self.ai_outcome, ai_report=self.ai_report,
                        pending_fixes=copy.deepcopy(self.pending_fixes),
                        term_cwd=self.term_cwd, revision=time.monotonic())

    def _begin_ai(self, phase):
        with self.lock:
            if self.ai_running:
                raise ValueError('Another AI task is running')
            self.ai_running = True
            self.ai_phase = phase
            self.ai_outcome = ''
            self.ai_cancel.clear()

    def _publish_ai(self, phase=None):
        with self.lock:
            if phase and not self.ai_cancel.is_set():
                self.ai_phase = phase
            self.emit('ai', self.ai_state())

    def _finish_ai(self, outcome):
        with self.lock:
            self.ai_running = False
            self.ai_phase = ''
            self.ai_outcome = outcome
            try:
                atomic_json(self.ai_result_path, {'report': self.ai_report[-65536:],
                            'outcome': outcome, 'fixes': self.pending_fixes, 'cwd': self.term_cwd})
            except OSError as e:
                self.ai_report += f'\nCould not save AI report: {e}'
            self._publish_ai()

    def cancel_ai(self):
        with self.lock:
            if self.ai_running:
                self.ai_phase = 'Stopping'
                self.ai_cancel.set()
                if self.ai_proc is not None:
                    self._stop_ai_process(self.ai_proc)
                self._publish_ai()

    @staticmethod
    def _stop_ai_process(proc):
        try:
            if IS_WIN:
                try:
                    subprocess.run(['taskkill', '/T', '/F', '/PID', str(proc.pid)], timeout=3,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except (OSError, subprocess.TimeoutExpired):
                    pass
                proc.kill()
            else:
                os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def _run_cancellable_cli(self, argv, stdin_text=None, timeout=900, cwd=None):
        # communicate drains both pipes while writing the prompt. Waiting for exit
        # first deadlocks as soon as the CLI fills either pipe with diagnostics.
        proc = subprocess.Popen(
            argv, cwd=cwd or str(ROOT), start_new_session=not IS_WIN,
            stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors='replace',
        )
        with self.lock:
            self.ai_proc = proc
        deadline = time.monotonic() + timeout
        try:
            while True:
                if self.ai_cancel.is_set():
                    raise Cancelled('Cancelled by user')
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f'{argv[0]} did not finish within {timeout:g}s')
                try:
                    out, err = proc.communicate(input=stdin_text, timeout=min(.25, remaining))
                except subprocess.TimeoutExpired:
                    stdin_text = None
                    continue
                if self.ai_cancel.is_set():
                    raise Cancelled('Cancelled by user')
                return proc.returncode, out, err
        finally:
            if proc.returncode is None:
                self._stop_ai_process(proc)
                proc.communicate()
            with self.lock:
                if self.ai_proc is proc:
                    self.ai_proc = None

    def call_ai_provider(self, provider, key, model, base_url, sys_prompt, user_payload, thinking='auto'):
        t = (thinking or 'auto').strip().lower()
        if t not in ('auto', 'low', 'medium', 'high'):
            t = 'auto'

        def send_once(use_thinking):
            if provider == 'anthropic':
                if not key:
                    raise ValueError('Set an Anthropic API key first')
                payload = {
                    'model': model or 'claude-3-5-haiku-latest',
                    'max_tokens': 4096,
                    'system': sys_prompt,
                    'messages': [{'role': 'user', 'content': user_payload}],
                }
                if use_thinking != 'auto':
                    budget = {'low': 1024, 'medium': 8192, 'high': 16384}[use_thinking]
                    payload['thinking'] = {'type': 'enabled', 'budget_tokens': budget}
                    payload['max_tokens'] = budget + 4096
                req = urllib.request.Request('https://api.anthropic.com/v1/messages', data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json', 'x-api-key': key, 'anthropic-version': '2023-06-01'}, method='POST')
                with urllib.request.urlopen(req, timeout=600) as resp:
                    blocks = json.loads(resp.read()).get('content', [])
                    return ''.join(b['text'] for b in blocks if b.get('type') == 'text' and 'text' in b)
            elif provider == 'gemini':
                if not key:
                    raise ValueError('Set a Gemini API key first')
                m = urllib.parse.quote(model or 'gemini-2.5-flash', safe='')
                gen_cfg = {'responseMimeType': 'application/json'}
                if use_thinking != 'auto':
                    gen_cfg['thinkingConfig'] = {'thinkingBudget': {'low': 1024, 'medium': 8192, 'high': 24576}[use_thinking]}
                payload = {
                    'systemInstruction': {'parts': [{'text': sys_prompt}]},
                    'contents': [{'role': 'user', 'parts': [{'text': user_payload}]}],
                    'generationConfig': gen_cfg,
                }
                req = urllib.request.Request(f'https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={urllib.parse.quote(key, safe="")}', data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'}, method='POST')
                with urllib.request.urlopen(req, timeout=600) as resp:
                    return json.loads(resp.read())['candidates'][0]['content']['parts'][0]['text']
            elif provider == 'subscription':
                cli = (base_url or '').strip().lower() or next((c for c in ('opencode', 'codex', 'claude', 'gemini') if shutil.which(c)), 'opencode')
                if cli not in ('opencode', 'codex', 'claude', 'gemini'):
                    raise ValueError(f'Unsupported subscription CLI: {cli}')
                if not shutil.which(cli):
                    raise ValueError(f'{cli} CLI is not installed on this machine')
                # The launcher owns catalog writes. Keep one-shot inference
                # outside the project so CLI agents do not run repository tasks.
                with tempfile.TemporaryDirectory(prefix='armin-ai-') as workdir:
                    stdin_text = f'{sys_prompt}\n\n{user_payload}'
                    if cli == 'opencode':
                        attachment = Path(workdir) / 'facts.json'
                        attachment.write_text(user_payload, encoding='utf-8')
                        argv = ['opencode', 'run', *(['-m', model] if model else []), '-f', str(attachment), '--', sys_prompt + '\nReturn ONLY valid JSON.']
                        stdin_text = None
                    elif cli == 'codex':
                        effort = ['-c', f'model_reasoning_effort="{use_thinking}"'] if use_thinking != 'auto' else []
                        argv = ['codex', 'exec', '--skip-git-repo-check', '--sandbox', 'read-only',
                                *(['-m', model] if model else []), *effort, '-']
                    elif cli == 'claude':
                        argv = ['claude', '-p', *(['--model', model] if model else [])]
                    else:
                        argv = ['gemini', *(['-m', model] if model else []), '-p', sys_prompt]
                        stdin_text = user_payload
                    rc, out, err = self._run_cancellable_cli(argv, stdin_text=stdin_text, cwd=workdir)
                if rc != 0:
                    raise ValueError((err or out or f'{cli} exited {rc}').strip()[-600:])
                return out
            else:
                endpoint = {'openai': 'https://api.openai.com/v1', 'openrouter': 'https://openrouter.ai/api/v1'}.get(provider, (base_url or '').strip().rstrip('/'))
                if not endpoint:
                    raise ValueError('Enter a Base URL for custom OpenAI-compatible provider')
                if provider != 'custom' and not key:
                    raise ValueError(f'Set an API key for {provider} first')
                headers = {'Content-Type': 'application/json'}
                if key:
                    headers['Authorization'] = f'Bearer {key}'
                payload = {
                    'model': model or 'gpt-4o-mini',
                    'response_format': {'type': 'json_object'},
                    'messages': [
                        {'role': 'system', 'content': sys_prompt},
                        {'role': 'user', 'content': user_payload},
                    ],
                }
                if use_thinking != 'auto' and provider in ('openai', 'openrouter'):
                    payload['reasoning_effort'] = use_thinking
                req = urllib.request.Request(f'{endpoint}/chat/completions', data=json.dumps(payload).encode(), headers=headers, method='POST')
                with urllib.request.urlopen(req, timeout=600) as resp:
                    return json.loads(resp.read())['choices'][0]['message']['content']

        def request_text():
            try:
                return send_once(t)
            except urllib.error.HTTPError as e:
                if e.code == 400 and t != 'auto':
                    return send_once('auto')
                else:
                    detail = ''
                    try:
                        raw_err = e.read().decode('utf-8', errors='ignore')
                        err_json = json.loads(raw_err)
                        detail = (err_json.get('error', {}).get('message') if isinstance(err_json.get('error'), dict) else err_json.get('error')) or raw_err
                    except Exception:
                        pass
                    raise ValueError(f'{provider} API {e.code}: {str(detail or e.reason).strip()[:300]}') from e

        if provider == 'subscription':
            text = request_text()
        else:
            # urllib may block waiting for response headers. A stopped job must
            # never process a late result or hold up the next user request.
            response = queue.Queue(maxsize=1)
            def request_worker():
                try:
                    response.put((request_text(), None))
                except Exception as e:
                    response.put((None, e))
            threading.Thread(target=request_worker, name='armin-ai-http', daemon=True).start()
            while not self.ai_cancel.is_set():
                try:
                    text, error = response.get(timeout=.25)
                    if error:
                        raise error
                    break
                except queue.Empty:
                    continue
            else:
                raise Cancelled('Cancelled by user')
        if self.ai_cancel.is_set():
            raise Cancelled('Cancelled by user')
        cleaned = re.sub(r'^```(?:json)?\s*|\s*```$', '', text.strip(), flags=re.I)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            s, e = cleaned.find('{'), cleaned.rfind('}')
            if s != -1 and e > s:
                return json.loads(cleaned[s:e + 1])
            raise

    def fetch_ai_models(self, provider='openai', key='', base_url=''):
        key = (key or '').strip() or self.get_ai_key(provider)
        models = []
        if provider == 'subscription':
            cli = (base_url or '').strip().lower() or next((c for c in ('opencode', 'codex', 'claude', 'gemini') if shutil.which(c)), 'opencode')
            if cli == 'opencode' and shutil.which('opencode'):
                p = subprocess.run(['opencode', 'models'], capture_output=True, text=True, timeout=10)
                if p.returncode == 0:
                    models = [ln.strip() for ln in p.stdout.splitlines() if ln.strip() and '/' in ln]
            elif cli == 'codex':
                codex_home = Path(os.environ.get('CODEX_HOME') or (self.home / '.codex'))
                cache_file = codex_home / 'models_cache.json'
                if cache_file.is_file():
                    try:
                        raw_models = json.loads(cache_file.read_text(encoding='utf-8')).get('models') or []
                        visible = [m for m in raw_models if isinstance(m, dict) and m.get('visibility', 'list') == 'list']
                        picked = visible or [m for m in raw_models if isinstance(m, dict)]
                        models = [m.get('slug') or m.get('id') for m in picked if (m.get('slug') or m.get('id'))]
                    except Exception:
                        pass
                if not models:
                    models = ['gpt-6.2-sol', 'gpt-6.2-astra', 'gpt-6.1-terra', 'gpt-5.4', 'o4-mini']
            elif cli == 'claude':
                models = ['sonnet', 'opus', 'haiku']
            elif cli == 'gemini':
                models = ['gemini-2.5-pro', 'gemini-2.5-flash', 'gemini-3-flash-preview']
            if models:
                with self.lock:
                    box = self.state.setdefault('ai_models', {})
                    box['subscription'] = models
                    box[f'subscription:{cli}'] = models
                    self.save()
            return models
        elif provider == 'anthropic':
            if not key:
                return []
            req = urllib.request.Request('https://api.anthropic.com/v1/models?limit=50', headers={'x-api-key': key, 'anthropic-version': '2023-06-01'})
            with urllib.request.urlopen(req, timeout=15) as r:
                models = [m['id'] for m in json.loads(r.read()).get('data', []) if m.get('id')]
        elif provider == 'gemini':
            if not key:
                return []
            req = urllib.request.Request(f'https://generativelanguage.googleapis.com/v1beta/models?key={urllib.parse.quote(key, safe="")}&pageSize=50')
            with urllib.request.urlopen(req, timeout=15) as r:
                for m in json.loads(r.read()).get('models', []):
                    if 'generateContent' in m.get('supportedGenerationMethods', []):
                        models.append(m['name'].removeprefix('models/'))
        else:
            endpoint = {'openai': 'https://api.openai.com/v1', 'openrouter': 'https://openrouter.ai/api/v1'}.get(provider, (base_url or '').strip().rstrip('/'))
            if not endpoint or (provider != 'custom' and not key):
                return []
            headers = {'Authorization': f'Bearer {key}'} if key else {}
            req = urllib.request.Request(f'{endpoint}/models', headers=headers)
            with urllib.request.urlopen(req, timeout=15) as r:
                raw = [m['id'] for m in json.loads(r.read()).get('data', []) if m.get('id')]
            if provider == 'openai':
                models = sorted([m for m in raw if m.startswith(('gpt-', 'o1', 'o3', 'o4', 'chatgpt-'))], reverse=True)[:40]
            else:
                models = raw[:50]
        if models:
            with self.lock:
                self.state.setdefault('ai_models', {})[provider] = models
                self.save()
        return models

    def check_launchable(self, app):
        if not self.installed(app):
            return {'installed': False, 'ok': None, 'reason': 'not installed'}
        try:
            argv = self.launch_argv(app)
        except Exception as e:
            return {'installed': True, 'ok': False, 'reason': f'invalid launch command: {e}'}
        cmd0 = argv[0]
        exe = Path(cmd0) if ('/' in cmd0 or '\\' in cmd0) else (Path(shutil.which(cmd0)) if shutil.which(cmd0) else None)
        if not exe or not exe.is_file():
            return {'installed': True, 'ok': False, 'reason': f'executable missing: {cmd0}', 'argv': argv}
        if not IS_WIN and not os.access(exe, os.X_OK):
            return {'installed': True, 'ok': False, 'reason': f'missing executable permission (+x): {exe}', 'exe': str(exe), 'fixable_chmod': True}
        if not IS_WIN:
            x11_dir = Path('/tmp/.X11-unix')
            if x11_dir.is_dir() and any(x11_dir.glob('X[0-9]*_')) and not (x11_dir / 'X0').exists():
                return {'installed': True, 'ok': False, 'reason': 'X11 socket /tmp/.X11-unix/X0 missing (X0_ exists)', 'exe': str(exe), 'fixable_x11': True}
            if app['install'].get('type') != 'appimage' and shutil.which('ldd'):
                try:
                    with exe.open('rb') as binary:
                        head = binary.read(4)
                    if head == b'\x7fELF':
                        p = subprocess.run(['ldd', str(exe)], capture_output=True, text=True, timeout=2)
                        missing = [ln.strip() for ln in p.stdout.splitlines() if 'not found' in ln]
                        if missing:
                            return {'installed': True, 'ok': False, 'reason': 'missing shared libraries: ' + '; '.join(missing[:3]), 'exe': str(exe)}
                except Exception:
                    pass
        return {'installed': True, 'ok': True, 'exe': str(exe)}

    def _append_term(self, text):
        with self.lock:
            cur = self.ai_report or ''
            self.ai_report = (cur + ('\n' if cur and not cur.endswith('\n') else '') + text).strip()
        self._publish_ai()

    def _run_shell_cmd(self, cmd, needs_admin=False):
        self._begin_ai('Running command')
        def work():
            outcome = 'complete'
            try:
                run_cmd = cmd.strip()
                if run_cmd.startswith('sudo '):
                    run_cmd = run_cmd[5:].strip()
                    needs_priv = True
                else:
                    needs_priv = bool(needs_admin)
                self._append_term(f'$ {("pkexec " if needs_priv else "")}{run_cmd}')
                if needs_priv and not IS_WIN:
                    priv = self.privilege_cmd()
                    argv = [*priv, 'sh', '-c', run_cmd]
                else:
                    argv = ['cmd', '/c', run_cmd] if IS_WIN else ['sh', '-c', run_cmd]
                proc = subprocess.Popen(
                    argv, cwd=self.term_cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL, text=True, errors='replace', bufsize=1, start_new_session=not IS_WIN,
                )
                with self.lock:
                    self.ai_proc = proc
                    if self.ai_cancel.is_set():
                        self._stop_ai_process(proc)
                buf = []
                for line in proc.stdout:
                    if self.ai_cancel.is_set():
                        self._stop_ai_process(proc)
                        break
                    buf.append(line.rstrip('\n'))
                    if len(buf) >= 5:
                        self._append_term('\n'.join(buf))
                        buf.clear()
                if buf:
                    self._append_term('\n'.join(buf))
                proc.stdout.close()
                rc = proc.wait()
                if self.ai_cancel.is_set():
                    outcome = 'cancelled'
                    self._append_term('Cancelled by user.')
                elif rc != 0:
                    outcome = 'error'
                    self._append_term(f'[exit {rc}]')
            except Exception as e:
                outcome = 'error'
                self._append_term(f'Error: {e}')
            finally:
                with self.lock:
                    self.ai_proc = None
                self._finish_ai(outcome)

        threading.Thread(target=work, name='armin-term-cmd', daemon=True).start()

    def run_pending_fix(self, fix_id):
        with self.lock:
            if self.ai_running:
                raise ValueError('Another AI task is running')
            fix = next((f for f in self.pending_fixes if f['id'] == fix_id), None)
            if not fix:
                raise ValueError('Fix command not found')
            self.pending_fixes = [f for f in self.pending_fixes if f['id'] != fix_id]
            self._run_shell_cmd(fix['cmd'], needs_admin=bool(fix.get('needs_admin')))

    def terminal_exec(self, raw_input, provider='openai', model='', base_url='', thinking='auto'):
        text = (raw_input or '').strip()
        if not text:
            return
        if text == 'clear':
            with self.lock:
                self.ai_report = ''
                self.pending_fixes = []
                self.chat_history = []
                self.ai_outcome = ''
                self.ai_result_path.unlink(missing_ok=True)
            self._publish_ai()
            return
        if text == 'help':
            self._append_term(
                '$ help\n'
                'Built-ins: clear, pwd, cd <dir>, help\n'
                'Run shell commands with ! or $ (e.g. !ls -la, !sudo pacman -Syu, !systemctl --user status)\n'
                'Or type normally to chat with the AI and ask it to inspect or fix apps.'
            )
            return
        if text == 'pwd':
            self._append_term(f'$ pwd\n{self.term_cwd}')
            return
        if text == 'cd' or text.startswith('cd '):
            arg = text[2:].strip() or str(self.home)
            target = (Path(self.term_cwd) / os.path.expanduser(arg)).resolve()
            if not target.is_dir():
                self._append_term(f'$ {text}\ncd: no such directory: {arg}')
            else:
                self.term_cwd = str(target)
                self._append_term(f'$ {text}\n{self.term_cwd}')
            return

        shell_prefixes = ('!', '$', 'ls', 'cat', 'which', 'echo', 'env', 'uname', 'ps', 'ss', 'df', 'free', 'ldd', 'chmod', 'ln', 'mkdir', 'rm', 'mv', 'cp', 'git', 'pacman', 'yay', 'paru', 'systemctl', 'journalctl', 'nvidia-smi', 'pkexec', 'sudo')
        is_shell = text.startswith(('!', '$')) or text.split()[0] in shell_prefixes
        if is_shell:
            with self.lock:
                if self.ai_running:
                    raise ValueError('Another AI task is running')
            cmd = text.lstrip('!$ ').strip()
            self._run_shell_cmd(cmd, needs_admin=cmd.startswith('sudo '))
            return

        key = self.get_ai_key(provider)
        if provider not in ('custom', 'subscription') and not key:
            raise ValueError(f'Set an API key for {provider} first')
        self._begin_ai('Checking installed apps')
        self._append_term(f'You: {text}')

        def run_readonly_inspect(cmd_str):
            s = (cmd_str or '').strip()
            if not s or any(ch in s for ch in ('|', '>', '<', ';', '&', '$', '`', '\n')):
                return f'[blocked non-readonly command: {s}]'
            try:
                parts = shlex.split(s)
            except ValueError as e:
                return f'[invalid command: {e}]'
            ro_bins = {'ls', 'cat', 'head', 'tail', 'which', 'ldd', 'file', 'uname', 'ps', 'ss', 'df', 'free', 'env', 'nvidia-smi', 'pacman', 'systemctl', 'journalctl'}
            if not parts or parts[0] not in ro_bins:
                return f'[not in read-only allowlist: {parts[0] if parts else ""}]'
            if parts[0] == 'pacman' and not any(f in parts[1:] for f in ('-Q', '-Qi', '-Ql', '-Si', '-Qu')):
                return '[pacman inspect only allows query flags]'
            if parts[0] == 'systemctl' and 'status' not in parts[1:] and 'is-active' not in parts[1:]:
                return '[systemctl inspect only allows status/is-active]'
            try:
                p = subprocess.run(parts, cwd=self.term_cwd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=6)
                return ((p.stdout or '') + ('\n' + p.stderr if p.stderr else '')).strip()[-1800:] or '(no output)'
            except Exception as e:
                return f'[inspect error: {e}]'

        def chat_work():
            outcome = 'complete'
            try:
                linux_cat = self.catalog.load()
                launch_status = []
                for app in linux_cat['apps']:
                    if self.ai_cancel.is_set():
                        raise Cancelled('Cancelled by user')
                    info = self.check_launchable(app)
                    if info['installed']:
                        launch_status.append({'id': app['id'], 'name': app['name'], **info})
                sys_prompt = (
                    'You are the interactive AI assistant inside Armin Launcher\'s mini terminal. '
                    'Help the user diagnose app launch failures, inspect logs, and fix issues. '
                    'Format reply for reading with short Markdown paragraphs, lists, or fenced code blocks where useful. '
                    'Return ONLY valid JSON: {"reply": str, "inspect_commands": [str], "fix_commands": [{"title": str, "cmd": str, "needs_admin": bool}]}. '
                    'Use inspect_commands ONLY if you need read-only diagnostic output first (ls, cat, head, tail, which, ldd, file, ps, ss, df, free, nvidia-smi, systemctl status, journalctl). '
                    'Set needs_admin=true in fix_commands when root/sudo/pacman permissions are needed (the UI will prompt the user for admin via pkexec).'
                )
                inspect_results = []
                res = {}
                for _round in range(3):
                    if self.ai_cancel.is_set():
                        raise Cancelled('Cancelled by user')
                    payload = json.dumps({
                        'message': text,
                        'history': self.chat_history[-10:],
                        'cwd': self.term_cwd,
                        'recent_log': (self.ai_report or '')[-3000:],
                        'installed_launch_status': launch_status,
                        'inspect_results': inspect_results,
                    }, separators=(',', ':'))
                    self._publish_ai(f'Waiting for {base_url if provider == "subscription" and base_url else provider}')
                    res = self.call_ai_provider(provider, key, model, base_url, sys_prompt, payload, thinking=thinking)
                    if self.ai_cancel.is_set():
                        raise Cancelled('Cancelled by user')
                    cmds = [str(c).strip() for c in (res.get('inspect_commands') or []) if str(c).strip()][:3]
                    if not cmds or _round == 2:
                        break
                    for c in cmds:
                        if self.ai_cancel.is_set():
                            raise Cancelled('Cancelled by user')
                        out = run_readonly_inspect(c)
                        inspect_results.append({'cmd': c, 'output': out})
                        self._append_term(f'$ {c}\n{out[:500]}')
                reply = str(res.get('reply') or res.get('summary') or 'Done.')
                fixes = []
                for idx_f, f in enumerate(res.get('fix_commands') or []):
                    if isinstance(f, dict) and str(f.get('cmd', '')).strip():
                        fixes.append({
                            'id': f'fix-{int(time.time()*1000)}-{idx_f}',
                            'title': str(f.get('title') or f['cmd'])[:80],
                            'cmd': str(f['cmd']).strip(),
                            'needs_admin': bool(f.get('needs_admin', False)),
                        })
                with self.lock:
                    self.pending_fixes = fixes
                    self.chat_history = (self.chat_history + [{'role': 'user', 'content': text}, {'role': 'assistant', 'content': reply}])[-12:]
                self._append_term(f'AI: {reply}')
            except Cancelled:
                outcome = 'cancelled'
                self._append_term('Cancelled by user.')
            except Exception as e:
                outcome = 'error'
                self._append_term(f'Error: {e}')
            finally:
                self._finish_ai(outcome)

        threading.Thread(target=chat_work, name='armin-ai-chat', daemon=True).start()

    @staticmethod
    def _extract_accent_from_bytes(data, fallback='#2d81ff'):
        if b'<svg' in data[:500].lower():
            for m in re.finditer(r'#[0-9a-fA-F]{6}\b', data.decode('utf-8', errors='ignore')):
                c = m.group(0).lower()
                if c not in ('#000000', '#ffffff', '#111111', '#222222', '#eeeeee', '#f5f5f5'):
                    return c
            return fallback
        try:
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(data)).convert('RGBA').resize((48, 48))
            best, best_score = fallback, -1.0
            for r, g, b, a in img.getdata():
                if a < 128:
                    continue
                mx, mn = max(r, g, b), min(r, g, b)
                sat = (mx - mn) / max(1, mx)
                lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
                if lum < 0.12 or lum > 0.92:
                    continue
                score = sat * 2.0 + (1.0 - abs(lum - 0.55))
                if score > best_score:
                    best_score = score
                    best = f'#{r:02x}{g:02x}{b:02x}'
            return best
        except Exception:
            return fallback

    @staticmethod
    def _shift_hex(hex_color, delta=28):
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', hex_color or ''):
            return '#7aa2f7'
        r, g, b = int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)
        r = max(0, min(255, r + delta))
        g = max(0, min(255, g - delta // 2))
        b = max(0, min(255, b + delta))
        return f'#{r:02x}{g:02x}{b:02x}'

    def enrich_app_assets(self, app, details, log=None):
        """Automatically fetch missing icon, screenshot, description, features, and colors for an app."""
        aid = app['id']
        changed = False
        has_icon = any((ROOT / 'ui' / 'icons' / f'{aid}.{e}').is_file() for e in ('png', 'svg'))
        entry = details.get(aid) if isinstance(details.get(aid), dict) else {}
        has_shot = any((ROOT / 'ui' / s.get('url', '').lstrip('/')).is_file() for s in entry.get('shots', []) if isinstance(s, dict))
        needs_details = not entry.get('about') or not entry.get('features') or not entry.get('accent2')
        if has_icon and has_shot:
            if not needs_details:
                return False
            # A missing secondary shade can be derived entirely from the
            # catalog color when the app already has its text and imagery.
            if entry.get('about') and entry.get('features') and app.get('accent', '').lower() not in ('', '#2d81ff', '#000000', '#ffffff'):
                entry['accent2'] = self._shift_hex(app['accent'])
                return True

        badge_re = re.compile(r'(shields\.io|sonarcloud\.io|coderabbit\.ai|codecov\.io|badgen\.net|badge|workflows/|actions/workflows)', re.I)
        icon_candidates, shot_candidates = [], []
        repo_desc, web_desc, readme_text, theme_color, avatar_url = '', '', '', '', ''

        def fetch_bytes(url, timeout=12):
            req = urllib.request.Request(url, headers={'User-Agent': 'ArminLauncher/1.0'})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read(), (r.headers.get('Content-Type') or '').lower()

        website = app.get('website', '')
        if website.startswith('https://'):
            try:
                raw, ctype = fetch_bytes(website, timeout=10)
                if 'html' in ctype or b'<html' in raw[:500].lower():
                    html_txt = raw.decode('utf-8', errors='ignore')
                    m_tc = re.search(r'<meta[^>]+name=["\']theme-color["\'][^>]+content=["\'](#[0-9a-fA-F]{6})["\']', html_txt, re.I)
                    if m_tc:
                        theme_color = m_tc.group(1)
                    m_desc = re.search(r'<meta[^>]+(?:name=["\']description["\']|property=["\']og:description["\'])[^>]+content=["\']([^"\']+)["\']', html_txt, re.I)
                    if m_desc:
                        web_desc = m_desc.group(1).strip()
                    for m in re.finditer(r'<link[^>]+rel=["\'][^"\']*icon[^"\']*["\'][^>]+href=["\']([^"\']+)["\']', html_txt, re.I):
                        icon_candidates.append(urllib.parse.urljoin(website, m.group(1)))
                    for m in re.finditer(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html_txt, re.I):
                        shot_candidates.append(urllib.parse.urljoin(website, m.group(1)))
                    for m in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', html_txt, re.I):
                        u = urllib.parse.urljoin(website, m.group(1))
                        if not badge_re.search(u):
                            if 'icon' in u.lower() or 'logo' in u.lower():
                                icon_candidates.append(u)
                            else:
                                shot_candidates.append(u)
            except Exception:
                pass

        repo = (app.get('source') or {}).get('repo', '')
        branch = 'main'
        if repo:
            try:
                with self.request(f'{self.api_base}/repos/{repo}', {'Accept': 'application/vnd.github+json'}) as r:
                    rdata = json.load(r)
                repo_desc = (rdata.get('description') or '').strip()
                branch = rdata.get('default_branch') or 'main'
                avatar_url = (rdata.get('owner') or {}).get('avatar_url') or ''
            except Exception:
                pass
            try:
                with self.request(f'{self.api_base}/repos/{repo}/readme', {'Accept': 'application/vnd.github.raw+json'}) as r:
                    readme_text = r.read().decode('utf-8', errors='ignore')
                raw_base = f'https://raw.githubusercontent.com/{repo}/{branch}/'
                for m in re.finditer(r'(?:<img[^>]+src=["\']|!\[[^\]]*\]\()([^"\'\)\s]+)', readme_text, re.I):
                    u = m.group(1)
                    if badge_re.search(u):
                        continue
                    if not u.startswith(('http://', 'https://')):
                        u = urllib.parse.urljoin(raw_base, u.lstrip('./'))
                    if any(k in u.lower() for k in ('icon', 'logo', 'hicolor')):
                        icon_candidates.append(u)
                    else:
                        shot_candidates.append(u)
            except Exception:
                pass

        if avatar_url:
            icon_candidates.append(avatar_url)

        # Probe a few distinct image candidates within a per-app budget.
        asset_deadline = time.monotonic() + 25
        icon_bytes = b''
        if not has_icon:
            for u in list(dict.fromkeys(icon_candidates))[:5]:
                if self.ai_cancel.is_set():
                    raise Cancelled('Cancelled by user')
                remaining = asset_deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    data, ctype = fetch_bytes(u, timeout=min(remaining, 10))
                    if len(data) < 64:
                        continue
                    if b'<svg' in data[:500].lower():
                        (ROOT / 'ui' / 'icons' / f'{aid}.svg').write_bytes(data)
                        icon_bytes, has_icon, changed = data, True, True
                        if log is not None:
                            log.append(f'Auto-saved SVG icon for {aid}')
                        break
                    if 'image' in ctype or data[:4] in (b'\x89PNG', b'RIFF') or data[:2] == b'\xff\xd8':
                        from PIL import Image
                        import io
                        out = io.BytesIO()
                        Image.open(io.BytesIO(data)).convert('RGBA').save(out, format='PNG')
                        png_data = out.getvalue()
                        (ROOT / 'ui' / 'icons' / f'{aid}.png').write_bytes(png_data)
                        icon_bytes, has_icon, changed = png_data, True, True
                        if log is not None:
                            log.append(f'Auto-saved PNG icon for {aid}')
                        break
                except Exception:
                    continue
        else:
            for ext in ('png', 'svg'):
                p = ROOT / 'ui' / 'icons' / f'{aid}.{ext}'
                if p.is_file():
                    icon_bytes = p.read_bytes()
                    break

        if not has_shot:
            for u in list(dict.fromkeys(shot_candidates))[:5]:
                if self.ai_cancel.is_set():
                    raise Cancelled('Cancelled by user')
                remaining = asset_deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    data, ctype = fetch_bytes(u, timeout=min(remaining, 10))
                    if len(data) < 2048 or b'<svg' in data[:400].lower():
                        continue
                    ext = '.png' if data[:4] == b'\x89PNG' else '.webp' if data[:4] == b'RIFF' else '.jpg'
                    fname = f'{aid}-1{ext}'
                    (ROOT / 'ui' / 'shots' / fname).write_bytes(data)
                    entry = details.setdefault(aid, {'about': '', 'features': [], 'shots': []})
                    entry['shots'] = [{'caption': f'{app["name"]} preview', 'url': f'/shots/{fname}'}]
                    has_shot, changed = True, True
                    if log is not None:
                        log.append(f'Auto-saved screenshot for {aid}')
                    break
                except Exception:
                    continue

        entry = details.setdefault(aid, {'about': '', 'features': [], 'shots': []})
        if not entry.get('about'):
            entry['about'] = web_desc or repo_desc or app.get('tagline', '')
            changed = True
        if not entry.get('features'):
            feats = []
            for line in readme_text.splitlines():
                m = re.match(r'^\s*[-*]\s+\*\*([^*]{2,40})\*\*[:\-\s]+(.{8,140})$', line)
                if m:
                    feats.append({'title': m.group(1).strip(), 'text': m.group(2).strip()})
                if len(feats) >= 3:
                    break
            if not feats and entry.get('about'):
                feats = [{'title': app['name'], 'text': entry['about']}]
            if feats:
                entry['features'] = feats
                changed = True

        extracted = theme_color or (self._extract_accent_from_bytes(icon_bytes, app.get('accent', '#2d81ff')) if icon_bytes else app.get('accent', '#2d81ff'))
        if re.fullmatch(r'#[0-9a-fA-F]{6}', extracted) and app.get('accent', '').lower() in ('#2d81ff', '#000000', '#ffffff', ''):
            app['accent'] = extracted
            changed = True
        if not entry.get('accent2'):
            entry['accent2'] = self._shift_hex(app.get('accent') or extracted)
            changed = True
        return changed

    def launch_subscription_login(self, cli='opencode'):
        c = (cli or 'opencode').strip().lower()
        if c not in ('opencode', 'codex', 'claude', 'gemini'):
            raise ValueError(f'Unsupported subscription CLI: {c}')
        if not shutil.which(c):
            raise ValueError(f'{c} CLI is not installed')
        login_cmd = {
            'opencode': ['opencode', 'auth', 'login'],
            'codex': ['codex', 'login'],
            'claude': ['claude', 'login'],
            'gemini': ['gemini'],
        }[c]
        if IS_WIN:
            subprocess.Popen(['cmd', '/c', 'start', '', *login_cmd], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        term = next((t for t in ('xdg-terminal-exec', 'ghostty', 'kitty', 'alacritty', 'foot', 'wezterm', 'konsole', 'gnome-terminal') if shutil.which(t)), '')
        if not term:
            raise ValueError(f'No terminal emulator found. Run `{" ".join(login_cmd)}` in your terminal.')
        if term in ('gnome-terminal',):
            argv = [term, '--', *login_cmd]
        elif term in ('alacritty', 'kitty', 'ghostty', 'konsole', 'foot'):
            argv = [term, '-e', *login_cmd]
        else:
            argv = [term, *login_cmd]
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

    def _ai_release_facts(self, repos, label, noise_asset_re):
        def lookup(repo):
            try:
                with self.request(f'{self.api_base}/repos/{repo}/releases/latest', {'Accept': 'application/vnd.github+json'}) as response:
                    release = json.load(response)
                return {'latest_tag': release.get('tag_name'), 'assets': [
                    asset['name'] for asset in release.get('assets', []) if not noise_asset_re.search(asset['name'])]}
            except urllib.error.HTTPError as e:
                return {'api_status': e.code}
            except (OSError, KeyError, ValueError) as e:
                return {'api_error': str(e)}

        facts = {}
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=5, thread_name_prefix='armin-ai-release')
        try:
            pending = {executor.submit(lookup, name): name for name in dict.fromkeys(repos)}
            total = len(pending)
            while pending:
                if self.ai_cancel.is_set():
                    raise Cancelled('Cancelled by user')
                done, _ = concurrent.futures.wait(pending, timeout=.2, return_when=concurrent.futures.FIRST_COMPLETED)
                if done:
                    for future in done:
                        facts[pending.pop(future)] = future.result()
                    self._publish_ai(f'{label} ({len(facts)}/{total})')
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        return facts

    def ai_maintain(self, prompt='', model='gpt-4o-mini', provider='openai', base_url='', thinking='auto'):
        key = self.get_ai_key(provider)
        if provider not in ('custom', 'subscription') and not key:
            raise ValueError(f'Set an API key for {provider} first')
        with self.lock:
            self._begin_ai('Checking catalog')
            self.ai_report = 'Gathering live release and asset metadata…'
        self._publish_ai()

        def work():
            log = []
            changed = False
            outcome = 'complete'
            try:
                linux_path = ROOT / 'catalog.json'
                win_path = ROOT / 'catalog.windows.json'
                bundled = self.catalog.path in (linux_path, win_path)
                if not bundled:
                    active = self.catalog.load()
                    windows_catalog = (self.catalog.path.name.endswith('.windows.json') or
                                       any(app['install']['type'] in ('winget', 'exe', 'msi', 'zip') for app in active['apps']) or
                                       (not active['apps'] and IS_WIN))
                    linux_path = None if windows_catalog else self.catalog.path
                    win_path = self.catalog.path if windows_catalog else None
                empty = {'version': 1, 'apps': []}
                linux_cat = Catalog(linux_path).load() if linux_path else empty
                win_cat = Catalog(win_path).load() if win_path and win_path.is_file() else empty
                det_path = ROOT / 'ui' / 'details.json'
                details = json.loads(det_path.read_text()) if bundled and det_path.is_file() else {}
                last_tags = dict(self.state.get('ai_last_maintain_tags', {}))
                stale_shots = []

                # 1. Gather live facts in Python
                noise_asset_re = re.compile(r'(\.(sha256|sha512|sha1|md5|sig|asc|zsync|blockmap)|arm64|aarch64|armv7|i386|i686)', re.I)
                facts = []
                total_apps = len(linux_cat['apps'])
                known_repos = [app['source']['repo'] for app in linux_cat['apps'] if app['source']['type'] == 'github_release']
                release_facts = self._ai_release_facts(known_repos, 'Checking releases', noise_asset_re)
                for idx_app, a in enumerate(linux_cat['apps'], 1):
                    if self.ai_cancel.is_set():
                        raise Cancelled('Cancelled by user')
                    aid = a['id']
                    if idx_app == 1 or idx_app % 5 == 0 or idx_app == total_apps:
                        self.ai_report = f'Checking catalog & releases ({idx_app}/{total_apps}): {a["name"]}…'
                        self._publish_ai(f'Checking catalog ({idx_app}/{total_apps})')
                    has_icon = bundled and any((ROOT / 'ui' / 'icons' / f'{aid}.{e}').is_file() for e in ('png', 'svg'))
                    shots = [s for s in details.get(aid, {}).get('shots', []) if s.get('url', '').startswith('/shots/') and (ROOT / 'ui' / s['url'].lstrip('/')).is_file()]
                    launch_info = self.check_launchable(a)
                    if bundled and launch_info.get('fixable_chmod') and launch_info.get('exe'):
                        try:
                            os.chmod(launch_info['exe'], 0o755)
                            launch_info = self.check_launchable(a)
                            log.append(f'Fixed +x permissions for {a["name"]}')
                        except OSError:
                            pass
                    if bundled and launch_info.get('fixable_x11') and not IS_WIN:
                        try:
                            for sock in Path('/tmp/.X11-unix').glob('X[0-9]*_'):
                                tgt = sock.with_name(sock.name[:-1])
                                if sock.is_socket() and not tgt.exists():
                                    tgt.symlink_to(sock.name)
                            launch_info = self.check_launchable(a)
                            log.append('Restored missing /tmp/.X11-unix/X0 symlink')
                        except OSError:
                            pass
                    if launch_info.get('installed') and launch_info.get('ok') is False:
                        log.append(f'Launch check failed for {a["name"]}: {launch_info.get("reason")}')
                    item = {'id': aid, 'name': a['name'], 'source': a['source'], 'install': a['install'], 'has_icon': has_icon if bundled else None, 'local_shots': len(shots) if bundled else None, 'build_info': details.get(aid, {}).get('build_info'), 'launchable': launch_info}
                    if a['source']['type'] == 'github_release':
                        item.update(release_facts[a['source']['repo']])
                    cur_tag = item.get('latest_tag') or self.state.get('releases', {}).get(aid, {}).get('tag')
                    if cur_tag:
                        item['latest_tag'] = cur_tag
                        prev_tag = last_tags.get(aid)
                        if prev_tag and prev_tag != cur_tag and len(shots) > 0:
                            item['shot_stale'] = True
                            item['prev_maintain_tag'] = prev_tag
                            stale_shots.append(aid)
                    facts.append(item)
                win_facts = [{'id': a['id'], 'name': a['name'], 'source': a['source'], 'install': a['install']} for a in win_cat['apps']]

                known_names = {name.lower() for name in known_repos}
                artcraft_repos = []
                self.ai_report = f'Checked {len(facts)} apps\nChecking ArtCraft (storytold) for new releases…'
                self._publish_ai('Checking new releases')
                try:
                    with self.request(f'{self.api_base}/users/storytold/repos?per_page=30&sort=updated', {'Accept': 'application/vnd.github+json'}) as response:
                        candidates = {repo['full_name']: repo for repo in json.load(response)
                                      if repo.get('full_name') and not repo.get('archived') and not repo.get('fork')
                                      and repo['full_name'].lower() not in known_names}
                except Exception:
                    candidates = {}
                discoveries = self._ai_release_facts(candidates, 'Checking new releases', noise_asset_re)
                for name, repo in candidates.items():
                    release = discoveries[name]
                    if release.get('assets'):
                        artcraft_repos.append({'repo': name, 'name': repo.get('name'), 'description': repo.get('description'),
                                               'homepage': repo.get('homepage'), **release})

                search_hits = []
                if prompt.strip():
                    q = urllib.parse.quote(prompt.strip())
                    try:
                        with self.request(f'{self.api_base}/search/repositories?q={q}&per_page=5', {'Accept': 'application/vnd.github+json'}) as r:
                            for repo in json.load(r).get('items', []):
                                if self.ai_cancel.is_set():
                                    break
                                rname = repo['full_name']
                                assets = []
                                try:
                                    with self.request(f'{self.api_base}/repos/{rname}/releases/latest', {'Accept': 'application/vnd.github+json'}) as rr:
                                        assets = [x['name'] for x in json.load(rr).get('assets', [])]
                                except Exception:
                                    pass
                                search_hits.append({'repo': rname, 'description': repo.get('description'), 'homepage': repo.get('homepage'), 'assets': assets})
                    except Exception:
                        pass
                    try:
                        with urllib.request.urlopen(f'https://aur.archlinux.org/rpc/v5/search/{q}', timeout=10) as r:
                            search_hits.append({'aur': [x['Name'] for x in json.loads(r.read()).get('results', [])[:5]]})
                    except Exception:
                        pass

                log.append(f'Checked {len(facts)} apps' + (f' ({len(stale_shots)} screenshot(s) flagged stale after update)' if stale_shots else '') + (f' + {len(artcraft_repos)} new ArtCraft releases' if artcraft_repos else '') + (f' + search hits for "{prompt.strip()}"' if prompt.strip() else ''))

                # 2. Call selected AI provider
                sys_prompt = (
                    'You maintain Armin Launcher (catalog.json for Linux x86_64 and catalog.windows.json for Windows). '
                    'Each app object MUST have exact keys: id, name, publisher, category, tagline, accent (#rrggbb), website (https://...), source, install, hidden (bool). '
                    'Valid source: {"type": "github_release", "repo": "owner/repo", "asset_pattern": "glob", "prerelease": bool} or {"type": "arch_repo"|"aur"|"winget", "package": "pkg"}. '
                    'Valid install: {"type": "appimage", "binary_name": "name", "launch": "cmd"} | {"type": "tarball"|"zip", "bin": "rel/path", "launch": "cmd"} | {"type": "pacman_pkg"|"pacman"|"aur"|"winget"|"msi"|"exe", "package": "pkg", "launch": "cmd"}. '
                    'Prefer pre-built downloadable versions (github_release, arch_repo, or -bin AUR) over compiling from source. '
                    'If artcraft_repos contains any newly released ArtCraft app not yet in facts, propose adding it to linux_updates (and win_updates if Windows assets exist). '
                    'If any installed app has launchable.ok == false, propose repair commands in fix_commands (set needs_admin=true when root/sudo/pacman is needed). '
                    'If an app has shot_stale=true (updated since last maintain) or its screenshot no longer represents it well, propose a fresh verified shot_url in assets. '
                    'Given the live app facts, win_facts, artcraft_repos, and optional user request, return ONLY valid JSON with keys: '
                    '{"summary": str, "linux_updates": [app_obj], "win_updates": [app_obj], '
                    '"remove_ids": [str], "fix_commands": [{"title": str, "cmd": str, "needs_admin": bool}], '
                    '"assets": [{"id": str, "icon_url": str|null, "shot_url": str|null, "shot_caption": str, "about": str, "features": [{"title": str, "text": str}], "build_info": {"from_source": bool, "estimated_gb": number, "base_minutes_8core": number}|null}]}. '
                    'Only suggest real, verified assets seen in the provided facts, artcraft_repos, or search_hits. Keep lists empty if no changes are needed.'
                )
                if not bundled:
                    target = 'Windows' if win_path else 'Linux'
                    sys_prompt += f' This run maintains only the selected {target} catalog. Local asset metadata is unavailable. Leave assets and the other platform empty.'
                user_payload = json.dumps(
                    {'request': prompt.strip() or 'Audit catalog for better install/update methods, new ArtCraft apps, unreleased removals, and missing icons/screenshots.', 'facts': facts, 'win_facts': win_facts, 'artcraft_repos': artcraft_repos, 'search_hits': search_hits},
                    separators=(',', ':'),
                )
                def ask_provider(payload, label):
                    if self.ai_cancel.is_set():
                        raise Cancelled('Cancelled by user')
                    self.ai_report = '\n'.join([*log, label])
                    self._publish_ai(f'Waiting for {base_url if provider == "subscription" and base_url else provider}')
                    result = self.call_ai_provider(provider, key, model, base_url, sys_prompt, payload, thinking=thinking)
                    if self.ai_cancel.is_set():
                        raise Cancelled('Cancelled by user')
                    return result

                plan = ask_provider(user_payload, f'Asking {provider} ({model or "default"}) to review catalog and assets…')

                def build_and_validate(candidate):
                    nl = copy.deepcopy(linux_cat)
                    nw = copy.deepcopy(win_cat)
                    rids = set(candidate.get('remove_ids') or [])
                    if rids:
                        nl['apps'] = [a for a in nl['apps'] if a['id'] not in rids]
                        nw['apps'] = [a for a in nw['apps'] if a['id'] not in rids]

                    def upsert(cat_obj, items):
                        for item in items or []:
                            if not isinstance(item, dict) or not item.get('id'):
                                continue
                            cleaned = {k: item[k] for k in APP_KEYS if k in item and item[k] is not None}
                            idx = next((i for i, x in enumerate(cat_obj['apps']) if x['id'] == cleaned['id']), None)
                            if idx is None:
                                cleaned.setdefault('hidden', False)
                                cat_obj['apps'].append(cleaned)
                            else:
                                cat_obj['apps'][idx] = {**cat_obj['apps'][idx], **cleaned}

                    upsert(nl, candidate.get('linux_updates'))
                    upsert(nw, candidate.get('win_updates'))
                    validate_catalog(nl)
                    if nw['apps']:
                        validate_catalog(nw)
                    return nl, nw, rids

                try:
                    new_linux, new_win, remove_ids = build_and_validate(plan)
                except Exception as val_err:
                    log.append(f'AI plan failed validation ({val_err}) — asking AI to fix it…')
                    self.ai_report = '\n'.join(log)
                    self._publish_ai('Validating catalog changes')
                    repair_payload = json.dumps({'error': str(val_err), 'previous_plan': plan, 'facts': facts, 'win_facts': win_facts}, separators=(',', ':'))
                    plan = ask_provider(repair_payload, f'Repairing AI plan with {provider} ({model or "default"})…')
                    new_linux, new_win, remove_ids = build_and_validate(plan)

                self._publish_ai('Applying catalog changes')
                log.append('AI summary: ' + str(plan.get('summary', 'Done.')))
                if remove_ids:
                    log.append('Removed: ' + ', '.join(sorted(remove_ids)))
                fixes = []
                for idx_f, f in enumerate(plan.get('fix_commands') or []):
                    if isinstance(f, dict) and str(f.get('cmd', '')).strip():
                        fixes.append({
                            'id': f'fix-{int(time.time()*1000)}-{idx_f}',
                            'title': str(f.get('title') or f['cmd'])[:80],
                            'cmd': str(f['cmd']).strip(),
                            'needs_admin': bool(f.get('needs_admin', False)),
                        })
                with self.lock:
                    self.pending_fixes = fixes
                if fixes:
                    log.append(f'Proposed {len(fixes)} fix command(s) — click Run below to execute.')

                if self.ai_cancel.is_set():
                    raise Cancelled('Cancelled by user')
                assets = (plan.get('assets') or []) if bundled else []
                for asset in assets:
                    if self.ai_cancel.is_set():
                        raise Cancelled('Cancelled by user')
                    aid = asset.get('id', '')
                    if not re.fullmatch(r'[a-z0-9-]+', aid):
                        continue
                    bi = asset.get('build_info')
                    if isinstance(bi, dict):
                        entry = details.setdefault(aid, {'about': asset.get('about', ''), 'features': asset.get('features', []), 'shots': []})
                        entry['build_info'] = {
                            'from_source': bool(bi.get('from_source', True)),
                            'estimated_gb': round(max(0.1, float(bi.get('estimated_gb') or 2.5)), 1),
                            'base_minutes_8core': round(max(1.0, float(bi.get('base_minutes_8core') or 10.0)), 1),
                        }
                        atomic_json(det_path, details)
                        changed = True
                        log.append(f'Updated build info for {aid}')
                    if asset.get('icon_url'):
                        try:
                            data = urllib.request.urlopen(urllib.request.Request(asset['icon_url'], headers={'User-Agent': 'ArminLauncher/1.0'}), timeout=15).read()
                            ext = '.svg' if b'<svg' in data[:400].lower() else '.png'
                            (ROOT / 'ui/icons' / f'{aid}{ext}').write_bytes(data)
                            changed = True
                            log.append(f'Saved icon for {aid}')
                        except Exception:
                            pass
                    if asset.get('shot_url'):
                        try:
                            data = urllib.request.urlopen(urllib.request.Request(asset['shot_url'], headers={'User-Agent': 'ArminLauncher/1.0'}), timeout=20).read()
                            ext = '.png' if asset['shot_url'].lower().endswith('.png') else '.webp' if asset['shot_url'].lower().endswith('.webp') else '.jpg'
                            fname = f'{aid}-1{ext}'
                            (ROOT / 'ui/shots' / fname).write_bytes(data)
                            entry = details.setdefault(aid, {'about': asset.get('about', ''), 'features': asset.get('features', []), 'shots': []})
                            entry['shots'] = [{'caption': asset.get('shot_caption') or aid, 'url': f'/shots/{fname}'}]
                            atomic_json(det_path, details)
                            changed = True
                            log.append(f'Saved screenshot for {aid}')
                        except Exception:
                            pass

                enriched_any = False
                asset_apps = new_linux['apps'] if bundled else []
                for idx, app_obj in enumerate(asset_apps, 1):
                    self._publish_ai(f'Checking assets ({idx}/{len(asset_apps)}): {app_obj["name"]}')
                    if self.ai_cancel.is_set():
                        raise Cancelled('Cancelled by user')
                    if self.enrich_app_assets(app_obj, details, log):
                        enriched_any = True
                if enriched_any:
                    validate_catalog(new_linux)
                    atomic_json(det_path, details)
                    changed = True

                # Recheck under the same locks as the editor immediately before
                # publishing. The expensive model and network calls ran unlocked.
                updates = [(path, before, after) for path, before, after in
                           ((linux_path, linux_cat, new_linux), (win_path, win_cat, new_win))
                           if path and before != after]
                with contextlib.ExitStack() as locks:
                    for path, before, after in sorted(updates):
                        locks.enter_context(Catalog(path).locked())
                        current = Catalog(path).load() if path.is_file() else empty
                        if current != before:
                            raise ValueError(f'{path.name} changed during the audit. Run the audit again to review your edits.')
                    for path, _, after in updates:
                        atomic_json(path, after)
                        changed = True

                if changed and bundled:
                    self._publish_ai('Verifying catalog changes')
                    t = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests'], cwd=ROOT, capture_output=True, text=True, timeout=60)
                    if t.returncode != 0:
                        raise ValueError('Tests failed after AI update:\n' + t.stderr[-500:])
                    log.append('All unit tests passed.')
                elif changed:
                    log.append('Validated the updated catalog.')
                else:
                    log.append('Catalog already up to date — no changes needed.')

                with self.lock:
                    tag_map = self.state.setdefault('ai_last_maintain_tags', {})
                    for item in facts:
                        if item.get('latest_tag'):
                            tag_map[item['id']] = item['latest_tag']
                    self.save()
                self.ai_report = '\n'.join(log)
                self.notice = 'AI Maintain complete.'
            except Cancelled:
                outcome = 'cancelled'
                log.append('Cancelled by user.')
                self.ai_report = '\n'.join(log)
                self.notice = 'AI Maintain cancelled.'
            except Exception as e:
                outcome = 'error'
                log.append(f'Error: {e}')
                self.ai_report = '\n'.join(log)
                self.last_error = str(e)
                self.notice = str(e)
                self.emit('error', {'message': str(e)})
            finally:
                self._finish_ai(outcome)
                if changed:
                    self.emit('state', self.snapshot())

        threading.Thread(target=work, name='armin-ai-maintain', daemon=True).start()

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
        request = urllib.request.Request(url, headers=req_headers, method=method)
        if run := getattr(self._refresh_context, 'run', None):
            return urllib.request.urlopen(request, timeout=min(run.REQUEST_TIMEOUT, run.remaining()), context=run.ssl_context)
        return urllib.request.urlopen(request, timeout=20)

    def github_release(self, app):
        src = app['source']
        url = f'{self.api_base}/repos/{src["repo"]}/releases' + ('?per_page=30' if src.get('prerelease') else '/latest')
        run = getattr(self._refresh_context, 'run', None)
        with self.lock:
            cache = run.http if run else self.state['http']
            cached = cache.get(url, {})
        headers = {'Accept': 'application/vnd.github+json'}
        if cached.get('etag'):
            headers['If-None-Match'] = cached['etag']
        try:
            with self.request(url, headers) as response:
                body = json.load(response)
                with self.lock:
                    if run:
                        run.remaining()
                    cache[url] = {'etag': response.headers.get('ETag'), 'body': body}
                    if run:
                        run.http_updates[url] = cache[url]
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
        with self.lock:
            old = copy.deepcopy(self.cached_release(app))
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

    def cached_release(self, app):
        app_id = app['id']
        source = self.state['release_sources'].get(app_id, app['source'])
        return self.state['releases'].get(app_id, {}) if app['source'] == source else {}

    def _record_release(self, app, release):
        self.state['releases'][app['id']] = release
        self.state['release_sources'][app['id']] = app['source'].copy()

    def _refresh_package_group(self, source, apps):
        argv = (['pacman', '-Qu'] if source == 'arch_repo' else
                [shutil.which('yay') or shutil.which('paru'), '-Qua'])
        if not argv[0] or not shutil.which(argv[0]):
            return {}, [f'{source}: package helper is not installed']
        result = self.command(argv, timeout=6)
        # pacman returns 1 for no upgrades. Other failures carry stderr.
        failed = result.returncode != 0 and bool(result.stderr.strip())
        warnings = [f'{source}: {result.stderr.strip()}'] if failed else []
        versions = {}
        for line in result.stdout.splitlines():
            fields = line.split()
            if len(fields) >= 4 and fields[2] == '->':
                versions[fields[0]] = fields[3]
        if source == 'arch_repo':
            missing = list(dict.fromkeys(a['source']['package'] for a in apps if a['source']['package'] not in versions))
            if missing:
                result = self.command(['pacman', '-Si', *missing], timeout=4)
                if result.returncode and result.stderr.strip():
                    failed = True
                    warnings.append(f'{source}: {result.stderr.strip()}')
                for name, version in re.findall(r'^Name\s*:\s*(\S+)[^\n]*\nVersion\s*:\s*(\S+)', result.stdout, re.M):
                    versions[name] = version
        releases = {}
        for app in apps:
            version = versions.get(app['source']['package'])
            if version or not failed:
                releases[app['id']] = self._package_release(app, version)
        return releases, warnings

    def _package_release(self, app, version):
        return dict(tag=version or self.installed(app), notes='Package updates use the configured package databases.',
                    url=app['website'], checked=time.time())

    def _refresh_app(self, app):
        src = app['source']
        if src['type'] == 'github_release':
            return self.github_release(app)
        if src['type'] == 'local':
            return dict(tag='local', notes='Local user-built application.', url=app['website'], checked=time.time())
        version = None
        if src['type'] == 'winget' and IS_WIN and shutil.which('winget'):
            result = self.command(['winget', 'show', '--id', src['package'], '-e', '--accept-source-agreements'], timeout=6)
            match = re.search(r'^Version:\s*(\S+)', result.stdout, re.M)
            if result.returncode or not match:
                raise ValueError(result.stderr.strip() or 'WinGet could not determine the latest version')
            version = match[1]
        return self._package_release(app, version)

    def refresh(self):
        apps = self.catalog.load()['apps']
        with self.lock:
            run = RefreshRun(self.cancel, self.state['http'])
            checked = {app['id']: self.cached_release(app).get('checked') or 0 for app in apps}
        if any(app['source']['type'] == 'github_release' for app in apps):
            run.ssl_context = ssl.create_default_context()

        tasks = queue.Queue()
        results = queue.Queue()
        for source in ('arch_repo', 'aur'):
            group = [a for a in apps if a['source']['type'] == source]
            if group:
                tasks.put((source, group))
        for app in sorted(apps, key=lambda a: checked.get(a['id'], 0)):
            if app['source']['type'] not in ('arch_repo', 'aur'):
                tasks.put((None, [app]))

        def check():
            self._refresh_context.run = run
            try:
                while not tasks.empty():
                    run.remaining()
                    if not self._refresh_slots.acquire(timeout=.1):
                        continue
                    try:
                        source, group = tasks.get_nowait()
                        try:
                            if source:
                                releases, warnings = self._refresh_package_group(source, group)
                            else:
                                app = group[0]
                                releases, warnings = {app['id']: self._refresh_app(app)}, []
                            run.remaining()
                        except Cancelled:
                            return
                        except TimeoutError:
                            run.remaining()
                            labels = source or group[0]['name']
                            releases, warnings = {}, [f'{labels}: check timed out; kept cached results']
                        except Exception as exc:
                            labels = source or group[0]['name']
                            releases, warnings = {}, [f'{labels}: {exc}']
                        results.put((group, releases, warnings))
                    finally:
                        self._refresh_slots.release()
            except (Cancelled, TimeoutError, queue.Empty):
                pass

        pending = {app['id']: app for app in apps}
        releases = {}
        warnings = []
        rate_limited = 0
        self.emit('refresh-progress', dict(completed=0, total=len(apps)))
        try:
            for _ in range(min(RefreshRun.WORKERS, tasks.qsize())):
                # An unresponsive network call must not keep the local server process open.
                threading.Thread(target=check, name='launchcraft-refresh-check', daemon=True).start()
            while pending:
                try:
                    wait = min(.1, run.remaining())
                    group, found, issues = results.get(timeout=wait)
                except queue.Empty:
                    continue
                except TimeoutError:
                    warnings.insert(0, f'Refresh timed out on {len(pending)} of {len(apps)} app checks; kept cached results.')
                    break
                warnings.extend(issues)
                releases.update(found)
                for app in group:
                    del pending[app['id']]
                    warning = found.get(app['id'], {}).get('warning')
                    if warning and 'GitHub rate limited' in warning:
                        rate_limited += 1
                        if 'Asset metadata unavailable' not in warning:
                            continue
                    if warning:
                        warnings.append(f'{app["name"]}: {warning}')
                self.emit('refresh-progress', dict(completed=len(apps) - len(pending), total=len(apps)))
            if self.cancel.is_set():
                raise Cancelled()
            if rate_limited:
                warnings.insert(0, f'GitHub API rate limit reached ({rate_limited} apps); versions fetched via release redirects.')
            current_sources = {app['id']: app['source'] for app in self.catalog.load()['apps']}
            with self.lock:
                run.done.set()
                self.state['http'].update(run.http_updates)
                for app in apps:
                    app_id = app['id']
                    if app_id in releases and app['source'] == current_sources.get(app_id):
                        self._record_release(app, releases[app_id])
                self.save()
                self.warnings = warnings
                self.notice = 'Refresh complete' if not warnings else 'Refresh complete with warnings'
        finally:
            run.done.set()

    def start(self, action, ids=None, clean=False, allow_build=False):
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
                    self.install_many(ids, allow_build=allow_build)
            except Cancelled:
                self.notice = ('Refresh cancelled' if action == 'refresh' else
                               'Cancelled. Partial downloads are kept for resume.')
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
        if action != 'refresh':
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
                self.status(appid, 'Installing', percent=5, message='Authentication may be required. Package transactions finish safely before cancellation.')
            # Do not terminate pacman in the middle of its database transaction.
            process = subprocess.Popen(
                argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                text=True, errors='replace', bufsize=1,
            )
            tail = []
            phase, pct, compiled = 'Installing', 5, 0
            last_emit = 0.0
            for raw in process.stdout:
                tail.append(raw)
                if len(tail) > 200:
                    tail = tail[-120:]
                line = raw.strip()
                if not line:
                    continue
                new_phase, new_pct = phase, pct
                m = re.search(r'(\d{1,3})%', line)
                if m:
                    val = min(98, max(5, int(m.group(1))))
                    if val >= pct or phase != 'Installing':
                        new_pct = val
                elif re.search(r'Downloading|Cloning|Retrieving', line, re.I):
                    new_phase, new_pct = 'Downloading', max(pct, 15)
                elif re.search(r'Checking|Resolving|Validating', line, re.I):
                    new_phase, new_pct = 'Preparing', max(pct, 25)
                elif re.search(r'Making package|Extracting|Starting build', line, re.I):
                    new_phase, new_pct = 'Building', max(pct, 35)
                elif 'Compiling ' in line:
                    compiled += 1
                    new_phase = 'Building'
                    new_pct = max(pct, min(82, 38 + compiled))
                elif re.search(r'Packaging|Tidying|Creating package', line, re.I):
                    new_phase, new_pct = 'Packaging', max(pct, 85)
                elif re.search(r'\b(installing|upgrading)\b', line, re.I):
                    new_phase, new_pct = 'Installing', max(pct, 92)
                now = time.monotonic()
                if (new_phase != phase or new_pct != pct) and (now - last_emit >= 0.15 or new_phase != phase):
                    phase, pct, last_emit = new_phase, new_pct, now
                    for appid in ids:
                        self.status(appid, phase, percent=pct, message=line[:140])
            process.wait()
            log = ''.join(tail)[-10000:]
            if process.returncode:
                raise ValueError(f'Installer exited {process.returncode}: {log.strip()}')

    def app(self, appid):
        return next((a for a in self.catalog.load()['apps'] if a['id'] == appid), None)

    def install_many(self, ids=None, allow_build=False):
        apps = self.catalog.load()['apps']
        details = self.load_details()
        if ids is None:
            snap = self.snapshot()
            ids = [a['id'] for a in snap['apps'] if a['update'] and not a['hidden'] and not a.get('build_info')]
        chosen = [a for a in apps if a['id'] in ids]
        if len(chosen) != len(set(ids)):
            raise ValueError('Unknown app ID')
        if not allow_build:
            for a in chosen:
                if self.app_build_info(a, details.get(a['id'])):
                    raise ValueError(f'{a["name"]} requires building from source; confirm BUILD to proceed')
        packages = []
        for a in chosen:
            self.status(a['id'], 'Queued')
        try:
            for app in chosen:
                appid, ins = app['id'], app['install']
                if self.cancel.is_set():
                    raise Cancelled()
                if app['source']['type'] == 'github_release':
                    with self.lock:
                        release = self.cached_release(app)
                    if not release or not release.get('asset'):
                        release = self.github_release(app)
                        with self.lock:
                            self._record_release(app, release)
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
                    try:
                        self.transaction([helper, '-S', '--needed', '--noconfirm', *sudo_args, ins['package']], [appid])
                    finally:
                        for cache_dir in (self.home / '.cache' / 'yay' / ins['package'], self.home / '.cache' / 'paru' / 'clone' / ins['package']):
                            if cache_dir.is_dir():
                                shutil.rmtree(cache_dir, ignore_errors=True)
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
        if not IS_WIN:
            x11_dir = Path('/tmp/.X11-unix')
            if x11_dir.is_dir():
                for sock in x11_dir.glob('X[0-9]*_'):
                    target = sock.with_name(sock.name[:-1])
                    if sock.is_socket() and not target.exists():
                        try:
                            target.symlink_to(sock.name)
                        except OSError:
                            pass
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
        self.instance_id = secrets.token_hex(16)
        self.origin = f'http://127.0.0.1:{self.server_port}'
        self.grace, self.startup_timeout = grace, startup_timeout
        self.last_client = time.monotonic()
        self.ever_connected = False
        self.stopping = threading.Event()
        self.lifecycle = threading.RLock()

    def monitor(self):
        while not self.stopping.wait(.2):
            with self.lifecycle, self.engine.lock:
                if self.engine.listeners or self.engine.ai_running or (self.engine.busy and not self.engine.refreshing):
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
        elif path == '/api/instance':
            with self.server.lifecycle:
                if self.server.stopping.is_set():
                    self.json(503, {'error': 'Server closing'})
                    return
                # Give the newly opened desktop window time to establish its SSE stream.
                self.server.ever_connected = False
                self.server.last_client = time.monotonic()
                self.json(200, {'instance': self.server.instance_id})
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
            elif path == '/api/ai_keys':
                provider = str(data.get('provider', 'openai')).strip().lower()
                if provider not in ('openai', 'anthropic', 'gemini', 'openrouter', 'custom'):
                    raise ValueError('Unsupported AI provider')
                op = str(data.get('op', 'select')).strip().lower()
                if op == 'add':
                    raw_key = str(data.get('api_key', '')).strip()
                    if not raw_key:
                        raise ValueError('API key is required')
                    engine.save_ai_key(provider, raw_key, str(data.get('label', '')))
                elif op == 'select':
                    engine.select_ai_key(provider, str(data.get('key_id', '')).strip())
                elif op == 'delete':
                    engine.delete_ai_key(provider, str(data.get('key_id', '')).strip())
                else:
                    raise ValueError('Unsupported ai_keys op')
                self.json(200, engine.snapshot())
                return
            elif path == '/api/ai_sub_login':
                cli = str(data.get('cli', 'opencode')).strip().lower()
                engine.launch_subscription_login(cli)
                self.json(200, {'ok': True})
                return
            elif path == '/api/ai_models':
                provider = str(data.get('provider', 'openai')).strip().lower()
                if provider not in ('openai', 'anthropic', 'gemini', 'openrouter', 'custom', 'subscription'):
                    raise ValueError('Unsupported AI provider')
                key = str(data.get('api_key', '')).strip()
                if not key and data.get('key_id'):
                    with engine.lock:
                        entries = engine._ensure_key_profiles(provider)
                        selected = next((e for e in entries if e['id'] == data['key_id']), None)
                        if not selected:
                            raise ValueError('API key not found')
                        key = selected['key']
                models = engine.fetch_ai_models(provider, key, str(data.get('base_url', '')))
                self.json(200, {'models': models, 'ai_models': engine.state.get('ai_models', {})})
                return
            elif path == '/api/ai_maintain':
                provider = str(data.get('provider', 'openai')).strip().lower()
                if provider not in ('openai', 'anthropic', 'gemini', 'openrouter', 'custom', 'subscription'):
                    raise ValueError('Unsupported AI provider')
                model = str(data.get('model', '')).strip()
                base_url = str(data.get('base_url', '')).strip()
                thinking = str(data.get('thinking', 'auto')).strip().lower()
                if thinking not in ('auto', 'low', 'medium', 'high'):
                    thinking = 'auto'
                if 'api_key' in data and str(data['api_key']).strip():
                    engine.save_ai_key(provider, str(data['api_key']).strip(), str(data.get('key_label', '')))
                elif data.get('key_id'):
                    engine.select_ai_key(provider, str(data['key_id']).strip())
                with engine.lock:
                    prefs = engine.state.setdefault('prefs', {})
                    prefs['ai_provider'] = provider
                    prefs['ai_thinking'] = thinking
                    if model:
                        model_key = f'subscription:{base_url}' if provider == 'subscription' and base_url else provider
                        prefs.setdefault('ai_selected_models', {})[model_key] = model[:200]
                    if provider == 'custom' and base_url:
                        prefs['ai_base_url'] = base_url[:300]
                    engine.save()
                engine.ai_maintain(prompt=str(data.get('prompt', '')), model=model, provider=provider, base_url=base_url, thinking=thinking)
                self.json(200, engine.ai_state())
                return
            elif path == '/api/ai_terminal':
                provider = str(data.get('provider', 'openai')).strip().lower()
                if provider not in ('openai', 'anthropic', 'gemini', 'openrouter', 'custom', 'subscription'):
                    provider = 'openai'
                if data.get('key_id'):
                    engine.select_ai_key(provider, str(data['key_id']).strip())
                thinking = str(data.get('thinking', 'auto')).strip().lower()
                if thinking not in ('auto', 'low', 'medium', 'high'):
                    thinking = 'auto'
                engine.terminal_exec(
                    str(data.get('input', '')),
                    provider=provider,
                    model=str(data.get('model', '')).strip(),
                    base_url=str(data.get('base_url', '')).strip(),
                    thinking=thinking,
                )
                self.json(200, engine.ai_state())
                return
            elif path == '/api/ai_fix':
                engine.run_pending_fix(str(data.get('id', '')).strip())
                self.json(200, engine.ai_state())
                return
            elif path == '/api/ai_cancel':
                engine.cancel_ai()
                self.json(200, engine.ai_state())
                return
            elif path == '/api/install':
                ids = data.get('ids')
                if ids is not None and (not isinstance(ids, list) or not all(isinstance(i, str) for i in ids)):
                    raise ValueError('ids must be a list')
                engine.start('install', ids, allow_build=bool(data.get('allow_build', False)))
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
                        t = str(data['theme']).strip()
                        if not re.fullmatch(r'[a-z0-9-]+', t):
                            raise ValueError('invalid theme')
                        prefs['theme'] = t
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
                    if 'ai_provider' in data:
                        ap = str(data['ai_provider']).strip().lower()
                        if ap not in ('openai', 'anthropic', 'gemini', 'openrouter', 'custom', 'subscription'):
                            raise ValueError('invalid ai_provider')
                        prefs['ai_provider'] = ap
                    if 'ai_sub_cli' in data:
                        sc = str(data['ai_sub_cli']).strip().lower()
                        if sc in ('opencode', 'codex', 'claude', 'gemini'):
                            prefs['ai_sub_cli'] = sc
                    if 'ai_thinking' in data:
                        at = str(data['ai_thinking']).strip().lower()
                        if at not in ('auto', 'low', 'medium', 'high'):
                            raise ValueError('invalid ai_thinking')
                        prefs['ai_thinking'] = at
                    if 'ai_base_url' in data:
                        prefs['ai_base_url'] = str(data['ai_base_url']).strip()[:300]
                    if 'ai_selected_models' in data:
                        sm = data['ai_selected_models']
                        if not isinstance(sm, dict):
                            raise ValueError('ai_selected_models must be an object')
                        cur = prefs.setdefault('ai_selected_models', {})
                        for k, v in sm.items():
                            kp = str(k).strip().lower()
                            if kp in ('openai', 'anthropic', 'gemini', 'openrouter', 'custom', 'subscription',
                                      'subscription:opencode', 'subscription:codex', 'subscription:claude', 'subscription:gemini') and isinstance(v, str):
                                if v.strip():
                                    cur[kp] = v.strip()[:200]
                                else:
                                    cur.pop(kp, None)
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


def desktop_server(engine, grace, startup_timeout):
    # A desktop launch must reconnect to the worker that owns an active job.
    # The OS releases the lock on exit, including after a crash.
    key = engine.catalog_key
    engine.data.mkdir(parents=True, exist_ok=True)
    lock = (engine.data / f'desktop-{key}.lock').open('a+b')
    endpoint = engine.data / f'desktop-{key}.json'
    deadline = time.monotonic() + 8
    try:
        while True:
            try:
                if fcntl is not None:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                else:
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except (BlockingIOError, PermissionError):
                try:
                    record = json.loads(endpoint.read_text())
                    origin = f"http://127.0.0.1:{int(record['port'])}"
                    with urllib.request.urlopen(origin + '/api/instance', timeout=.5) as response:
                        if json.load(response)['instance'] == record['instance']:
                            lock.close()
                            return None, origin, None
                except (OSError, ValueError, KeyError):
                    pass
                if time.monotonic() >= deadline:
                    raise ValueError('The running launcher did not respond when reopening its window')
                time.sleep(.1)
                continue
            server = Server(engine, 0, grace, startup_timeout)
            atomic_json(endpoint, {'instance': server.instance_id, 'port': server.server_port})
            return server, server.origin, lock
    except BaseException:
        lock.close()
        raise


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
        grace = max(.1, args.grace)
        startup_timeout = max(.1, args.startup_timeout)
        desktop_lock = None
        if args.no_browser or args.port:
            server = Server(engine, args.port, grace, startup_timeout)
            origin = server.origin
        else:
            server, origin, desktop_lock = desktop_server(engine, grace, startup_timeout)
    except (OSError, ValueError) as e:
        parser.exit(1, f'Armin Launcher: {e}\n')
    print(origin, flush=True)
    if not args.no_browser:
        ensure_home_menu_shortcut()
        browser = find_browser()
        if browser:
            kw = {'creationflags': subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP} if IS_WIN else {'start_new_session': True}
            argv = [browser, '--app=' + origin] + ([] if IS_WIN else ['--class=LaunchCraft'])
            subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
        elif IS_WIN:
            webbrowser.open(origin)
        else:
            if server:
                server.server_close()
            parser.exit(1, 'Armin Launcher: install a Chromium browser or use --no-browser\n')
    if server is None:
        return 0

    def stop(signum, frame):
        engine.cancel.set()
        engine.cancel_ai()
        server.stopping.set()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.run()
    finally:
        if desktop_lock:
            desktop_lock.close()
    if engine.worker:
        engine.worker.join(timeout=.5 if engine.worker.daemon else None)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
