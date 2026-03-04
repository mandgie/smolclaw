# Architecture

## Design Philosophy

smolclaw is deliberately simple:

- **Single process** — no microservices, no Docker, no message queues
- **Filesystem-as-config** — folders and markdown files define agents, not code
- **Everything routes through one bus** — Telegram, API, CLI, cron — same path
- **~1200 lines** — small enough to read, understand, and extend

## System Overview

```
Gateway (single async process)
│
├── Agent: tars
│   ├── Claude SDK session (isolated)
│   ├── System prompt (soul + skills + context)
│   └── Memory namespace
│
├── Agent: coach
│   ├── Claude SDK session (isolated)
│   ├── System prompt (soul + skills + context)
│   └── Memory namespace
│
├── Router
│   └── InboundMessage → Agent.send() → OutboundMessage
│
├── Channels
│   └── TelegramChannel (polling, per-agent)
│
├── Scheduler
│   └── Cron jobs → InboundMessage → Router
│
└── API (FastAPI :7890)
    ├── REST endpoints
    └── Dashboard (single HTML file)
```

## Message Flow

Every message — regardless of source — follows the same path:

```
Source (Telegram / API / CLI / Cron)
  │
  ▼
InboundMessage { agent, text, source, chat_id }
  │
  ▼
Router.route()
  │
  ▼
Agent.send(text)  →  Claude SDK  →  Claude API
  │
  ▼
OutboundMessage { agent, text, source, chat_id }
  │
  ▼
Response callback (send to Telegram / return to API / print to CLI)
```

## Module Map

| Module | Lines | Responsibility |
|---|---|---|
| `gateway.py` | ~150 | Process orchestrator — boots everything, manages lifecycle |
| `agent.py` | ~110 | Wraps Claude SDK — identity, prompt assembly, sessions |
| `router.py` | ~50 | Message routing — source → agent → response callback |
| `channel.py` | ~180 | Channel adapters — Telegram with polling, typing, formatting |
| `memory.py` | ~85 | SQLite memory — facts, chunks, namespaced, WAL mode |
| `scheduler.py` | ~140 | Cron engine — croniter, job state, fires through router |
| `api.py` | ~120 | REST API — FastAPI endpoints, Pydantic models |
| `config.py` | ~95 | Agent discovery — reads filesystem, builds AgentInfo |
| `cli.py` | ~420 | CLI — Click commands for all operations |

## Key Design Decisions

### Filesystem-as-Config

Agents are directories. Skills are folders with a `SKILL.md`. Context is `.md` files in a `context/` folder. This means:

- No config files to learn — just write markdown
- Version control friendly — `git diff` shows personality changes
- Easy to share — zip a folder, send it to someone
- No migration — add a file, restart, done

### Single Gateway Process

Everything runs in one `asyncio` event loop. No inter-process communication, no service discovery, no container orchestration. This limits scale but maximizes simplicity.

### Cron Through the Message Bus

Scheduled jobs don't bypass the router. A cron job creates an `InboundMessage` with `source="cron"` and routes it through the same path as a Telegram message. This means:

- All messages are logged the same way
- Agents don't need to know where a message came from
- Adding a new source is just creating a new `InboundMessage`

### Namespaced Shared Memory

One SQLite database, but each agent only sees its own data by default. Cross-agent search is opt-in per agent. This gives isolation without the overhead of multiple databases.

### Agent Isolation via CWD

Each agent's Claude SDK session has its working directory set to the agent's folder. This means agents can read their own skill files, context, and prompts without path juggling.

## What's Intentionally Missing

- **No distributed execution** — single process, single machine
- **No plugin system** — extend by editing source or adding skills
- **No authentication on API** — designed for local use on your laptop
- **No multi-model routing** — each agent has one model, period
- **No vector search (yet)** — memory uses LIKE queries, sqlite-vec planned
