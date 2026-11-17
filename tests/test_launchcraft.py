"""Isolated tests: temporary catalogs/homes, loopback HTTP only, no actual installs."""
import contextlib
import copy
import hashlib
import http.client
import http.server
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from launcher import Catalog, Engine, Server, Cancelled, atomic_json, validate_catalog

APP = dict(id='sample', name='Sample', publisher='Example', category='Tools',
           tagline='A test application', accent='#2d81ff', website='https://example.com',
           source=dict(type='github_release', repo='example/sample', asset_pattern='sample.AppImage'),
           install=dict(type='appimage', binary_name='sample.AppImage', launch='sample'), hidden=False)
PAYLOAD = b'LaunchCraft mock artifact\n' * 20000
SHA = hashlib.sha256(PAYLOAD).hexdigest()


class MockHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_HEAD(self):
        if self.path.endswith('/releases/latest'):
            self.send_response(302)
            self.send_header('Location', self.server.url + '/example/sample/releases/tag/v2.0')
        else:
            self.send_response(200)
        self.end_headers()

    def do_GET(self):
        self.server.requests.append((self.path, dict(self.headers)))
        if self.path.startswith('/repos/'):
            if self.server.rate_limit:
                self.send_error(429)
                return
            if self.headers.get('If-None-Match') == '"test-etag"':
                self.send_response(304)
                self.end_headers()
                return
            assets = [dict(name='sample.AppImage', browser_download_url=self.server.url + '/artifact', size=len(PAYLOAD), digest='sha256:' + SHA),
                      dict(name='SHA256SUMS.txt', browser_download_url=self.server.url + '/sums')]
            body = json.dumps(dict(tag_name='v2.0', assets=assets, body='Test release', html_url='https://example.com/release')).encode()
            self.send_response(200)
            self.send_header('ETag', '"test-etag"')
        elif self.path == '/sums':
            body = (SHA + '  sample.AppImage\n').encode()
            self.send_response(200)
        else:
            offset = 0 if self.server.ignore_range else int(self.headers.get('Range', 'bytes=0-').split('=')[1].split('-')[0])
            body = PAYLOAD[offset:]
            self.send_response(206 if offset else 200)
            if offset:
                self.send_header('Content-Range', f'bytes {offset}-{len(PAYLOAD)-1}/{len(PAYLOAD)}')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.catalog = self.home / 'catalog.json'
        atomic_json(self.catalog, dict(version=1, apps=[copy.deepcopy(APP)]))

    def engine(self, url=None):
        return Engine(self.catalog, home=self.home, **(dict(api_base=url, web_base=url) if url else {}))

    @contextlib.contextmanager
    def mock_http(self):
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), MockHandler)
        server.url = f'http://127.0.0.1:{server.server_port}'
        server.requests = []
        server.rate_limit = False
        server.ignore_range = False
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    @contextlib.contextmanager
    def app_server(self, grace=.25):
        server = Server(self.engine(), grace=grace, startup_timeout=2)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        try:
            yield server, thread
        finally:
            server.stopping.set()
            thread.join(4)
            self.assertFalse(thread.is_alive(), 'server did not stop')


