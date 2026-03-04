# Channels

Channels connect agents to the outside world. Currently, smolclaw supports Telegram with more adapters planned.

## Telegram

### Setup

1. **Create a bot** with [@BotFather](https://t.me/botfather) on Telegram
2. **Get the token** — BotFather gives you something like `7123456789:AAH...`
3. **Create the env file** at `~/.smolclaw/agents/<name>/channels/telegram.env`:

```env
TARS_TELEGRAM_TOKEN=7123456789:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

4. **Configure the channel** in `agent.yaml`:

```yaml
channels:
  telegram:
    token_env: TARS_TELEGRAM_TOKEN
    authorized_users: []  # Empty = anyone can use it
```

5. **Restart the gateway**: `smolclaw up`

### Authorization

Restrict who can talk to your bot by listing Telegram user IDs:

```yaml
channels:
  telegram:
    token_env: TARS_TELEGRAM_TOKEN
    authorized_users: [123456789, 987654321]
```

To find your user ID, send a message to your bot and check the gateway logs, or use [@userinfobot](https://t.me/userinfobot).

### Bot Commands

Users can send these commands to the Telegram bot:

| Command | Description |
|---|---|
| `/start` | Shows bot status and connection info |
| `/new` | Clears the current session (fresh start) |

### Features

- **Typing indicators** — the bot shows "typing..." while the agent is processing
- **Markdown rendering** — agent responses are converted from Markdown to Telegram HTML
- **Message splitting** — long responses are automatically split at paragraph boundaries (Telegram's 4000-char limit)
- **Fallback formatting** — if HTML parsing fails, the message is sent as plain text

## REST API

The built-in REST API is always available as a channel:

```bash
curl -X POST http://localhost:7890/api/agents/tars/send \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello!"}'
```

See the [API Reference](../reference/api.md) for all endpoints.

## CLI

Send one-shot messages from the command line:

```bash
smolclaw send tars "What's on my calendar today?"
```

## Writing a Channel Adapter

Channel adapters extend the `Channel` base class:

```python
from smolclaw.channel import Channel

class DiscordChannel(Channel):
    async def start(self) -> None:
        # Connect to Discord, start listening
        ...

    async def stop(self) -> None:
        # Disconnect gracefully
        ...

    async def send(self, chat_id: str, text: str) -> None:
        # Send a message to a Discord channel
        ...
```

The channel receives a `Router` instance and uses it to route incoming messages:

```python
from smolclaw.router import InboundMessage

msg = InboundMessage(
    agent=self.agent_name,
    text=user_message,
    source="discord",
    chat_id=channel_id,
)
response = await self.router.route(msg)
```
