"""Background AI lifecycle tests use temporary homes and loopback providers."""
import http.client
import io
import json
import sys
import threading
import time
from unittest.mock import patch

from launcher import Catalog, atomic_json, desktop_server
from tests.test_launchcraft import Fixture


class AiBackgroundTests(Fixture):
    def test_cli_drains_output_while_sending_large_prompt(self):
        engine = self.engine('http://127.0.0.1')
        script = (
            "import sys,time; sys.stderr.write('x' * 256000); sys.stderr.flush(); "
            "time.sleep(.35); print(len(sys.stdin.read()))"
        )
        rc, out, err = engine._run_cancellable_cli(
            [sys.executable, '-c', script], stdin_text='p' * 256000, timeout=5)
        self.assertEqual((rc, out.strip(), len(err)), (0, '256000', 256000))
        self.assertIsNone(engine.ai_proc)

    def test_stopped_http_reply_does_not_replace_next_result(self):
        engine = self.engine('http://127.0.0.1')
        entered, release, finished = (threading.Event() for _ in range(3))

        def delayed_response(*args, **kwargs):
            entered.set()
            release.wait(5)
            finished.set()
            return io.BytesIO(json.dumps({'choices': [{'message': {'content': '{"reply":"late"}'}}]}).encode())

        def wait_for_idle():
            deadline = time.monotonic() + 2
            while engine.ai_running and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertFalse(engine.ai_running)

        with patch('launcher.ROOT', self.home), patch('urllib.request.urlopen', side_effect=delayed_response):
            try:
                engine.terminal_exec('first question', provider='custom', base_url='http://127.0.0.1')
                self.assertTrue(entered.wait(2))
                engine.cancel_ai()
                wait_for_idle()
                self.assertEqual(engine.ai_outcome, 'cancelled')
                engine.terminal_exec('!echo next')
                wait_for_idle()
                release.set()
                self.assertTrue(finished.wait(1))
            finally:
                release.set()
        self.assertEqual(engine.ai_outcome, 'complete')
        self.assertTrue(engine.ai_report.endswith('next'))
        self.assertNotIn('late', engine.ai_report)
        reopened = self.engine('http://127.0.0.1')
        self.assertEqual(reopened.ai_report, engine.ai_report)

    def test_desktop_reattaches_to_active_job_after_window_disconnect(self):
        engine = self.engine('http://127.0.0.1')
        server, origin, lock = desktop_server(engine, .1, .1)
        self.addCleanup(lock.close)
        server.ever_connected = True
        engine._begin_ai('Checking catalog')
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        try:
            time.sleep(.45)
            self.assertFalse(server.stopping.is_set())
            attached, same_origin, other_lock = desktop_server(self.engine('http://127.0.0.1'), .1, .1)
            self.assertIsNone(attached)
            self.assertIsNone(other_lock)
            self.assertEqual(same_origin, origin)
            engine._finish_ai('complete')
            thread.join(2)
            self.assertFalse(thread.is_alive())
        finally:
            server.stopping.set()
            thread.join(2)

    def test_custom_audit_changes_only_selected_catalog_and_preserves_concurrent_edit(self):
        engine = self.engine('http://127.0.0.1')
        bundled = self.home / 'bundled'
        bundled_catalog = bundled / 'catalog.json'
        atomic_json(bundled_catalog, {'version': 1, 'apps': []})
        engine.request = lambda *args: io.BytesIO(b'{}')
        plan = {'linux_updates': [{'id': 'sample', 'tagline': 'reviewed'}],
                'summary': 'Reviewed sample', 'assets': [{'id': 'sample', 'icon_url': 'unused'}]}
        def run():
            engine.ai_maintain(provider='custom', base_url='http://127.0.0.1')
            deadline = time.monotonic() + 3
            while engine.ai_running and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertFalse(engine.ai_running)

        with patch('launcher.ROOT', bundled):
            with patch.object(engine, 'call_ai_provider', return_value=plan):
                run()
            self.assertEqual(engine.ai_outcome, 'complete', engine.ai_report)
            self.assertEqual(engine.catalog.load()['apps'][0]['tagline'], 'reviewed')
            self.assertEqual(Catalog(bundled_catalog).load()['apps'], [])
            self.assertFalse((bundled / 'ui').exists())

            def edit_then_reply(*args, **kwargs):
                engine.catalog.mutate(lambda data: data['apps'][0].update(tagline='my edit'))
                plan['linux_updates'][0]['tagline'] = 'second review'
                return plan

            with patch.object(engine, 'call_ai_provider', side_effect=edit_then_reply):
                run()
            self.assertEqual(engine.ai_outcome, 'error')
            self.assertIn('changed during the audit', engine.ai_report)
            self.assertEqual(engine.catalog.load()['apps'][0]['tagline'], 'my edit')

    def test_model_lookup_does_not_select_or_save_credentials(self):
        with self.app_server() as (server, _):
            engine = server.engine
            first = engine.save_ai_key('openai', 'first-test-key')
            second = engine.save_ai_key('openai', 'second-test-key')
            def lookup(payload):
                with patch.object(engine, 'fetch_ai_models', return_value=['example']) as fetch:
                    conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=2)
                    try:
                        conn.request('POST', '/api/ai_models', body=json.dumps(payload),
                                     headers={'X-LaunchCraft-Token': server.token, 'Content-Type': 'application/json'})
                        response = conn.getresponse()
                        self.assertEqual(response.status, 200, response.read())
                        return fetch.call_args.args[1]
                    finally:
                        conn.close()
            self.assertEqual(lookup({'provider': 'openai', 'key_id': first}), 'first-test-key')
            self.assertEqual(lookup({'provider': 'openai', 'api_key': 'unsaved-test-key'}), 'unsaved-test-key')
            self.assertEqual(engine.active_ai_key_id('openai'), second)
            self.assertEqual(len(engine.public_ai_keys('openai')), 2)
