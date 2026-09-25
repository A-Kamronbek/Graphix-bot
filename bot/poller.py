"""The Telegram side: ``/start`` and ``/chatid``.

The bot answers exactly two commands, and both say the same thing - the id
of the chat they were typed in. That is how the operator finds the value for
``TELEGRAM_CHAT_ID`` when the bot is first set up, or when it is added to a
group. Nothing else typed at the bot gets an answer, and answering these
subscribes nobody to anything: notifications go to the one configured chat
and no other.

Updates arrive by long polling. The bot never has to be reachable from the
internet for this, so there is no public URL, no nginx change and no port to
open. A network error pauses the loop for a few seconds and it tries again;
it never exits on one.
"""
import logging
import threading
import time

from .telegram import TelegramError

logger = logging.getLogger(__name__)

COMMANDS = ('/start', '/chatid')

REPLY = ('<b>GRAPHIX</b> — doʻkon boti.\n'
         'Bu chatning ID raqami: <code>{chat_id}</code>\n\n'
         'Uni botning <code>.env</code> faylida <code>TELEGRAM_CHAT_ID</code> '
         'sifatida yozing. Bildirishnomalar faqat sozlangan chatga boradi.')


def command_in(message):
    """The command a message carries, without the ``@botname`` suffix, or ``None``."""
    text = (message.get('text') or '').strip()
    if not text.startswith('/'):
        return None
    word = text.split(maxsplit=1)[0].split('@', 1)[0].lower()
    return word if word in COMMANDS else None


def reply_for(message):
    """The answer to one message, or ``None`` when it deserves none."""
    if command_in(message) is None:
        return None
    chat = message.get('chat') or {}
    chat_id = chat.get('id')
    if chat_id is None:
        return None
    return chat_id, REPLY.format(chat_id=chat_id)


class Poller:
    """A thread that long-polls ``getUpdates`` and answers the two commands."""

    def __init__(self, client, *, sleep=time.sleep):
        self.client = client
        self._sleep = sleep
        self._offset = None
        self._thread = threading.Thread(target=self._run, name='telegram-poller', daemon=True)

    def start(self):
        """Begin polling; called once from the entry point."""
        self._thread.start()

    def _run(self):
        """Poll forever; back off on an error rather than spin or die."""
        while True:
            try:
                self.poll_once()
            except TelegramError as e:
                logger.warning('getUpdates failed (%s); retrying in 5s', e)
                self._sleep(5)
            except Exception:
                logger.exception('the poller hit something unexpected; retrying in 5s')
                self._sleep(5)

    def poll_once(self):
        """One ``getUpdates`` round: answer what needs answering, advance the offset."""
        updates = self.client.get_updates(offset=self._offset) or []
        for update in updates:
            self._offset = update.get('update_id', 0) + 1
            self.handle(update)
        return len(updates)

    def handle(self, update):
        """Answer one update. A failure to reply is logged and skipped, not fatal."""
        message = update.get('message')
        if not isinstance(message, dict):
            return
        reply = reply_for(message)
        if reply is None:
            return
        chat_id, text = reply
        try:
            self.client.send_message(chat_id, text)
            logger.info('answered %s in chat %s', command_in(message), chat_id)
        except TelegramError as e:
            logger.warning('could not answer chat %s: %s', chat_id, e)
