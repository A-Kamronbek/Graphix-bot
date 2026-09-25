"""The bot's tests. ``python -m unittest`` from the repository root runs them all.

Logging is switched off for the run: the refusals and retries the tests
provoke are the point of the tests, not noise for the console.
"""
import logging

logging.disable(logging.CRITICAL)
