#!/usr/bin/env python3
"""Optional headless Chromium UI smoke check, driven through stdlib-only CDP.
Never opens a visible window and edits only a temporary copy of the catalog.
"""
import base64
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from launcher import atomic_json


class CDP:
    def __init__(self, url):
        from urllib.parse import urlsplit
        u = urlsplit(url)
        self.sock = socket.create_connection((u.hostname, u.port), timeout=10)
        self.sock.settimeout(15)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall(f'GET {u.path} HTTP/1.1\r\nHost: {u.netloc}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n'.encode())
        header = b''
        while not header.endswith(b'\r\n\r\n'):
            header += self.sock.recv(1)
        assert header.startswith(b'HTTP/1.1 101 '), header
        self.seq = 0
        self.errors = []

    def read(self, size):
        data = b''
        while len(data) < size:
            chunk = self.sock.recv(size - len(data))
            if not chunk:
                raise EOFError('CDP disconnected')
            data += chunk
        return data

    def send(self, data, opcode=1):
        body = data.encode() if isinstance(data, str) else data
        mask = os.urandom(4)
        length = len(body)
        prefix = bytes([0x80 | opcode])
        prefix += bytes([0x80 | length]) if length < 126 else bytes([0x80 | 126]) + struct.pack('!H', length) if length < 65536 else bytes([0x80 | 127]) + struct.pack('!Q', length)
        self.sock.sendall(prefix + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(body)))

    def call(self, method, params=None):
        self.seq += 1
        self.send(json.dumps(dict(id=self.seq, method=method, params=params or {})))
        while True:
            a, b = self.read(2)
            length = b & 127
            if length == 126:
                length = struct.unpack('!H', self.read(2))[0]
            elif length == 127:
                length = struct.unpack('!Q', self.read(8))[0]
            mask = self.read(4) if b & 128 else None
            body = self.read(length)
            if mask:
                body = bytes(v ^ mask[i % 4] for i, v in enumerate(body))
            if a & 15 == 9:
                self.send(body, 10)
                continue
            if a & 15 != 1:
                continue
            message = json.loads(body)
            if message.get('method') == 'Runtime.exceptionThrown':
                self.errors.append(message['params'])
            if message.get('id') == self.seq:
                if 'error' in message:
                    raise RuntimeError(message['error'])
                return message.get('result', {})

    def evaluate(self, expression):
        result = self.call('Runtime.evaluate', dict(expression=expression, returnByValue=True, awaitPromise=True))
        if 'exceptionDetails' in result:
            raise RuntimeError(result['exceptionDetails'])
        return result['result'].get('value')

    def until(self, expression):
        for _ in range(100):
            if self.evaluate(expression):
                return
            time.sleep(.05)
        raise AssertionError('Timed out waiting for ' + expression)


