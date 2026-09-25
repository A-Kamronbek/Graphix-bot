"""Sending to Telegram, off the request thread, with retries.

The site waits ten seconds for an answer and never sends an event twice. So
the receiver answers ``2xx`` the moment a request is verified and hands the
message to this worker, which is the only thing that talks to Telegram for
notifications. If Telegram is slow or briefly down the site is not held up,
and the message is retried here rather than lost.

Retries are bounded: a handful of attempts over about a minute, honouring
``retry_after`` on a 429. An error a retry cannot fix - a bad token, a chat
the bot was removed from, HTML Telegram will not parse - is logged once and
dropped, because sending it again five times would only fill the log.

``sendMessage`` is not idempotent, so a retry after a response that was lost
on the way back can show a message twice. That is the failure to prefer: a
paid order seen twice costs a glance, one never seen costs a parcel.

On shutdown the entry point asks the worker to drain, so a restart in the
middle of a retry does not lose what is queued.
"""
import logging
import queue
import threading
import time

from .telegram import TelegramError

logger = logging.getLogger(__name__)

#: Seconds to wait before each retry; the length of this is the attempt limit.
BACKOFF = (2, 5, 10, 20, 30)


class Worker:
    """A queue and one thread that drains it into ``sendMessage``."""

    def __init__(self, client, chat_id, *, backoff=BACKOFF, sleep=time.sleep):
        self.client = client
        self.chat_id = chat_id
        self.backoff = backoff
        self._sleep = sleep
        self._queue = queue.Queue()
        self._thread = threading.Thread(target=self._run, name='telegram-delivery', daemon=True)

    def start(self):
        """Begin draining; called once from the entry point."""
        self._thread.start()

    def enqueue(self, event, params):
        """Accept a message to send; returns at once."""
        self._queue.put((event, params))

    def pending(self):
        """How many messages are queued or being sent right now."""
        return self._queue.unfinished_tasks

    def join(self, timeout=None):
        """Wait until everything queued so far has been attempted; False on timeout.

        ``queue.Queue.join`` takes no timeout and a shutdown must not wait
        forever on Telegram, so this is that method with one, on the queue's
        own condition - ``task_done`` notifies it when the count reaches zero.
        """
        with self._queue.all_tasks_done:
            if self._queue.unfinished_tasks:
                self._queue.all_tasks_done.wait(timeout)
            return self._queue.unfinished_tasks == 0

    def _run(self):
        """The thread body: never exits, never lets one message take it down."""
        while True:
            event, params = self._queue.get()
            try:
                self.send(event, params)
            except Exception:
                # Deliberately broad: a surprise here must not stop the next order.
                logger.exception('delivering %s failed unexpectedly', event)
            finally:
                self._queue.task_done()

    def send(self, event, params):
        """One message, retried on the errors a retry can fix; True when it landed."""
        if not self.chat_id:
            logger.error('%s dropped: TELEGRAM_CHAT_ID is blank - send /chatid to the bot '
                         'and put the answer in .env', event)
            return False
        attempts = len(self.backoff) + 1
        for attempt in range(1, attempts + 1):
            try:
                self.client.send_message(self.chat_id, **params)
                logger.info('%s sent to Telegram', event)
                return True
            except TelegramError as e:
                if e.permanent:
                    logger.error('%s refused by Telegram, not retried: %s', event, e)
                    return False
                if attempt == attempts:
                    logger.error('%s not delivered after %d attempts: %s', event, attempt, e)
                    return False
                wait = self.backoff[attempt - 1]
                if e.retry_after:
                    wait = max(wait, int(e.retry_after))
                logger.warning('%s: attempt %d failed (%s); retrying in %ds',
                               event, attempt, e, wait)
                self._sleep(wait)
        return False
