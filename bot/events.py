"""From an event the site sent to a message Telegram will show.

The site already composed the message: ``text`` is finished Uzbek in
Telegram's HTML parse mode, with every customer-typed value escaped. The bot
forwards it as it is and adds one thing the site cannot - an inline button
that opens the staff panel at the order, message or review - built from the
``admin_url`` the event carries.

The text ends with the same link as a line of its own, because a bot that
only forwards text still needs the owner to get there. With a button under
the message that line would say the same thing twice, so the bot drops it -
only when the last line is exactly that anchor, so nothing else the site
wrote is ever touched.
"""
import re

#: The three events the site sends, and the button each one gets.
BUTTONS = {
    'order.paid': ('order', 'Buyurtmani ochish'),
    'message.created': ('message', 'Xabarni ochish'),
    'review.created': ('review', 'Sharhni ochish'),
}

_ANCHOR_LINE = re.compile(r'^<a href="(?P<href>[^"]*)">[^<]*</a>$')


def known(event):
    """Is this an event the bot shows? Anything else is acknowledged and ignored."""
    return isinstance(event, str) and event in BUTTONS


def panel_url(event, data):
    """The panel link inside ``data``, or ``''`` when the event carries none."""
    key = BUTTONS.get(event, (None,))[0]
    if not key or not isinstance(data, dict):
        return ''
    inner = data.get(key)
    if not isinstance(inner, dict):
        return ''
    url = inner.get('admin_url') or ''
    # Telegram accepts only http(s) in a URL button; anything else is no button.
    return url if isinstance(url, str) and url.startswith(('https://', 'http://')) else ''


def strip_trailing_link(text, url):
    """Drop a final ``<a href="url">…</a>`` line, since the button now carries it."""
    if not url:
        return text
    head, sep, last = text.rstrip().rpartition('\n')
    match = _ANCHOR_LINE.match(last.strip())
    if sep and match and match.group('href') == url:
        return head.rstrip()
    return text


def message_for(payload):
    """The ``sendMessage`` parameters for one event, or ``None`` to ignore it.

    ``payload`` is the parsed body the site POSTed. A known event with no
    usable ``text`` is ignored too: there is nothing to show, and inventing a
    message from ``data`` would be a second copy of the site's copywriting to
    keep in step.
    """
    event = payload.get('event')
    text = payload.get('text')
    if not known(event) or not isinstance(text, str) or not text.strip():
        return None

    url = panel_url(event, payload.get('data'))
    params = {
        'text': strip_trailing_link(text, url),
        'parse_mode': payload.get('parse_mode') or 'HTML',
        'disable_web_page_preview': True,
    }
    if url:
        params['reply_markup'] = {
            'inline_keyboard': [[{'text': BUTTONS[event][1], 'url': url}]],
        }
    return params