class CatalogTests(Fixture):
    def test_valid_and_invalid(self):
        good = Catalog(self.catalog).load()
        self.assertEqual(validate_catalog(good), good)
        changes = [lambda d:d.update(version=True), lambda d:d['apps'].append(copy.deepcopy(APP)),
                   lambda d:d['apps'][0].update(id='../escape'), lambda d:d['apps'][0].update(hidden=1),
                   lambda d:d['apps'][0]['install'].update(binary_name='../bad'),
                   lambda d:d['apps'][0]['source'].update(repo='bad'),
                   lambda d:d['apps'][0].update(accent='red'),
                   lambda d:d['apps'][0]['install'].update(type='pacman')]
        for change in changes:
            with self.subTest(change=change):
                value = copy.deepcopy(good)
                change(value)
                with self.assertRaises(ValueError):
                    validate_catalog(value)

    def test_atomic_edit_and_invalid_preserves_file(self):
        cat = Catalog(self.catalog)
        cat.mutate(lambda d:d['apps'][0].update(hidden=True))
        before = self.catalog.read_bytes()
        with self.assertRaises(ValueError):
            cat.mutate(lambda d:d['apps'].append(copy.deepcopy(APP)))
        self.assertEqual(self.catalog.read_bytes(), before)
        self.assertTrue(cat.load()['apps'][0]['hidden'])

    def test_cli_lifecycle(self):
        ctl = Path(__file__).resolve().parents[1] / 'launchcraft-ctl'
        def run(*args, body=None):
            result = subprocess.run([sys.executable, str(ctl), '--catalog', str(self.catalog), *args], input=body, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout
        self.assertIn('Valid catalog', run('validate'))
        self.assertIn('sample', run('list'))
        new = copy.deepcopy(APP)
        new['id'] = 'second'
        run('add', body=json.dumps(new))
        run('edit', 'second', body='{"hidden":true}')
        self.assertEqual(len(Catalog(self.catalog).load()['apps']), 2)
        run('remove', 'second')
        self.assertEqual(len(Catalog(self.catalog).load()['apps']), 1)

    def test_runtime_reload(self):
        engine = self.engine()
        Catalog(self.catalog).mutate(lambda d:d['apps'][0].update(name='Changed externally'))
        self.assertEqual(engine.snapshot()['apps'][0]['name'], 'Changed externally')


class DownloadTests(Fixture):
    def test_etag_is_persisted_and_reused(self):
        with self.mock_http() as server:
            engine = self.engine(server.url)
            one = engine.github_release(APP)
            engine.save()
            two = self.engine(server.url).github_release(APP)
            self.assertEqual(one['tag'], two['tag'])
            self.assertEqual(server.requests[-1][1].get('If-None-Match'), '"test-etag"')
            self.assertIn('test-etag', engine.state_path.read_text())

    def test_rate_limit_head_fallback(self):
        with self.mock_http() as server:
            engine = self.engine(server.url)
            server.rate_limit = True
            release = engine.github_release(APP)
            self.assertEqual(release['tag'], 'v2.0')
            self.assertIn('rate limited', release['warning'])
            self.assertIn('/releases/download/v2.0/', release['asset']['browser_download_url'])

    def test_range_resume_and_digest(self):
        with self.mock_http() as server:
            engine = self.engine(server.url)
            asset = engine.github_release(APP)['asset']
            folder = engine.downloads
            folder.mkdir(parents=True)
            (folder / 'sample.AppImage.part').write_bytes(PAYLOAD[:12345])
            path, verification = engine.download(asset)
            self.assertEqual(path.read_bytes(), PAYLOAD)
            self.assertEqual(verification, 'SHA-256 verified')
            self.assertEqual(server.requests[-1][1].get('Range'), 'bytes=12345-')
            self.assertFalse(path.with_name(path.name + '.part').exists())
            count = len(server.requests)
            self.assertEqual(engine.download(asset)[0], path)
            self.assertEqual(len(server.requests), count, 'verified cached artifacts should be reused')

    def test_range_ignored_restarts_cleanly_and_sends_validator(self):
        with self.mock_http() as server:
            engine = self.engine(server.url)
            asset = engine.github_release(APP)['asset']
            engine.downloads.mkdir(parents=True)
            (engine.downloads / 'sample.AppImage.part').write_bytes(PAYLOAD[:300])
            atomic_json(engine.downloads / 'sample.AppImage.source.json', {'url':asset['browser_download_url'], 'validator':'"old-etag"'})
            server.ignore_range = True
            path, verification = engine.download(asset)
            self.assertEqual(path.read_bytes(), PAYLOAD)
            self.assertEqual(server.requests[-1][1].get('If-Range'), '"old-etag"')

    def test_same_filename_new_url_does_not_resume_old_release(self):
        with self.mock_http() as server:
            engine = self.engine(server.url)
            asset = engine.github_release(APP)['asset']
            engine.downloads.mkdir(parents=True)
            (engine.downloads / 'sample.AppImage.part').write_bytes(b'old data')
            atomic_json(engine.downloads / 'sample.AppImage.source.json', {'url':'https://example.com/old-version'})
            path, _ = engine.download(asset)
            self.assertEqual(path.read_bytes(), PAYLOAD)
            self.assertNotIn('Range', server.requests[-1][1])

    def test_no_publisher_checksum_is_labeled(self):
        with self.mock_http() as server:
            engine = self.engine(server.url)
            asset = engine.github_release(APP)['asset']
            asset.pop('digest')
            path, verification = engine.download(asset)
            self.assertEqual(path.read_bytes(), PAYLOAD)
            self.assertIn('No publisher checksum', verification)
            self.assertIn(SHA, verification)

    def test_sha256sums_and_mismatch(self):
        with self.mock_http() as server:
            engine = self.engine(server.url)
            release = engine.github_release(APP)
            asset = release['asset']
            asset.pop('digest')
            path, verification = engine.download(asset, release['checksum'])
            self.assertEqual(verification, 'SHA-256 verified')
            asset['digest'] = 'sha256:' + '0' * 64
            with self.assertRaisesRegex(ValueError, 'mismatch'):
                engine.download(asset)
            self.assertFalse(path.exists())
            self.assertFalse(path.with_name(path.name + '.part').exists())

    def test_cancel_preserves_partial(self):
        with self.mock_http() as server:
            engine = self.engine(server.url)
            asset = engine.github_release(APP)['asset']
            engine.cancel.set()
            with self.assertRaises(Cancelled):
                engine.download(asset)
            self.assertTrue(list(engine.downloads.rglob('*.part')))


class InstallTests(Fixture):
    def test_update_all_one_pacman_invocation(self):
        apps = []
        for i in range(3):
            app = copy.deepcopy(APP)
            app.update(id=f'app-{i}')
            app['install'] = dict(type='pacman_pkg', package=f'app-{i}', launch=f'app-{i}')
            apps.append(app)
        atomic_json(self.catalog, dict(version=1, apps=apps))
        engine = self.engine()
        for a in apps:
            engine.state['releases'][a['id']] = dict(tag='v2', asset={'name':a['id'], 'browser_download_url':'mock'})
        with patch.object(engine, 'installed', return_value='v1'), patch.object(engine, 'download', side_effect=lambda a,*_: (self.home / a['name'], 'SHA-256 verified')), patch.object(engine, 'transaction') as transaction:
            engine.install_many()
        transaction.assert_called_once()
        argv = transaction.call_args.args[0]
        self.assertEqual(argv[:5], ['pkexec', 'pacman', '-U', '--noconfirm', str(self.home / 'app-0')])
        self.assertEqual(len(argv), 7)

    def test_tarball_atomic_current_and_traversal(self):
        engine = self.engine()
        app = copy.deepcopy(APP)
        app['install'] = dict(type='tarball', bin='sample/bin/app', launch='app')
        archive = self.home / 'release.tar.gz'
        def build(name):
            with tarfile.open(archive, 'w:gz') as tar:
                member = tarfile.TarInfo(name)
                member.size = 3
                tar.addfile(member, io.BytesIO(b'bin'))
        build('sample/bin/app')
        target = engine.install_tarball(app, archive, 'v2.0')
        self.assertTrue(target.is_file())
        self.assertTrue((engine.data / 'apps/sample/current').is_symlink())
        self.assertTrue(os.access(target, os.X_OK))
        build('../../escape')
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            engine.install_tarball(app, archive, 'v3')
        self.assertFalse((self.home / 'escape').exists())
        self.assertEqual(target.read_bytes(), b'bin')

    def test_appimage_install_desktop_detect_open_uninstall(self):
        engine = self.engine()
        artifact = self.home / 'sample.AppImage'
        artifact.write_bytes(b'not executable during test')
        engine.state['releases']['sample'] = dict(tag='v2', asset={"name":"sample.AppImage"})
        with patch.object(engine, 'download', return_value=(artifact, 'SHA-256 verified')):
            engine.install_many(['sample'])
        target = self.home / 'Applications/sample.AppImage'
        self.assertEqual(engine.installed(APP), 'v2')
        self.assertTrue(os.access(target, os.X_OK))
        desktop = self.home / '.local/share/applications/launchcraft-sample.desktop'
        self.assertIn(str(target), desktop.read_text())
        with patch('launcher.subprocess.Popen') as popen:
            engine.open_app('sample')
            self.assertEqual(popen.call_args.args[0], [str(target)])
        engine.uninstall('sample')
        self.assertFalse(target.exists())
        self.assertFalse(desktop.exists())
        self.assertIsNone(engine.installed(APP))

    def test_package_updates_are_clean_and_scoped(self):
        app = copy.deepcopy(APP)
        app['source'] = dict(type='arch_repo', package='sample')
        app['install'] = dict(type='pacman', package='sample', launch='sample')
        atomic_json(self.catalog, dict(version=1, apps=[app]))
        engine = self.engine()
        def command(argv, **kwargs):
            output = 'sample 1.0 -> 2.0\nother 1 -> 3\n' if '-Qu' in argv else 'sample 1.0\n'
            return subprocess.CompletedProcess(argv, 0, output, '')
        with patch.object(engine, 'command', side_effect=command), patch('launcher.shutil.which', return_value='/mock/pacman'):
            engine.refresh()
        self.assertEqual(engine.state['releases']['sample']['tag'], '2.0')
        self.assertEqual(engine.warnings, [])


class ServerTests(Fixture):
    def sse(self, server):
        sock = socket.create_connection(('127.0.0.1', server.server_port))
        sock.settimeout(2)
        sock.sendall(f'GET /events HTTP/1.1\r\nHost: 127.0.0.1:{server.server_port}\r\n\r\n'.encode())
        content = b''
        while b'event: connected' not in content:
            content += sock.recv(4096)
        return sock

    def request(self, server, path, data=None, token=None, origin=None):
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
        headers = {}
        if token:
            headers['X-LaunchCraft-Token'] = token
        if origin:
            headers['Origin'] = origin
        if data is not None:
            headers['Content-Type'] = 'application/json'
        conn.request('POST' if data is not None else 'GET', path, body=json.dumps(data) if data is not None else None, headers=headers)
        response = conn.getresponse()
        body = response.read()
        status = response.status
        conn.close()
        return status, json.loads(body)

    def test_sse_events_and_auto_shutdown_after_all_clients_disconnect(self):
        with self.app_server() as (server, thread):
            one, two = self.sse(server), self.sse(server)
            server.engine.emit('progress', {'id':'sample', 'percent':42})
            self.assertIn(b'"percent": 42', one.recv(4096))
            one.close()
            time.sleep(.8)
            self.assertTrue(thread.is_alive(), 'second client must keep server running')
            two.close()
            thread.join(3)
            self.assertFalse(thread.is_alive(), 'last disconnect must stop the server')

    def test_active_job_defers_shutdown(self):
        with self.app_server() as (server, thread):
            client = self.sse(server)
            server.engine.busy = True
            client.close()
            time.sleep(1.2)
            self.assertTrue(thread.is_alive())
            server.engine.busy = False
            thread.join(3)
            self.assertFalse(thread.is_alive())

    def test_refresh_does_not_hold_server_open(self):
        with self.app_server() as (server, thread):
            client = self.sse(server)
            server.engine.busy = True
            server.engine.refreshing = True
            client.close()
            thread.join(3)
            self.assertFalse(thread.is_alive())
            self.assertTrue(server.engine.cancel.is_set())

    def test_state_api_catalog_and_origin_protection(self):
        with self.app_server() as (server, thread):
            status, data = self.request(server, '/api/state')
            self.assertEqual(status, 200)
            self.assertIn('token', data)
            self.assertEqual(self.request(server, '/api/catalog', dict(op='hide', id='sample', hidden=True))[0], 403)
            self.assertEqual(self.request(server, '/api/catalog', dict(op='hide', id='sample', hidden=True), data['token'], 'https://evil.example')[0], 403)
            status, data = self.request(server, '/api/catalog', dict(op='hide', id='sample', hidden=True), server.token)
            self.assertEqual(status, 200)
            self.assertTrue(data['apps'][0]['hidden'])

    def test_no_browser_subprocess_and_startup_timeout(self):
        script = Path(__file__).resolve().parents[1] / 'launcher.py'
        env = dict(os.environ, HOME=str(self.home))
        with subprocess.Popen([sys.executable, str(script), '--headless-server', '--catalog', str(self.catalog), '--startup-timeout', '.3'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env) as proc:
            url = proc.stdout.readline().strip()
            self.assertRegex(url, r'^http://127.0.0.1:\d+$')
            _, err = proc.communicate(timeout=5)
            self.assertEqual(proc.returncode, 0, err)


if __name__ == '__main__':
    unittest.main()
