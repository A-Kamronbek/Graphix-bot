"""Checking that a request really came from the site.

The site signs every event twice over: ``X-Webhook-Secret`` carries the shared
secret itself, and ``X-Webhook-Signature`` is an HMAC-SHA256 of
``"<timestamp>.<raw body>"`` under that secret. The contract lets the bot
check either; this bot checks the signature, because it also proves the body
was not altered on the way and, with the timestamp inside it, that a captured
request cannot be replayed later.

The digest is computed over the raw bytes the site sent - never over JSON
that was parsed and serialised again, which would change the bytes and never
match.
"""
import hashlib
import hmac
import time


def signature(secret, timestamp, body):
    """``sha256=<hex>`` for ``timestamp`` and ``body`` under ``secret``.

    The same function the site uses to sign, so a test can produce a request
    the bot accepts.
    """
    signed = f'{timestamp}.'.encode('ascii') + body
    return 'sha256=' + hmac.new(secret.encode('utf-8'), signed, hashlib.sha256).hexdigest()


def verify(headers, body, secret, *, max_skew=300, now=None):
    """True when ``body`` was signed with ``secret`` within ``max_skew`` seconds.

    ``headers`` is anything with a case-insensitive ``get`` - the standard
    library's message object is one. Compares in constant time, so a wrong
    signature and a nearly-right one take the same time to refuse.
    """
    timestamp = (headers.get('X-Webhook-Timestamp') or '').strip()
    # isdecimal + isascii: str.isdigit accepts superscripts int() refuses,
    # and a length cap keeps int() from ever refusing a very long string.
    if not timestamp.isascii() or not timestamp.isdecimal() or len(timestamp) > 20:
        return False
    current = time.time() if now is None else now
    if abs(current - int(timestamp)) > max_skew:
        return False
    expected = signature(secret, timestamp, body)
    given = (headers.get('X-Webhook-Signature') or '').strip()
    # Compared as bytes: compare_digest raises on a non-ASCII str, and a
    # header is the one place a stranger can put one.
    return hmac.compare_digest(expected.encode('ascii'), given.encode('utf-8', 'surrogateescape'))
