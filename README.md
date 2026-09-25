# graphix-bot

The Telegram bot behind [graphix.uz](https://graphix.uz)'s notifications. The
site pushes each event to the bot as signed JSON — a paid order, a contact
message, a review waiting for moderation — and the bot shows it in the shop's
Telegram chat with a button that opens the staff panel.

It is a receiving service, not a client of the site: it never reads the site
or its database, and nothing it does is triggered by the shop. The contract
is the site's `docs/integrations/telegram-bot.md`; this repository is the
other side of it.

**Standard library only.** Python 3.12+, no dependencies, no virtualenv.

```
A customer pays  →  the site POSTs the event to 127.0.0.1:8100  →  the bot
verifies the signature, answers at once, and sends the message to Telegram
```

## What it does

- Accepts the site's `POST` on one loopback path, verifies the HMAC signature
  over the raw body (five-minute window), and answers within milliseconds —
  Telegram is spoken to afterwards, off the request thread, so the site's
  ten-second budget is never spent waiting.
- Forwards the site's finished message unchanged, and adds an inline
  **Buyurtmani ochish / Xabarni ochish / Sharhni ochish** button built from the
  event's `admin_url`. The duplicate link line at the end of the text is
  dropped, and only that line.
- Delivers to **one** chat, the one in `.env`. Nobody can subscribe from
  inside Telegram.
- Retries a message Telegram could not take — network, 5xx, 429 with its
  `retry_after` — a handful of times over about a minute, and drops one it
  can never take (bad token, bot removed from the chat, HTML it will not
  parse) after logging why.
- Answers `/start` and `/chatid` with the chat's id. That is how you find the
  value for `TELEGRAM_CHAT_ID`; nothing else is answered.
- Acknowledges an event it does not know with `2xx` and ignores it, as the
  contract requires, so a new event on the site can never look like a failure.
- Never exits on an error. A bad signature is `401`; anything else the bot
  cannot use is logged and acknowledged; the poller backs off and tries again.

## Layout

```
bot/
  __main__.py   python -m bot: reads .env, proves the token, starts everything
  config.py     .env reader and validated settings
  signing.py    the HMAC check, over the raw bytes
  server.py     the HTTP receiver (loopback, one path, POST only)
  events.py     event JSON → sendMessage parameters, plus the panel button
  delivery.py   the queue and the thread that talks to Telegram, with retries
  poller.py     long-polling getUpdates for /start and /chatid
  telegram.py   a small Bot API client on urllib
tests/          python -m unittest
deploy/         the systemd unit
```

## Running it locally

```bash
git clone git@github.com:A-Kamronbek/graphix-bot.git
cd graphix-bot
cp .env.example .env      # token, chat id, shared secret
python -m bot
```

Then, in the site's `.env`:

```
TELEGRAM_BOT_WEBHOOK_URL=http://127.0.0.1:8100/graphix/events
WEBSITE_WEBHOOK_SECRET=<the same secret>
```

and from the site's repository:

```bash
python manage.py shell -c "from core import telegram; print(telegram.deliver('test.ping', '<b>GRAPHIX</b>: sinov', {}))"
```

`True` means the bot answered. It logs `test.ping acknowledged and ignored` —
nothing reaches Telegram for a ping, by contract. To see a real message, place
and pay for an order, send a contact message, or write a review.

Tests:

```bash
python -m unittest
```

They start a real server on an ephemeral port and talk to a fake Telegram;
no token or network is needed.

## On the server

The bot runs on the same VPS as the site, as the same user, listening on
loopback. Every command runs on the server.

```bash
# 1. the code
sudo git clone git@github.com:A-Kamronbek/graphix-bot.git /srv/graphix-bot
sudo chown -R graphix:graphix /srv/graphix-bot

# 2. the secrets
sudo -u graphix cp /srv/graphix-bot/.env.example /srv/graphix-bot/.env
sudo -u graphix chmod 600 /srv/graphix-bot/.env
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # the shared secret
sudo -u graphix nano /srv/graphix-bot/.env
#    TELEGRAM_BOT_TOKEN=      from @BotFather
#    TELEGRAM_CHAT_ID=        leave blank until step 4
#    WEBSITE_WEBHOOK_SECRET=  the value just generated

# 3. the unit
sudo cp /srv/graphix-bot/deploy/graphix-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
```

**4. Find the chat id.** The bot starts with `TELEGRAM_CHAT_ID` blank — it
answers `/chatid` but drops every event, and says so in its log — so start
it and ask it:

```bash
sudo systemctl enable --now graphix-bot
sudo journalctl -u graphix-bot -n 5 --no-pager      # "graphix-bot 1.0.0 as @…, notifying chat (not set)"
```

Open the bot in Telegram (or add it to the staff group) and send `/chatid`.
It answers with the id. Put that in `.env` and restart:

```bash
sudo -u graphix nano /srv/graphix-bot/.env            # TELEGRAM_CHAT_ID=…
sudo systemctl restart graphix-bot
```

**5. Point the site at it.** In the site's `.env`:

```
TELEGRAM_BOT_WEBHOOK_URL=http://127.0.0.1:8100/graphix/events
WEBSITE_WEBHOOK_SECRET=<the same secret as the bot's>
```

```bash
sudo systemctl restart graphix
```

With the URL set the site's own `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`
are no longer used; they may stay in the file.

**6. Prove it.**

```bash
graphix shell -c "from core import telegram; print(telegram.deliver('test.ping', '<b>GRAPHIX</b>: sinov', {}))"
sudo journalctl -u graphix-bot -n 3 --no-pager       # "test.ping acknowledged and ignored"
```

`True` and that line mean the two sides share the secret and the bot is
listening. Then place a test order and pay for it: exactly one message
arrives, headed **toʻlandi**, with a **Buyurtmani ochish** button.

### Updating

```bash
cd /srv/graphix-bot && sudo -u graphix git pull && sudo systemctl restart graphix-bot
```

### Reading the log

```bash
sudo journalctl -u graphix-bot -f
```

Every event logs twice: `order.paid accepted` when the site's request was
verified and queued, then `order.paid sent to Telegram` when it landed, or
the reason it did not. A `refused a request with a bad or stale signature`
line means the two `.env` files disagree on the secret, or the clocks are
more than five minutes apart.

## Privacy

Events carry customers' names, phone numbers, addresses and messages. The
bot keeps nothing: a message is held in memory until Telegram takes it and
then forgotten, and the log records event names and outcomes, never the
contents. It runs on the site's own server in Warsaw, so the site's privacy
policy already names where this data is processed.
