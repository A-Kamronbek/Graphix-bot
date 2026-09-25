"""Settings, read once from ``.env``.

The site keeps every credential in a ``.env`` next to its code and loads it
itself, with nothing in the systemd unit; the bot does the same so there is
one place to look. A missing token or secret is reported at startup with the
variable's name, not discovered as a traceback on the first order.
"""
import os
from dataclasses import dataclass
from pathlib import Path

#: The variables the bot cannot run without. TELEGRAM_CHAT_ID is not one of
#: them: the bot has to be running before /chatid can tell the operator what
#: to put there, so a blank id starts the bot and drops events until it is set.
REQUIRED = ('TELEGRAM_BOT_TOKEN', 'WEBSITE_WEBHOOK_SECRET')


class ConfigError(Exception):
    """A setting is missing or malformed. Raised at startup, never later."""


def parse_env(text):
    """``KEY=value`` lines to a dict; ``#`` comments and blank lines skipped.

    A value may be wrapped in single or double quotes, which are removed; an
    ``export`` prefix is tolerated. Deliberately small - it reads the file
    the runbook tells the operator to write, not every dotenv dialect.
    """
    values = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        if line.startswith('export '):
            line = line[len('export '):].lstrip()
        key, _, value = line.partition('=')
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def load_env(path):
    """Put the file's variables into ``os.environ`` without overriding real ones.

    A variable already set in the environment wins, which is what lets a test
    or a one-off shell run override the file without editing it.
    """
    path = Path(path)
    if not path.is_file():
        return
    for key, value in parse_env(path.read_text(encoding='utf-8')).items():
        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Settings:
    """Everything the running bot needs, validated."""

    token: str
    chat_id: str
    secret: str
    bind_host: str = '127.0.0.1'
    bind_port: int = 8100
    webhook_path: str = '/graphix/events'
    log_level: str = 'INFO'
    #: Seconds a signed request may be off from our clock (the contract says five minutes).
    max_skew: int = 300

    @classmethod
    def from_environ(cls, environ=None):
        """Build the settings from the environment, refusing anything unusable."""
        env = os.environ if environ is None else environ
        missing = [name for name in REQUIRED if not env.get(name, '').strip()]
        if missing:
            raise ConfigError('missing in .env: ' + ', '.join(missing))

        try:
            port = int(env.get('BIND_PORT', '8100'))
        except ValueError:
            raise ConfigError('BIND_PORT must be a number') from None
        if not 1 <= port <= 65535:
            raise ConfigError('BIND_PORT must be between 1 and 65535')

        path = env.get('WEBHOOK_PATH', '/graphix/events').strip() or '/graphix/events'
        if not path.startswith('/'):
            raise ConfigError('WEBHOOK_PATH must start with /')

        return cls(
            token=env['TELEGRAM_BOT_TOKEN'].strip(),
            chat_id=env.get('TELEGRAM_CHAT_ID', '').strip(),
            secret=env['WEBSITE_WEBHOOK_SECRET'].strip(),
            bind_host=env.get('BIND_HOST', '127.0.0.1').strip() or '127.0.0.1',
            bind_port=port,
            webhook_path=path.rstrip('/') or '/',
            log_level=env.get('LOG_LEVEL', 'INFO').strip().upper() or 'INFO',
        )
