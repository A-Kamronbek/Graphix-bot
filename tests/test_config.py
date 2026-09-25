"""Reading ``.env`` and refusing a configuration the bot cannot run with."""
import unittest

from bot.config import ConfigError, Settings, parse_env

GOOD = {'TELEGRAM_BOT_TOKEN': '123:abc', 'TELEGRAM_CHAT_ID': '-100', 'WEBSITE_WEBHOOK_SECRET': 's'}


class ParseEnvTests(unittest.TestCase):
    """The small dotenv reader handles what the runbook tells people to write."""

    def test_reads_pairs_and_skips_comments(self):
        values = parse_env('# a comment\nA=1\n\nB = two \nexport C="quoted"\nD=\'x\'\nno-equals\n')
        self.assertEqual(values, {'A': '1', 'B': 'two', 'C': 'quoted', 'D': 'x'})

    def test_keeps_equals_inside_value(self):
        self.assertEqual(parse_env('URL=http://x/?a=b'), {'URL': 'http://x/?a=b'})


class SettingsTests(unittest.TestCase):
    """Defaults where they are safe, refusals where they are not."""

    def test_defaults(self):
        s = Settings.from_environ(GOOD)
        self.assertEqual((s.bind_host, s.bind_port, s.webhook_path), ('127.0.0.1', 8100, '/graphix/events'))

    def test_missing_names_the_variable(self):
        with self.assertRaises(ConfigError) as ctx:
            Settings.from_environ({**GOOD, 'WEBSITE_WEBHOOK_SECRET': ' '})
        self.assertIn('WEBSITE_WEBHOOK_SECRET', str(ctx.exception))

    def test_chat_id_may_be_blank_at_first(self):
        s = Settings.from_environ({k: v for k, v in GOOD.items() if k != 'TELEGRAM_CHAT_ID'})
        self.assertEqual(s.chat_id, '')

    def test_bad_port(self):
        with self.assertRaises(ConfigError):
            Settings.from_environ({**GOOD, 'BIND_PORT': 'eighty'})
        with self.assertRaises(ConfigError):
            Settings.from_environ({**GOOD, 'BIND_PORT': '70000'})

    def test_path_must_be_absolute_and_loses_trailing_slash(self):
        with self.assertRaises(ConfigError):
            Settings.from_environ({**GOOD, 'WEBHOOK_PATH': 'events'})
        self.assertEqual(Settings.from_environ({**GOOD, 'WEBHOOK_PATH': '/hook/'}).webhook_path, '/hook')


if __name__ == '__main__':
    unittest.main()
