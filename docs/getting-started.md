# Getting Started

## Prerequisites

- **Python 3.11+**
- **Claude CLI** — installed and authenticated ([install guide](https://docs.anthropic.com/en/docs/claude-code/overview))

## Installation

```bash
pip install smolclaw
```

For development:

```bash
git clone https://github.com/mandgie/smolclaw.git
cd smolclaw
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Initialize Your Project

```bash
smolclaw init --agent tars
```

This creates the smolclaw home directory at `~/.smolclaw/` with:

```
~/.smolclaw/
├── config.yaml              # Gateway settings (host, port, log level)
├── shared/
│   └── USER.md              # Shared user context (all agents see this)
└── agents/
    └── tars/
        ├── agent.yaml       # Model and channel config
        └── soul.md          # Agent personality
```

## Configure Your Agent

### Personality (`soul.md`)

Edit `~/.smolclaw/agents/tars/soul.md` to define your agent's personality:

```markdown
# TARS

You are TARS, a personal virtual assistant.

## Voice
- Direct and concise
- Dry humor when appropriate
- Always helpful, never verbose
```

### Model & Settings (`agent.yaml`)

Edit `~/.smolclaw/agents/tars/agent.yaml`:

```yaml
name: tars
model: claude-sonnet-4-6
memory:
  enabled: true
  cross_agent: false
```

Available models: `claude-opus-4-6`, `claude-sonnet-4-6`, `claude-haiku-4-5-20251001`

## Start the Gateway

```bash
smolclaw up
```

This starts:

- All configured agents
- Channel adapters (Telegram, etc.)
- Cron scheduler
- REST API + dashboard at `http://localhost:7890`

## Send a Message

In another terminal:

```bash
smolclaw send tars "What can you help me with?"
```

Or use the REST API:

```bash
curl -X POST http://localhost:7890/api/agents/tars/send \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello!"}'
```

## Check System Health

```bash
smolclaw doctor
```

This verifies Python version, Claude CLI, dependencies, agent configs, memory database, and port availability.

## What's Next

- [Add Telegram](guides/channels.md) — connect your agent to a Telegram bot
- [Add memory](guides/memory.md) — give your agent persistent knowledge
- [Schedule jobs](guides/scheduler.md) — set up recurring tasks with cron
- [Add more agents](guides/agents.md) — run multiple agents from one process
