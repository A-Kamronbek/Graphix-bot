"""The HTTP side: where the site POSTs its events.

One path, one method. A request is read whole, its signature is checked over
the raw bytes, and only then is the body parsed. Anything that fails the
signature is answered ``401`` and not looked at further; anything else is
answered ``2xx`` - including an event the bot does not know, which the
contract says must never look like a failure to the site - and the message,
if there is one, is queued for delivery. The site's ten-second budget is
never spent talking to Telegram.

The server binds to loopback by default. The site and the bot share a
machine, so nothing needs to be reachable from outside, and the secret would
otherwise be one misconfigured firewall away from the internet.
"""
import json
import logging
import socket
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import events, signing

logger = logging.getLogger(__name__)

#: Larger than any event the site sends; anything bigger is not from the site.
MAX_BODY = 256 * 1024


class Handler(BaseHTTPRequestHandler):
    """Answers the site. The settings and the worker hang off the server."""

    server_version = 'GRAPHIX-bot/1'
    sys_version = ''
    protocol_version = 'HTTP/1.1'
    #: A client that opens a connection and then says nothing, or sends fewer
    #: bytes than it declared, gets this long before its thread is freed.
    timeout = 30

    def do_POST(self):
        """Verify, acknowledge, queue. In that order, and nothing slow in between."""
        settings = self.server.settings
        length = self._content_length()
        if self._path() != settings.webhook_path:
            self._discard(length)
            self._answer(HTTPStatus.NOT_FOUND, 'not found')
            return

        if length is None:
            self._answer(HTTPStatus.LENGTH_REQUIRED, 'length required')
            return
        if length > MAX_BODY:
            # Not drained: a body that size is not the site's, and reading
            # it would be doing the sender's work. The client may see a
            # reset instead of the status; that is fine for this client.
            self._answer(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, 'too large')
            return
        body = self.rfile.read(length)

        if not signing.verify(self.headers, body, settings.secret, max_skew=settings.max_skew):
            logger.warning('refused a request with a bad or stale signature from %s',
                           self.client_address[0])
            self._answer(HTTPStatus.UNAUTHORIZED, 'bad signature')
            return

        # From here the request is the site's. Whatever goes wrong with it is
        # our problem to log, never the site's to count as a failed delivery.
        try:
            self._accept(body)
        except Exception:
            logger.exception('a signed request could not be handled')
            self._answer(HTTPStatus.OK, 'ignored')

    def _accept(self, body):
        """Parse a verified body and queue its message, or acknowledge and ignore it."""
        try:
            payload = json.loads(body.decode('utf-8'))
            if not isinstance(payload, dict):
                raise ValueError('body is not an object')
        except (UnicodeDecodeError, ValueError) as e:
            # Signed by the site, yet unreadable: a bug on one side or the
            # other. Say so, but do not make the site count it as a failure.
            logger.error('a signed request could not be parsed: %s', e)
            self._answer(HTTPStatus.OK, 'ignored')
            return

        event = payload.get('event')
        if not isinstance(event, str) or not event:
            event = self.headers.get('X-Webhook-Event') or '?'
        params = events.message_for(payload)
        if params is None:
            logger.info('%s acknowledged and ignored', event)
            self._answer(HTTPStatus.OK, 'ignored')
            return

        self.server.worker.enqueue(event, params)
        logger.info('%s accepted', event)
        self._answer(HTTPStatus.ACCEPTED, 'accepted')

    def do_GET(self):
        """``/healthz`` for a local check; the event path says which method it wants."""
        if self.path == '/healthz':
            self._answer(HTTPStatus.OK, 'ok')
        elif self._path() == self.server.settings.webhook_path:
            self._answer(HTTPStatus.METHOD_NOT_ALLOWED, 'POST only')
        else:
            self._answer(HTTPStatus.NOT_FOUND, 'not found')

    def _discard(self, length):
        """Read and drop a modest body we are about to refuse.

        Closing a socket with unread bytes on it makes the kernel send a
        reset instead of the answer - Windows does it every time, Linux
        when the body outruns a buffer - and the client then sees a dropped
        connection rather than the status it was owed.
        """
        if length and length <= MAX_BODY:
            self.rfile.read(length)

    def _path(self):
        """The request path without a trailing slash - and ``/`` still ``/``."""
        return self.path.split('?', 1)[0].rstrip('/') or '/'

    def _content_length(self):
        """The declared body length, or ``None`` when it is missing or not a number."""
        value = (self.headers.get('Content-Length') or '').strip()
        # isdecimal + isascii, not isdigit: int() refuses the superscripts isdigit accepts.
        if not value or not value.isascii() or not value.isdecimal() or len(value) > 12:
            return None
        return int(value)

    def _answer(self, status, text):
        """A short plain-text reply; the site ignores the body, a human may not."""
        data = text.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        # One request per connection. The site opens a fresh one per event
        # anyway, and a refused body that was never read must not be parsed
        # as the next request on a kept-alive socket.
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(data)
        self.close_connection = True

    def log_message(self, format, *args):
        """Route the request line into logging instead of stderr's own format."""
        logger.debug('%s - %s', self.client_address[0], format % args)


class Server(ThreadingHTTPServer):
    """A ``ThreadingHTTPServer`` that carries the settings and the delivery worker."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, settings, worker):
        # The contract allows ::1 as a loopback address; a colon means IPv6.
        if ':' in settings.bind_host:
            self.address_family = socket.AF_INET6
        super().__init__((settings.bind_host, settings.bind_port), Handler)
        self.settings = settings
        self.worker = worker
