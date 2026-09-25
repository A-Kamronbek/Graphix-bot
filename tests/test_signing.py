"""The signature check, against the contract's own definition."""
import hashlib
import hmac
import unittest

from bot import signing

SECRET = 'shared'
BODY = b'{"event":"order.paid"}'


class SignatureTests(unittest.TestCase):
    """Same bytes in, same digest out as the site's ``core.telegram.signature``."""

    def test_matches_the_contract(self):
        ts = '1700000000'
        expected = 'sha256=' + hmac.new(SECRET.encode(), ts.encode() + b'.' + BODY,
                                        hashlib.sha256).hexdigest()
        self.assertEqual(signing.signature(SECRET, ts, BODY), expected)

    def test_accepts_a_fresh_valid_signature(self):
        ts = 1700000000
        headers = {'X-Webhook-Timestamp': str(ts),
                   'X-Webhook-Signature': signing.signature(SECRET, ts, BODY)}
        self.assertTrue(signing.verify(headers, BODY, SECRET, now=ts + 10))

    def test_rejects_a_stale_timestamp(self):
        ts = 1700000000
        headers = {'X-Webhook-Timestamp': str(ts),
                   'X-Webhook-Signature': signing.signature(SECRET, ts, BODY)}
        self.assertFalse(signing.verify(headers, BODY, SECRET, now=ts + 301))
        self.assertFalse(signing.verify(headers, BODY, SECRET, now=ts - 301))

    def test_rejects_a_changed_body_or_wrong_secret(self):
        ts = 1700000000
        headers = {'X-Webhook-Timestamp': str(ts),
                   'X-Webhook-Signature': signing.signature(SECRET, ts, BODY)}
        self.assertFalse(signing.verify(headers, BODY + b' ', SECRET, now=ts))
        self.assertFalse(signing.verify(headers, BODY, 'other', now=ts))

    def test_rejects_missing_or_malformed_headers(self):
        self.assertFalse(signing.verify({}, BODY, SECRET))
        self.assertFalse(signing.verify({'X-Webhook-Timestamp': 'now'}, BODY, SECRET))
        self.assertFalse(signing.verify({'X-Webhook-Timestamp': '1700000000',
                                         'X-Webhook-Signature': ''}, BODY, SECRET, now=1700000000))

    def test_hostile_headers_are_refused_not_raised(self):
        # Superscript digits pass str.isdigit and fail int(); a non-ASCII
        # signature makes compare_digest raise. Both are a False, not a 500.
        self.assertFalse(signing.verify({'X-Webhook-Timestamp': '²'}, BODY, SECRET))
        self.assertFalse(signing.verify({'X-Webhook-Timestamp': '9' * 5000}, BODY, SECRET))
        self.assertFalse(signing.verify({'X-Webhook-Timestamp': '1700000000',
                                         'X-Webhook-Signature': 'sha256=ü'}, BODY, SECRET,
                                        now=1700000000))


if __name__ == '__main__':
    unittest.main()
