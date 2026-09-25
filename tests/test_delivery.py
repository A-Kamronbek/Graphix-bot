"""Retries: bounded, backing off, and not wasted on an error that cannot change."""
import unittest

from bot.delivery import Worker
from bot.telegram import TelegramError
from tests.fakes import FakeClient


class SendTests(unittest.TestCase):
    """``Worker.send`` on its own, with sleep recorded instead of slept."""

    def worker(self, client):
        self.slept = []
        return Worker(client, '-100', backoff=(1, 2, 3), sleep=self.slept.append)

    def test_first_try_lands(self):
        client = FakeClient()
        self.assertTrue(self.worker(client).send('order.paid', {'text': 'hi'}))
        self.assertEqual(client.sent[0]['chat_id'], '-100')
        self.assertEqual(self.slept, [])

    def test_transient_failure_is_retried_with_backoff(self):
        client = FakeClient(fail_times=2)
        self.assertTrue(self.worker(client).send('order.paid', {'text': 'hi'}))
        self.assertEqual(self.slept, [1, 2])
        self.assertEqual(len(client.sent), 1)

    def test_gives_up_after_the_last_backoff(self):
        client = FakeClient(fail_times=10)
        self.assertFalse(self.worker(client).send('order.paid', {'text': 'hi'}))
        self.assertEqual(self.slept, [1, 2, 3])
        self.assertEqual(client.sent, [])

    def test_429_waits_at_least_retry_after(self):
        client = FakeClient(fail_times=1, error=TelegramError('flood', status=429, retry_after=7))
        self.assertTrue(self.worker(client).send('order.paid', {'text': 'hi'}))
        self.assertEqual(self.slept, [7])

    def test_blank_chat_id_drops_without_calling_telegram(self):
        client = FakeClient()
        worker = Worker(client, '', backoff=(1,), sleep=lambda s: None)
        self.assertFalse(worker.send('order.paid', {'text': 'hi'}))
        self.assertEqual(client.sent, [])

    def test_permanent_error_is_not_retried(self):
        client = FakeClient(fail_times=5, error=TelegramError('bad html', status=400))
        self.assertFalse(self.worker(client).send('order.paid', {'text': '<b>'}))
        self.assertEqual(self.slept, [])


class QueueTests(unittest.TestCase):
    """The thread drains what the receiver enqueued."""

    def test_enqueued_messages_are_sent_in_order(self):
        client = FakeClient()
        worker = Worker(client, '-100', sleep=lambda s: None)
        worker.start()
        worker.enqueue('a', {'text': 'one'})
        worker.enqueue('b', {'text': 'two'})
        self.assertTrue(worker.join(timeout=5))
        self.assertEqual([m['text'] for m in client.sent], ['one', 'two'])
        self.assertEqual(worker.pending(), 0)

    def test_join_times_out_while_a_send_is_stuck(self):
        import threading
        gate = threading.Event()
        client = FakeClient(fail_times=1)
        worker = Worker(client, '-100', backoff=(1,), sleep=lambda s: gate.wait())
        worker.start()
        worker.enqueue('a', {'text': 'one'})
        self.assertFalse(worker.join(timeout=0.2))
        self.assertEqual(worker.pending(), 1)
        gate.set()
        self.assertTrue(worker.join(timeout=5))


if __name__ == '__main__':
    unittest.main()
