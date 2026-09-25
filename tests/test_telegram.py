"""The Bot API client, against a fake ``urlopen``: what it sends, what it raises."""
import io
import json
import unittest
import urllib.error

from bot.telegram import Client, TelegramError


class Response(io.BytesIO):
    """Enough of an ``urlopen`` response: bytes and a context manager."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class FakeOpener:
    """Records the requests and answers each from a script."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append((request, timeout))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return Response(json.dumps(answer).encode('utf-8'))


def http_error(code, body):
    return urllib.error.HTTPError('https://api.telegram.org/x', code, 'err', {},
                                  io.BytesIO(json.dumps(body).encode('utf-8')))


class ClientTests(unittest.TestCase):
    """One JSON POST per call; the result comes back, the failure comes out typed."""

    def test_sends_json_and_returns_result(self):
        opener = FakeOpener([{'ok': True, 'result': {'message_id': 9}}])
        client = Client('123:abc', opener=opener)
        result = client.send_message(-100, '<b>hi</b>',
                                     reply_markup={'inline_keyboard': [[{'text': 'x', 'url': 'https://a/'}]]})
        self.assertEqual(result, {'message_id': 9})
        request, timeout = opener.requests[0]
        self.assertEqual(request.full_url, 'https://api.telegram.org/bot123:abc/sendMessage')
        body = json.loads(request.data.decode('utf-8'))
        self.assertEqual(body['chat_id'], -100)
        self.assertEqual(body['parse_mode'], 'HTML')
        self.assertTrue(body['disable_web_page_preview'])
        self.assertIn('inline_keyboard', body['reply_markup'])
        self.assertEqual(timeout, 15)

    def test_long_poll_outlives_telegrams_hold(self):
        opener = FakeOpener([{'ok': True, 'result': []}])
        Client('t', opener=opener).get_updates(offset=5, timeout=50)
        request, timeout = opener.requests[0]
        self.assertGreater(timeout, 50)
        body = json.loads(request.data.decode('utf-8'))
        self.assertEqual((body['offset'], body['timeout'], body['allowed_updates']), (5, 50, ['message']))

    def test_http_error_carries_status_and_retry_after(self):
        opener = FakeOpener([http_error(429, {'ok': False, 'description': 'Too Many Requests',
                                              'parameters': {'retry_after': 3}})])
        with self.assertRaises(TelegramError) as ctx:
            Client('t', opener=opener).get_me()
        self.assertEqual((ctx.exception.status, ctx.exception.retry_after), (429, 3))
        self.assertFalse(ctx.exception.permanent)
        self.assertIn('Too Many Requests', str(ctx.exception))

    def test_400_is_permanent_and_network_error_is_not(self):
        opener = FakeOpener([http_error(400, {'ok': False, 'description': "can't parse entities"}),
                             urllib.error.URLError('unreachable')])
        client = Client('t', opener=opener)
        with self.assertRaises(TelegramError) as ctx:
            client.get_me()
        self.assertTrue(ctx.exception.permanent)
        with self.assertRaises(TelegramError) as ctx:
            client.get_me()
        self.assertEqual(ctx.exception.status, 0)
        self.assertFalse(ctx.exception.permanent)

    def test_ok_false_in_a_200_is_an_error(self):
        opener = FakeOpener([{'ok': False, 'error_code': 401, 'description': 'Unauthorized'}])
        with self.assertRaises(TelegramError) as ctx:
            Client('t', opener=opener).get_me()
        self.assertEqual(ctx.exception.status, 401)
        self.assertTrue(ctx.exception.permanent)

    def test_token_is_not_in_the_error_text(self):
        opener = FakeOpener([urllib.error.URLError('unreachable')])
        with self.assertRaises(TelegramError) as ctx:
            Client('123:SECRET', opener=opener).get_me()
        self.assertNotIn('SECRET', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
