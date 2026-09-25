"""A small client for the Telegram Bot API, on ``urllib`` alone.

Two methods are used - ``sendMessage`` and ``getUpdates`` - plus
``deleteWebhook`` once at startup and ``getMe`` to prove the token. Each call
is one JSON POST; Telegram answers ``{"ok": true, "result": ...}`` or
``{"ok": false, "description": ...}``. Errors are turned into
:class:`TelegramError` with the facts that matter for a retry - the status
and, on a 429, how long Telegram asked us to wait - and nothing else is
swallowed here, because the caller decides what a failure means.

The token appears in every URL, so it is never logged: log lines name the
method and the outcome only.
"""
import http.client
import json
import logging
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

API = 'https://api.telegram.org/bot{token}/{method}'
USER_AGENT = 'GRAPHIX-bot/1'


class TelegramError(Exception):
    """The Bot API refused or could not be reached.

    ``status`` is the HTTP status (0 when nothing answered), ``retry_after``
    the seconds Telegram asked for on a 429, else ``None``. ``permanent`` is
    True for the errors a retry cannot fix - a wrong token, a chat the bot is
    not in, a message Telegram cannot parse.
    """

    def __init__(self, message, *, status=0, retry_after=None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after

    @property
    def permanent(self):
        """A 4xx other than 429 will fail the same way however often it is sent."""
        return 400 <= self.status < 500 and self.status != 429


class Client:
    """One bot token, one way to call it."""

    def __init__(self, token, *, timeout=15, opener=None):
        self.token = token
        self.timeout = timeout
        # Injectable for tests; the real one is urllib's default.
        self._open = opener or urllib.request.urlopen

    def call(self, method, *, _timeout=None, **params):
        """POST ``params`` as JSON to ``method``; return Telegram's ``result``.

        ``_timeout`` overrides the client's for one call - a long poll must be
        allowed to last longer than an ordinary request.
        """
        request = urllib.request.Request(
            API.format(token=self.token, method=method),
            data=json.dumps(params, ensure_ascii=False).encode('utf-8'),
            headers={'Content-Type': 'application/json; charset=utf-8',
                     'User-Agent': USER_AGENT},
            method='POST',
        )
        try:
            with self._open(request, timeout=_timeout or self.timeout) as response:
                payload = json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            # Telegram puts the reason in the body of an error response.
            payload = _read_json(e)
            description = payload.get('description') or str(e)
            retry_after = (payload.get('parameters') or {}).get('retry_after')
            raise TelegramError(f'{method}: {description}', status=e.code,
                                retry_after=retry_after) from None
        except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as e:
            # HTTPException covers a connection that died mid-body
            # (IncompleteRead) - it is not an OSError, and it is retryable.
            raise TelegramError(f'{method}: {e}') from None

        if not payload.get('ok'):
            raise TelegramError(f"{method}: {payload.get('description', 'not ok')}",
                                status=int(payload.get('error_code') or 0))
        return payload.get('result')

    # Convenience wrappers; each is one API method with the same name.

    def get_me(self):
        """The bot's own identity; the cheapest way to prove the token works."""
        return self.call('getMe')

    def send_message(self, chat_id, text, *, parse_mode='HTML', reply_markup=None,
                     disable_web_page_preview=True):
        """Send one message; the inline keyboard is optional."""
        params = {'chat_id': chat_id, 'text': text, 'parse_mode': parse_mode,
                  'disable_web_page_preview': disable_web_page_preview}
        if reply_markup:
            params['reply_markup'] = reply_markup
        return self.call('sendMessage', **params)

    def get_updates(self, offset=None, timeout=50):
        """Long-poll for updates; only messages, since commands are all we answer."""
        params = {'timeout': timeout, 'allowed_updates': ['message']}
        if offset is not None:
            params['offset'] = offset
        # Telegram holds the request open for up to ``timeout`` seconds; the
        # socket must outlive that or every quiet poll ends in a timeout.
        return self.call('getUpdates', _timeout=timeout + 10, **params)

    def delete_webhook(self):
        """Clear any webhook so ``getUpdates`` is allowed; harmless when there is none."""
        return self.call('deleteWebhook', drop_pending_updates=False)


def _read_json(error):
    """The JSON body of an HTTP error, or ``{}`` when there is none worth reading."""
    try:
        return json.loads(error.read().decode('utf-8'))
    except Exception:
        return {}
