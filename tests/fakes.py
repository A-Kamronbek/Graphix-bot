"""Stand-ins for Telegram, so no test needs a token or the network."""
from bot.telegram import TelegramError


class FakeClient:
    """Records every ``sendMessage``; fails the first ``fail_times`` of them.

    ``updates`` is a list of ``getUpdates`` answers to hand out in order; once
    they are used up the poller gets an empty list, like a quiet chat.
    """

    def __init__(self, *, fail_times=0, error=None, updates=None):
        self.sent = []
        self.fail_times = fail_times
        self.error = error or TelegramError('boom', status=502)
        self.updates = list(updates or [])
        self.offsets = []

    def send_message(self, chat_id, text, **params):
        if self.fail_times > 0:
            self.fail_times -= 1
            raise self.error
        self.sent.append({'chat_id': chat_id, 'text': text, **params})
        return {'message_id': len(self.sent)}

    def get_updates(self, offset=None, timeout=50):
        self.offsets.append(offset)
        return self.updates.pop(0) if self.updates else []

    def get_me(self):
        return {'username': 'graphix_test_bot'}

    def delete_webhook(self):
        return True
