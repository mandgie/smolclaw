<p align="center">
  <h1 align="center">smolclaw</h1>
  <p align="center">Lightweight multi-agent framework for personal AI assistants</p>
</p>

<p align="center">
  <a href="https://github.com/mandgie/smolclaw/actions/workflows/ci.yml"><img src="https://github.com/mandgie/smolclaw/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
<a href="https://pypi.org/project/smolclaw/"><img src="https://img.shields.io/pypi/v/smolclaw" alt="PyPI"></a>
  <a href="https://pypi.org/project/smolclaw/"><img src="https://img.shields.io/pypi/pyversions/smolclaw" alt="Python"></a>
  <a href="https://github.com/mandgie/smolclaw/blob/main/LICENSE"><img src="https://img.shields.io/github/license/mandgie/smolclaw" alt="License"></a>
  <a href="https://mandgie.github.io/smolclaw"><img src="https://img.shields.io/badge/docs-mkdocs-blue" alt="Docs"></a>
</p>

---

Run multiple AI agents — each with its own personality, skills, and channels — from a single process. Agents are defined as folders with markdown files. No code required.

**Not another enterprise orchestration framework.** smolclaw is for people who want a personal AI assistant that runs on their laptop — not a distributed system that needs a DevOps team. ~10 modules, filesystem-as-config, zero boilerplate.

## Features

- **Filesystem-as-config** — Drop a folder, get an agent. `soul.md` for personality, `agent.yaml` for model/channels, `skills/` for capabilities.
- **Single gateway process** — All agents, channels, scheduler, and API run in one async process. No microservices, no Docker, no infra.
- **Telegram integration** — Each agent gets its own Telegram bot with typing indicators, markdown rendering, and user authorization.
- **Cron scheduler** — Schedule jobs with cron expressions. Jobs route through the same message bus as everything else.
- **Namespaced memory** — Shared SQLite database with per-agent isolation. Opt-in cross-agent memory sharing.
- **REST API + dashboard** — FastAPI on `:7890` with agent management, messaging, and a built-in dark-mode dashboard.
- **Claude SDK powered** — Built on Anthropic's Claude Agent SDK with session management and tool support.

## Quick Start

```bash
pip install smolclaw
smolclaw init --agent tars
# Edit ~/.smolclaw/agents/tars/soul.md — give your agent a personality
smolclaw up
```

This creates a full project at `~/.smolclaw/` with your first agent and starts the gateway. The API + dashboard will be at `http://localhost:7890`.

## How Agents Work

Each agent is a folder:

```
~/.smolclaw/agents/tars/
├── agent.yaml       # Model, channels, memory config
├── soul.md          # Personality & voice
├── agents.md        # Operational rules & tool access
├── skills/          # Folder per skill (or symlinks to shared/)
├── context/         # Extra .md files loaded into system prompt
├── channels/        # Channel credentials (*.env files)
└── prompts/         # Templates for scheduled jobs
```

The system prompt is assembled automatically from these files. Change a file, restart, and the agent updates.

### Example agent.yaml

```yaml
name: tars
model: claude-opus-4-6
channels:
  telegram:
    token_env: TARS_TELEGRAM_TOKEN
    authorized_users: []
memory:
  enabled: true
  cross_agent: true
```

### Example soul.md

```markdown
# TARS

You are TARS, a personal virtual assistant. Inspired by Interstellar.

## Voice & Tone
- Humor setting: 60%
- Concise and direct. No filler.
- Dry humor when appropriate.
```

## Why smolclaw?

| | smolclaw | CrewAI | LangGraph | OpenAI Agents SDK |
|---|---|---|---|---|
| **Setup** | `pip install` + folder | `pip install` + code | `pip install` + code | `pip install` + code |
| **Config** | Markdown files | Python classes | Python code | Python decorators |
| **Agents defined as** | Folders with `.md` files | Python code | Graph nodes | Python classes |
| **Multi-model** | Per-agent model selection | Per-agent | Per-node | OpenAI only |
| **Channels** | Telegram built-in, API | No built-in | No built-in | No built-in |
| **Scheduler** | Built-in cron | No built-in | No built-in | No built-in |
| **Dashboard** | Built-in | Studio (paid) | LangSmith (paid) | No built-in |
| **Memory** | Built-in SQLite | External | External | External |
| **Code size** | ~1200 lines | ~15K+ lines | ~25K+ lines | ~5K+ lines |
| **Focus** | Personal assistant | Enterprise teams | Workflows | General agents |

**smolclaw is opinionated:** one process, filesystem-as-config, batteries-included. If you want a personal AI assistant that just works — start here.

## Architecture

```
Gateway (single process)
├── Agent: tars     (Opus, Telegram, cross-agent memory)
├── Agent: coach    (Sonnet, no channel, isolated memory)
├── Scheduler       (croniter, fires through router)
├── API             (FastAPI :7890, serves dashboard)
└── Router          (any source → correct agent → response)
```

All messages — whether from Telegram, the API, the CLI, or the scheduler — flow through the same router.

## CLI

```bash
smolclaw init                        # Initialize project (first run)
smolclaw up                          # Start gateway (all agents + API)
smolclaw status                      # Show agents, jobs, config, issues
smolclaw doctor                      # Check system health and dependencies
smolclaw add <name>                  # Scaffold a new agent
smolclaw remove <name>               # Remove an agent (with confirmation)
smolclaw list                        # List discovered agents
smolclaw send <agent> "message"      # Send a one-shot message
smolclaw logs                        # Tail the gateway log file
smolclaw cron list                   # List scheduled jobs
smolclaw cron add \
  --agent tars \
  --schedule "0 8 * * 1-5" \
  --prompt "morning briefing"        # Add a cron job
smolclaw add-skill <agent> <skill>   # Symlink shared skill to agent
smolclaw version                     # Show version
```

## Dashboard

A built-in dark-mode dashboard runs at `http://localhost:7890` when the gateway starts. Shows agent status, config, and lets you send messages.

## Development

```bash
git clone https://github.com/mandgie/smolclaw.git
cd smolclaw
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run tests
pytest

# Lint
ruff check smolclaw/
ruff format --check smolclaw/
```

## Project Structure

```
smolclaw/              # Python package
├── gateway.py         # Single-process orchestrator
├── agent.py           # Agent class (loads identity, wraps Claude SDK)
├── router.py          # Message routing
├── channel.py         # Channel adapters (Telegram)
├── memory.py          # Namespaced SQLite memory
├── scheduler.py       # Cron scheduler (croniter)
├── api.py             # FastAPI REST endpoints
├── config.py          # Filesystem-based agent discovery
├── cli.py             # Click CLI
└── dashboard/
    └── index.html     # Single-file dashboard
```

## Roadmap

- [x] MCP server support (stdio/SSE/HTTP — Claude SDK managed)
- [x] Extended thinking & effort config
- [x] REST API + dark-mode dashboard
- [x] Cron scheduler with validation
- [x] CLI: init, status, doctor, add, remove, add-skill, logs
- [ ] Session persistence (save/resume per agent per chat)
- [ ] CLI interactive REPL (`smolclaw chat`)
- [ ] Vector search in memory (sqlite-vec embeddings)
- [ ] Hot-reload on config changes (no restart needed)
- [ ] Multiple Telegram bots (one per agent)
- [ ] Cross-agent messaging
- [ ] Discord / Slack channel adapters
- [ ] PyPI publish

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

[MIT](LICENSE)
