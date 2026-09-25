"""``python -m bot``: start the receiver, the delivery worker and the poller.

Reads ``.env`` from the working directory (or the file ``BOT_ENV`` names),
proves the token with one ``getMe``, then serves until stopped. Everything is
logged to standard output so systemd's journal is the one place to look, the
same as the site's gunicorn unit.
"""
import logging
import os
import signal
import sys
import threading

from . import __version__
from .config import ConfigError, Settings, load_env
from .delivery import Worker
from .poller import Poller
from .server import Server
from .telegram import Client, TelegramError

logger = logging.getLogger('bot')


def main(argv=None):
    """Entry point; returns the process exit status."""
    load_env(os.environ.get('BOT_ENV', '.env'))
    try:
        settings = Settings.from_environ()
    except ConfigError as e:
        print(f'graphix-bot: {e}', file=sys.stderr)
        return 2

    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
        stream=sys.stdout,
    )

    client = Client(settings.token)
    try:
        me = client.get_me()
    except TelegramError as e:
        if e.permanent:
            logger.error('the bot token does not work: %s', e)
            return 2
        # Telegram unreachable right now - DNS not up yet after a boot, an
        # outage. The receiver must still come up: the site's events would
        # otherwise be refused, and the site never sends one twice. The
        # worker retries and the poller backs off, so nothing else needs the
        # token proven first.
        logger.warning('could not reach Telegram at startup (%s); starting anyway', e)
        me = {}
    logger.info('graphix-bot %s as @%s, notifying chat %s',
                __version__, me.get('username', '?'), settings.chat_id or '(not set)')
    if not settings.chat_id:
        logger.warning('TELEGRAM_CHAT_ID is blank: events will be acknowledged and dropped. '
                       'Send /chatid to the bot, put the answer in .env and restart')

    # A webhook left on the bot would make getUpdates refuse; clearing one
    # that is not there is a no-op. Not fatal either way - the receiver is
    # the important half, and it does not need this.
    try:
        client.delete_webhook()
    except TelegramError as e:
        logger.warning('deleteWebhook failed (%s); /start may not answer', e)

    worker = Worker(client, settings.chat_id)
    worker.start()
    Poller(client).start()

    try:
        server = Server(settings, worker)
    except OSError as e:
        logger.error('cannot listen on %s:%s: %s', settings.bind_host, settings.bind_port, e)
        return 1
    logger.info('listening on http://%s:%s%s', settings.bind_host, settings.bind_port,
                settings.webhook_path)

    def stop(signum, frame):
        """Stop taking requests, from another thread: shutdown() blocks until
        serve_forever has returned, and must not be called on its own thread."""
        logger.info('stopping')
        threading.Thread(target=server.shutdown, name='shutdown', daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.serve_forever()
    finally:
        server.server_close()

    # What the site has already handed over is sent before the process ends;
    # a restart in the middle of a retry must not cost an order. The unit's
    # TimeoutStopSec leaves room for this.
    if worker.pending():
        logger.info('waiting for %d queued message(s)', worker.pending())
        if not worker.join(timeout=45):
            logger.error('%d message(s) still undelivered at exit', worker.pending())
    return 0


if __name__ == '__main__':
    sys.exit(main())
