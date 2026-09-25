"""GRAPHIX's Telegram bot: the shop's notifications, relayed.

The site (graphix.uz) pushes every notification here as signed JSON - a paid
order, a contact message, a review waiting for moderation - and this program
shows it in the shop's Telegram chat with a button that opens the staff
panel. Nothing here reads the site or its database; the contract is the
site's ``docs/integrations/telegram-bot.md`` and this package implements the
receiving side of it, no more.

Standard library only, on purpose. The bot is a hundred-line service that
runs beside the site on the same server, and a dependency it does not need is
a thing that can break at 3 a.m. for no benefit.
"""

__version__ = '1.0.0'
