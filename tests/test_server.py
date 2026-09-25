"""The receiver end to end: a real socket, a signed request, a fake Telegram."""
import http.client
import json
import time
import unittest

from bot import signing
from bot.config import Settings
from bot.delivery import Worker
from bot.server import MAX_BODY, Server
from tests.fakes import FakeClient

SECRET = 'shared-secret'
PANEL = 'https://graphix.uz/uz/boshqaruv/buyurtmalar/GX-260916-0001/'


class ServerTests(unittest.TestCase):
    """Spin the server up on an ephemeral port for each test."""

    def setUp(self):
        self.settings = Settings(token='t', chat_id='-100', secret=SECRET, bind_port=0)
        self.client = FakeClient()
        self.worker = Worker(self.client, '-100', sleep=lambda s: None)
        self.worker.start()
        self.server = Server(self.settings, self.worker)
        import threading
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def post(self, body, *, path='/graphix/events', headers=None, sign=True, timestamp=None):
        """POST ``body`` the way the site does, unless a test says otherwise."""
        if isinstance(body, dict):
            body = json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        ts = str(int(time.time()) if timestamp is None else timestamp)
        sent = {'Content-Type': 'application/json; charset=utf-8',
                'User-Agent': 'GRAPHIX-webhook/1',
                'X-Webhook-Event': 'order.paid',
                'X-Webhook-Timestamp': ts,
                'X-Webhook-Secret': SECRET}
        if sign:
            sent['X-Webhook-Signature'] = signing.signature(SECRET, ts, body)
        sent.update(headers or {})
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        conn.request('POST', path, body=body, headers=sent)
        response = conn.getresponse()
        data = response.read().decode()
        conn.close()
        return response.status, data

    def get(self, path):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        conn.request('GET', path)
        response = conn.getresponse()
        conn.close()
        return response.status

    def order(self):
        return {'event': 'order.paid', 'text': f'✅ <b>toʻlandi</b>\n\n<a href="{PANEL}">Buyurtmani ochish</a>',
                'parse_mode': 'HTML', 'data': {'order': {'id': 1, 'admin_url': PANEL}}}

    def test_signed_order_is_accepted_and_sent_with_a_button(self):
        status, _ = self.post(self.order())
        self.assertEqual(status, 202)
        self.worker.join()
        self.assertEqual(len(self.client.sent), 1)
        sent = self.client.sent[0]
        self.assertEqual(sent['reply_markup']['inline_keyboard'][0][0]['url'], PANEL)
        self.assertEqual(sent['text'], '✅ <b>toʻlandi</b>')

    def test_unicode_survives_the_trip(self):
        body = self.order()
        body['text'] = 'Toshkent · Chilonzor — oʻlcham: L'
        self.post(body)
        self.worker.join()
        self.assertEqual(self.client.sent[0]['text'], 'Toshkent · Chilonzor — oʻlcham: L')

    def test_bad_signature_is_401_and_nothing_is_sent(self):
        status, _ = self.post(self.order(), headers={'X-Webhook-Signature': 'sha256=00'})
        self.assertEqual(status, 401)
        status, _ = self.post(self.order(), sign=False)
        self.assertEqual(status, 401)
        self.worker.join()
        self.assertEqual(self.client.sent, [])

    def test_secret_header_alone_is_not_enough(self):
        # The contract allows either check; this bot insists on the signature.
        status, _ = self.post(self.order(), sign=False, headers={'X-Webhook-Secret': SECRET})
        self.assertEqual(status, 401)

    def test_stale_timestamp_is_401(self):
        status, _ = self.post(self.order(), timestamp=int(time.time()) - 600)
        self.assertEqual(status, 401)

    def test_unknown_event_is_2xx_and_ignored(self):
        status, _ = self.post({'event': 'test.ping', 'text': '<b>GRAPHIX</b>: sinov', 'data': {}})
        self.assertEqual(status, 200)
        self.worker.join()
        self.assertEqual(self.client.sent, [])

    def test_signed_but_unparseable_body_is_2xx(self):
        status, _ = self.post(b'{not json')
        self.assertEqual(status, 200)
        status, _ = self.post(b'[1,2]')
        self.assertEqual(status, 200)

    def test_wrong_path_and_wrong_method(self):
        self.assertEqual(self.post(self.order(), path='/elsewhere')[0], 404)
        self.assertEqual(self.get('/graphix/events'), 405)
        self.assertEqual(self.get('/healthz'), 200)
        self.assertEqual(self.get('/'), 404)

    def test_trailing_slash_on_the_path_is_tolerated(self):
        self.assertEqual(self.post(self.order(), path='/graphix/events/')[0], 202)

    def test_a_signed_surprise_is_2xx_not_a_dropped_connection(self):
        body = self.order()
        body['event'] = ['not', 'a', 'string']
        self.assertEqual(self.post(body)[0], 200)
        self.assertEqual(self.post(self.order(), headers={'Content-Length': '²'})[0], 411)

    def test_query_string_is_ignored_in_the_path(self):
        self.assertEqual(self.post(self.order(), path='/graphix/events?x=1')[0], 202)

    def test_oversized_body_is_refused_before_reading(self):
        # The status may not reach a client the kernel has already reset, so
        # only assert that nothing was sent and the server is still serving.
        try:
            status, _ = self.post(self.order(), headers={'Content-Length': str(MAX_BODY + 1)})
            self.assertEqual(status, 413)
        except (ConnectionError, http.client.HTTPException):
            pass
        self.assertEqual(self.get('/healthz'), 200)
        self.worker.join(timeout=1)
        self.assertEqual(self.client.sent, [])


if __name__ == '__main__':
    unittest.main()