def main():
    chromium = shutil.which('chromium') or shutil.which('chromium-browser')
    if not chromium:
        raise SystemExit('Chromium not installed')
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix='launchcraft-ui-'))
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='launchcraft-browser-') as tmp:
        home = Path(tmp)
        catalog = home / 'catalog.json'
        shutil.copyfile(ROOT / 'catalog.json', catalog)
        initial = json.loads(catalog.read_text())
        env = dict(os.environ, HOME=tmp)
        server = subprocess.Popen([sys.executable, str(ROOT / 'launcher.py'), '--no-browser', '--catalog', str(catalog), '--startup-timeout', '30', '--grace', '.3'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        browser = None
        try:
            url = server.stdout.readline().strip()
            assert url.startswith('http://127.0.0.1:'), url
            profile = home / 'chromium'
            browser = subprocess.Popen([chromium, '--headless', '--disable-gpu', '--no-first-run', '--no-default-browser-check', '--disable-background-networking', '--disable-component-update', '--disable-sync', '--disable-extensions', '--password-store=basic', '--remote-debugging-port=0', '--user-data-dir=' + str(profile), '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1', url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            for _ in range(100):
                if (profile / 'DevToolsActivePort').exists():
                    break
                time.sleep(.1)
            port = (profile / 'DevToolsActivePort').read_text().splitlines()[0]
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/json') as response:
                tabs = json.load(response)
            tab = next(t for t in tabs if t['type'] == 'page')
            cdp = CDP(tab['webSocketDebuggerUrl'])
            cdp.call('Runtime.enable')
            cdp.call('Page.enable')
            cdp.until("document.querySelectorAll('.card').length > 0 && typeof token !== 'undefined' && token.length > 0")
            def click(selector):
                cdp.evaluate(f'document.querySelector({json.dumps(selector)}).click()')
            cdp.call('Emulation.setDeviceMetricsOverride', dict(width=1440, height=1100, deviceScaleFactor=1, mobile=False))
            cdp.until("document.querySelector('#counts strong')?.textContent !== undefined")
            assert cdp.evaluate("currentTheme") == 'catppuccin'
            for theme_id in ('default', 'light'):
                cdp.evaluate(f"applyTheme('{theme_id}', false, false)")
                assert cdp.evaluate("document.querySelector('#update-all').disabled")
                colors = cdp.evaluate("(() => {const s = getComputedStyle(document.querySelector('#update-all')); return [s.backgroundColor, s.color, s.opacity];})()")
                assert colors == (['rgb(231, 230, 226)', 'rgb(98, 99, 108)', '1'] if theme_id == 'light' else ['rgb(6, 6, 7)', 'rgb(147, 148, 157)', '1']), colors
            cdp.evaluate("applyTheme('catppuccin', false, false); window.smokeState = state; state = {...state, apps: state.apps.map((a,i) => i ? a : {...a, update:true, latest:'v-test'})}; render()")
            assert cdp.evaluate("!document.querySelector('#update-all').disabled")
            cdp.until("getComputedStyle(document.querySelector('#update-all')).backgroundColor === 'rgb(216, 181, 255)'")
            assert cdp.evaluate("getComputedStyle(document.querySelector('#update-all')).backgroundColor") == 'rgb(216, 181, 255)'
            assert cdp.evaluate("getComputedStyle(document.querySelector('#update-all')).color") == 'rgb(255, 255, 255)'
            cdp.evaluate("state = window.smokeState; delete window.smokeState; render()")
            assert cdp.evaluate("document.querySelectorAll('.card').length") == len([a for a in initial['apps'] if not a['hidden']])
            cdp.evaluate("document.querySelector('#search').value='no-such-application'; document.querySelector('#search').dispatchEvent(new Event('input'))")
            assert cdp.evaluate("!document.querySelector('#empty').hidden")
            cdp.evaluate("document.querySelector('#search').value=''; document.querySelector('#search').dispatchEvent(new Event('input'))")
            click('#list-view')
            assert cdp.evaluate("document.querySelector('#apps').className === 'list' && !!document.querySelector('.table-head')")
            screenshot = cdp.call('Page.captureScreenshot', dict(format='png', captureBeyondViewport=False))
            (output / 'list.png').write_bytes(base64.b64decode(screenshot['data']))
            click('#grid-view')
            click('#theme')
            click('[data-theme-id=vscode-light]')
            assert cdp.evaluate("document.body.classList.contains('light')")
            click('#theme')
            click('[data-theme-id=default]')
            for key, code, modifiers, expected in [('+','Equal',2,1.1), ('-','Minus',2,1), ('=','Equal',4,1.1), ('0','Digit0',4,1)]:
                result = cdp.evaluate(f"(() => {{const e = new KeyboardEvent('keydown',{{key:{json.dumps(key)},code:{json.dumps(code)},ctrlKey:{str(modifiers == 2).lower()},metaKey:{str(modifiers == 4).lower()},cancelable:true}}); document.dispatchEvent(e); return [e.defaultPrevented, zoom];}})()")
                assert result == [True, expected], result
            click('#zoom-in')
            assert cdp.evaluate('zoom') == 1.1
            click('#zoom-reset')
            cdp.evaluate('applyZoom(8)')
            assert cdp.evaluate('zoom') == 1.75
            cdp.evaluate('applyZoom(-8)')
            assert cdp.evaluate('zoom') == .75
            click('#zoom-reset')
            # Exercise the real Add App modal/API against the temporary catalog.
            cdp.call('Emulation.setDeviceMetricsOverride', dict(width=1360, height=860, deviceScaleFactor=1, mobile=False))
            click('#add')
            for light in (False, True):
                cdp.evaluate(f"document.body.classList.toggle('light', {str(light).lower()})")
                for scale in (.8, 1, 1.2):
                    cdp.evaluate(f'applyZoom({scale})')
                    geometry = cdp.evaluate("""(() => {
                        const modal = document.querySelector('#modal');
                        const fields = document.querySelector('#add-form .form-fields');
                        const button = document.querySelector('#add-form button[type=submit]');
                        const before = button.getBoundingClientRect();
                        fields.scrollTop = fields.scrollHeight;
                        const after = button.getBoundingClientRect();
                        const hit = document.elementFromPoint(after.x + after.width / 2, after.y + after.height / 2);
                        fields.scrollTop = 0;
                        return {visible: after.top >= 0 && after.bottom <= innerHeight && hit === button,
                            pinned: Math.abs(before.y - after.y) < 1,
                            modalScroll: modal.scrollHeight - modal.clientHeight};
                    })()""")
                    assert geometry['visible'] and geometry['pinned'] and geometry['modalScroll'] <= 1, geometry
                cdp.evaluate('applyZoom(1)')
                screenshot = cdp.call('Page.captureScreenshot', dict(format='png', captureBeyondViewport=False))
                (output / ('add-light.png' if light else 'add-dark.png')).write_bytes(base64.b64decode(screenshot['data']))
            cdp.evaluate("document.body.classList.remove('light')")
            cdp.evaluate("Object.entries({name:'Browser Test',id:'browser-test',publisher:'QA',category:'Tools',tagline:'Added through the modal',website:'https://example.com',repo:'example/test',asset_pattern:'test.AppImage',target:'test.AppImage',launch:'test'}).forEach(([key,value]) => document.querySelector('#add-form').elements[key].value=value); document.querySelector('#add-form').requestSubmit()")
            cdp.until("!document.querySelector('#modal').open && state.apps.some(a=>a.id==='browser-test')")
            assert len(json.loads(catalog.read_text())['apps']) == len(initial['apps']) + 1
            cdp.evaluate("api('catalog',{op:'hide',id:'browser-test',hidden:true})")
            click('[data-filter=hidden]')
            cdp.until("!!document.querySelector('[data-id=browser-test]')")
            click('[data-id=browser-test] [data-action=menu]')
            click('[data-id=browser-test] [data-action=details]')
            assert cdp.evaluate("document.querySelector('#modal-title').textContent") == 'Browser Test'
            click('#modal-close')
            click('[data-filter=all]')
            screenshot = cdp.call('Page.captureScreenshot', dict(format='png', captureBeyondViewport=False))
            (output / 'grid.png').write_bytes(base64.b64decode(screenshot['data']))
            cdp.call('Emulation.setDeviceMetricsOverride', dict(width=520, height=900, deviceScaleFactor=1, mobile=False))
            assert cdp.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'mobile layout overflow'
            screenshot = cdp.call('Page.captureScreenshot', dict(format='png', captureBeyondViewport=False))
            (output / 'mobile.png').write_bytes(base64.b64decode(screenshot['data']))
            assert not cdp.errors, cdp.errors
            cdp.call('Page.navigate', dict(url='about:blank'))
            server.wait(timeout=6)
            assert server.returncode == 0, server.stderr.read()
            try:
                cdp.call('Browser.close')
            except (EOFError, OSError):
                pass
            cdp.sock.close()
            browser.wait(timeout=10)
            print(f'Headless Chromium smoke passed. Screenshots: {output}')
        finally:
            if browser and browser.poll() is None:
                os.killpg(browser.pid, signal.SIGTERM)
                try:
                    browser.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(browser.pid, signal.SIGKILL)
                    browser.wait()
            if server.poll() is None:
                server.terminate()
                server.wait(timeout=10)
            server.stdout.close()
            server.stderr.close()


if __name__ == '__main__':
    main()
