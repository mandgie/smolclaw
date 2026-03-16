# Architecture

## Design Philosophy

smolclaw is deliberately simple:

- **Single process** — no microservices, no Docker, no message queues
- **Filesystem-as-config** — folders and markdown files define agents, not code
- **Everything routes through one bus** — Telegram, API, CLI, cron — same path
- **~3200 lines** — small enough to read, understand, and extend

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
│   ├── TelegramChannel (polling, per-agent)
│   ├── WebhookChannel (HTTP POST delivery)
│   └── Custom channels (entry-point plugins)
│
├── Hooks
│   ├── Pre-route (modify/redirect/short-circuit)
│   └── Post-route (transform responses)
│
├── FileWatcher (hot-reload on config/skill changes)
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
Source (Telegram / Webhook / API / CLI / Cron)
  │
  ▼
InboundMessage { agent, text, source, chat_id }
  │
  ▼
Pre-route hooks (modify, redirect, or short-circuit)
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
Post-route hooks (transform response)
  │
  ▼
Response callback (send to Telegram / return to API / print to CLI)
```

## Module Map

| Module | Lines | Responsibility |
|---|---|---|
| `cli.py` | ~1565 | CLI — Click commands for all operations |
| `memory.py` | ~620 | Memory — SQLite + FTS5 + sqlite-vec vector search + hybrid RRF |
| `api.py` | ~577 | REST API — FastAPI endpoints, Pydantic models, dashboard |
| `channel.py` | ~486 | Channel adapters — Telegram, Webhook, extensible registry |
| `scheduler.py` | ~402 | Cron engine — croniter, job state, delivery, fires through router |
| `gateway.py` | ~336 | Process orchestrator — boots everything, manages lifecycle |
| `agent.py` | ~307 | Wraps Claude SDK — identity, prompt assembly, sessions, MCP |
| `tracing.py` | ~270 | Optional OpenTelemetry instrumentation (zero overhead when off) |
| `config.py` | ~225 | Agent discovery — reads filesystem, builds AgentInfo |
| `hooks.py` | ~198 | Pre/post-route message hooks (middleware) |
| `router.py` | ~161 | Message routing with hooks — source → agent → response |
| `watcher.py` | ~142 | Hot-reload file watcher (watchfiles-based) |

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
- **No multi-model routing** — each agent has one model, period
- **No WebSocket on dashboard** — polling every 10s, works fine for personal use
