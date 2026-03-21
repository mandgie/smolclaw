# Channels

Channels connect agents to the outside world. smolclaw includes Telegram and Webhook adapters out of the box, plus an extensible plugin system for custom channels.

## Telegram

### Quick Setup

The fastest way — use the `--telegram` flag when creating an agent:

```bash
smolclaw init --agent tars --telegram 7123456789:AAHxxxxxx
# or for an existing project:
smolclaw add coach --telegram 7123456789:AAHxxxxxx
```

This automatically creates the env file and configures `agent.yaml`. Done.

### Manual Setup

If you prefer to configure manually (or need to add Telegram to an existing agent):

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

## Webhook

Send agent responses to any HTTP endpoint via POST. Zero dependencies — uses Python's built-in `urllib.request`.

### Setup

```yaml
channels:
  webhook:
    url: https://hooks.slack.com/services/T00/B00/xxxx
    headers:
      X-Custom-Header: my-value
```

No `token_env` needed — webhooks are send-only channels. The `url` field is required.

### Payload

The webhook POSTs JSON:

```json
{
  "text": "Agent response text here"
}
```

### Use Cases

- Slack incoming webhooks
- Discord webhooks
- Custom notification APIs
- Integration with other services

## REST API

The built-in REST API is always available as a channel:

```bash
curl -X POST http://localhost:7890/api/agents/tars/send \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello!"}'
```

See the [API Reference](../reference/api.md) for all endpoints.

## CLI

Send one-shot messages or start an interactive session:

```bash
# One-shot
smolclaw send tars "What's on my calendar today?"

# Interactive REPL with session persistence
smolclaw chat tars
```

## Custom Channel Adapters

### Writing an Adapter

Channel adapters extend the `Channel` base class:

```python
from smolclaw.channel import Channel

class DiscordChannel(Channel):
    channel_type = "discord"

    async def start(self) -> None:
        # Connect and start listening
        ...

    async def stop(self) -> None:
        # Disconnect gracefully
        ...

    async def send(self, chat_id: str, text: str) -> None:
        # Send a message
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

### Registering Custom Channels

#### Programmatic registration

```python
from smolclaw.channel import register_channel

register_channel("discord", DiscordChannel)
```

After registration, use the channel type in any `agent.yaml`:

```yaml
channels:
  discord:
    token_env: DISCORD_BOT_TOKEN
    authorized_users: ["user-id-123"]
```

#### Entry-point plugins

Third-party packages can expose channels automatically via entry points in their `pyproject.toml`:

```toml
[project.entry-points."smolclaw.channels"]
discord = "smolclaw_discord:DiscordChannel"
```

Once the package is installed, the channel type is automatically available — no import or registration code needed. smolclaw discovers entry-point channels at startup.

#### Listing available channels

```python
from smolclaw.channel import list_channel_types

print(list_channel_types())
# {'telegram': <class 'TelegramChannel'>, 'webhook': <class 'WebhookChannel'>, ...}
```

### Channel Configuration

All channels share a common `ChannelConfig`:

| Field | Type | Default | Description |
|---|---|---|---|
| `token_env` | string | `""` | Environment variable name for the channel token |
| `authorized_users` | list | `[]` | User IDs allowed to interact (empty = all) |
| `url` | string | `""` | Endpoint URL (for webhook channels) |
| `headers` | dict | `{}` | Custom HTTP headers (for webhook channels) |
| `app_token_env` | string | `""` | Secondary token env (for dual-token auth like Slack Socket Mode) |

User IDs can be integers (Telegram) or strings (Slack, Discord) — the `authorized_users` field accepts both.
