# smolclaw — Development Context

## What This Is

Lightweight multi-agent framework for personal AI assistants. Think "OpenClaw but smol" — built on Claude Agent SDK, Python, single-process gateway architecture.

**Repo:** https://github.com/mandgie/smolclaw
**Author:** Magnus Friberg (mandgie / Saltfish-AB)
**Status:** v0.1.0 — core framework working, tested with Telegram bot

## Architecture

Single gateway process runs everything: agents, channels, scheduler, API.

```
Gateway (one process)
├── Agent: tars (Opus, Telegram, cross-agent memory)
├── Agent: coach (Sonnet, no channel yet, isolated memory)
├── Scheduler (reads shared/cron/jobs.json, fires through router)
├── API (FastAPI on :7890, serves dashboard)
└── Router (any source → correct agent → response)
```

## Key Design Decisions

- **Filesystem-as-config**: skills in folder = enabled, soul.md exists = loaded. No config bloat.
- **agent.yaml is identity only**: model, channels, memory settings. No skills, no jobs.
- **Jobs in separate store**: `shared/cron/jobs.json` — has runtime state (last_run, failures, etc.)
- **Cron routes through same message bus**: scheduled jobs are just another InboundMessage.
- **Shared memory, namespaced**: one SQLite DB, `agent` column on all tables. Cross-agent opt-in.
- **Symlinks for shared skills**: `smolclaw add-skill coach remindctl` creates symlink to shared/.
- **No Gateway WebSocket**: unlike OpenClaw, no central WS server. Just async Python in one process.
- **Agent isolation via cwd**: each agent's Claude SDK session has cwd set to its own directory.

## File Structure

```
smolclaw/              # Python package (~2900 lines, 11 modules)
├── __init__.py        # Version
├── config.py          # Agent discovery from filesystem, YAML loading, Pydantic models
├── agent.py           # Agent class: loads identity, builds system prompt, wraps Claude SDK
├── router.py          # InboundMessage/OutboundMessage routing
├── channel.py         # Channel base class + TelegramChannel adapter
├── memory.py          # Namespaced SQLite memory (FTS5 + vector search)
├── scheduler.py       # Cron scheduler using croniter, fires through router
├── gateway.py         # Single process: boots agents, channels, scheduler, API
├── tracing.py         # Optional OpenTelemetry instrumentation (zero overhead when disabled)
├── api.py             # FastAPI REST endpoints + dashboard serving
├── cli.py             # Click CLI: up, add, list, send, cron, add-skill
└── dashboard/
    └── index.html     # Single-file dark-mode dashboard (Alpine.js-style vanilla JS)

examples/              # Example two-agent setup (tars + coach)
```

## Runtime Directory (~/.smolclaw/)

```
~/.smolclaw/
├── config.yaml
├── shared/
│   ├── USER.md              # Shared user context (all agents see this)
│   ├── memory.db            # Shared DB, namespaced per agent
│   ├── skills/              # Shared skill library
│   └── cron/jobs.json       # All scheduled jobs
└── agents/
    └── <name>/
        ├── agent.yaml       # Model, channels, memory config
        ├── soul.md          # Personality
        ├── agents.md        # Operational rules
        ├── skills/          # Agent-specific (or symlinks to shared)
        ├── prompts/         # Cron job prompt templates
        ├── context/         # Extra .md files loaded into prompt
        ├── channels/        # *.env files with tokens
        └── sessions/        # Session state
```

## Inspiration & References

- **OpenClaw** (openclaw/openclaw): Full-featured TypeScript agent platform. We took the channel normalization pattern, AGENTS.md/SOUL.md convention, and cron-through-message-bus idea.
- **Nanobot** (HKUDS/nanobot): Ultra-lightweight Python agent. We took the "cron triggers are just messages" pattern and separate job store approach.
- **TARS** (~/.tars/): Magnus's existing personal assistant. smolclaw is the framework extracted from TARS's architecture.

## What Works

- [x] Agent discovery from filesystem
- [x] System prompt assembly (USER.md + soul.md + agents.md + skills + context)
- [x] Claude SDK integration with session resume
- [x] Telegram channel adapter (polling, typing indicators, markdown→HTML)
- [x] Message routing (any source → agent → response)
- [x] Namespaced memory (SQLite, per-agent scoping, FTS5, vector search via sqlite-vec)
- [x] Cron scheduler (croniter, fires through router)
- [x] REST API (FastAPI, agent list/detail/send/new-session, cron CRUD, health)
- [x] Dashboard (single HTML file, auto-refresh)
- [x] CLI (up, add, list, send, chat, cron list/add/remove, add-skill, install/uninstall)
- [x] Hot-reload (watchfiles-based file watcher, auto-reloads agent config/skills/context on change)
- [x] Cross-agent awareness (peer info in system prompts, API-based inter-agent messaging)
- [x] Smart send (CLI `send` uses running API when available, falls back to temporary gateway)
- [x] Tested: two agents responding in character, Telegram bot working

## What's Next (TODO)

- [x] Vector search in memory (sqlite-vec embeddings, hybrid search with RRF)
- [x] Session persistence (save/resume session IDs per agent per chat)
- [x] Hot-reload on config/skill file changes (watchfiles-based, no restart needed)
- [x] Cron delivery to Telegram (gateway wires scheduler → channel.send via deliver_callback)
- [ ] `smolclaw cron` interactive — let agents manage their own schedule conversationally
- [x] Cross-agent awareness (peer agents injected into system prompts, API-based messaging)
- [ ] Dashboard: agent detail view (click card → see soul, skills, logs, config editor)
- [ ] Dashboard: WebSocket live updates instead of polling
- [ ] Multiple Telegram bots (one per agent, each with own token)
- [x] CLI channel adapter (interactive REPL mode) — `smolclaw chat <agent>`
- [x] LaunchAgent plist generation (`smolclaw install` → auto-start on boot)
- [ ] Migrate TARS from ~/.tars/ to run on smolclaw as proof of full migration
- [x] Tests (539 tests, 96% coverage, pytest with mocked Claude SDK)
- [ ] PyPI publish

## Development

```bash
cd ~/smolclaw
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Test locally
smolclaw --home ~/.smolclaw list
smolclaw --home ~/.smolclaw up
```

## Important Notes

- `os.environ.pop("CLAUDECODE", None)` in agent.py — required to avoid nested session detection when running from inside Claude Code or cron
- Channel env files are loaded by gateway at startup from `agents/<name>/channels/*.env`
- Dashboard auto-refreshes every 10 seconds via JS polling
- The examples/ directory is reference only — runtime lives in ~/.smolclaw/
