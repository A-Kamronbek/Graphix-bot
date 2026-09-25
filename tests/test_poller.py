"""``/start`` and ``/chatid``, and nothing else."""
import unittest

from bot.poller import Poller, command_in, reply_for
from tests.fakes import FakeClient


def update(uid, text, chat_id=555):
    """One ``getUpdates`` entry carrying a text message."""
    return {'update_id': uid, 'message': {'message_id': uid, 'chat': {'id': chat_id}, 'text': text}}


class CommandTests(unittest.TestCase):
    """Recognising the two commands however Telegram delivers them."""

    def test_recognised_forms(self):
        for text in ('/start', '/chatid', '/CHATID', '/start@graphix_bot', '/chatid extra'):
            self.assertIsNotNone(command_in({'text': text}), text)

    def test_everything_else_is_ignored(self):
        for text in ('hello', '/help', 'start', '', None):
            self.assertIsNone(command_in({'text': text}), repr(text))
        self.assertIsNone(reply_for({'text': '/start'}))  # no chat at all

    def test_reply_names_the_chat(self):
        chat_id, text = reply_for({'text': '/chatid', 'chat': {'id': -1001}})
        self.assertEqual(chat_id, -1001)
        self.assertIn('<code>-1001</code>', text)


class PollerTests(unittest.TestCase):
    """One round: answer, advance the offset, survive junk."""

    def test_answers_and_advances(self):
        client = FakeClient(updates=[[update(10, '/start'), update(11, 'hi'), update(12, '/chatid', 7)]])
        poller = Poller(client, sleep=lambda s: None)
        self.assertEqual(poller.poll_once(), 3)
        self.assertEqual([m['chat_id'] for m in client.sent], [555, 7])
        self.assertEqual(poller.poll_once(), 0)
        self.assertEqual(client.offsets, [None, 13])

    def test_junk_updates_do_not_raise(self):
        client = FakeClient(updates=[[{'update_id': 1}, {'update_id': 2, 'message': 'x'},
                                      {'update_id': 3, 'message': {'text': '/start'}}]])
        poller = Poller(client, sleep=lambda s: None)
        poller.poll_once()
        self.assertEqual(client.sent, [])

    def test_a_failed_reply_is_skipped(self):
        client = FakeClient(fail_times=1, updates=[[update(1, '/start'), update(2, '/start')]])
        Poller(client, sleep=lambda s: None).poll_once()
        self.assertEqual(len(client.sent), 1)


if __name__ == '__main__':
    unittest.main()
