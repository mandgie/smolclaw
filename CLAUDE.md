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
├── Hooks (pre/post-route middleware on all messages)
├── FileWatcher (hot-reload on config/skill changes)
├── API (FastAPI on :7890, serves dashboard)
└── Router (any source → correct agent → response)
```

## Key Design Decisions

- **Filesystem-as-config**: skills in folder = enabled, soul.md exists = loaded. No config bloat.
- **Progressive skill disclosure**: follows the [Agent Skills spec](https://agentskills.io/specification). Only `name` + `description` from SKILL.md frontmatter are loaded into the system prompt at startup (~100 tokens per skill). The agent reads the full SKILL.md on-demand when it decides to activate a skill.
- **agent.yaml is identity only**: model, channels, memory settings. No skills, no jobs.
- **Jobs in separate store**: `shared/cron/jobs.json` — has runtime state (last_run, failures, etc.)
- **Cron routes through same message bus**: scheduled jobs are just another InboundMessage.
- **Shared memory, namespaced**: one SQLite DB, `agent` column on all tables. Cross-agent opt-in.
- **Symlinks for shared skills**: `smolclaw add-skill coach remindctl` creates symlink to shared/.
- **No Gateway WebSocket**: unlike OpenClaw, no central WS server. Just async Python in one process.
- **Agent isolation via cwd**: each agent's Claude SDK session has cwd set to its own directory.

## File Structure

```
smolclaw/              # Python package (~6200 lines, 14 modules)
├── __init__.py        # Package exports (~50 lines)
├── cli.py             # Click CLI: up, chat, add, list, send, cron, memory, export/import, install (~1914 lines)
├── memory.py          # Namespaced SQLite memory: FTS5 + sqlite-vec + hybrid RRF (~620 lines)
├── api.py             # FastAPI REST endpoints + dashboard serving (~668 lines)
├── channel.py         # Channel base + Telegram/Webhook + extensible registry (~486 lines)
├── scheduler.py       # Cron scheduler using croniter, fires through router (~606 lines)
├── gateway.py         # Single process: boots agents, channels, scheduler, API (~336 lines)
├── agent.py           # Agent class: loads identity, builds system prompt, wraps Claude SDK (~307 lines)
├── tracing.py         # Optional OpenTelemetry instrumentation (zero overhead when disabled) (~270 lines)
├── config.py          # Agent discovery from filesystem, YAML loading, Pydantic models (~275 lines)
├── hooks.py           # Pre/post-route message hooks (middleware) (~198 lines)
├── router.py          # InboundMessage/OutboundMessage routing with hooks (~161 lines)
├── watcher.py         # Hot-reload file watcher (watchfiles-based) (~142 lines)
└── dashboard/
    └── index.html     # Single-file dark-mode dashboard (vanilla JS)

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
        │   └── <skill>/
        │       ├── SKILL.md       # Required: YAML frontmatter (name, description) + instructions
        │       ├── scripts/       # Optional: executable code
        │       ├── references/    # Optional: detailed docs
        │       └── assets/        # Optional: templates, resources
        ├── prompts/         # Cron job prompt templates
        ├── context/         # Extra .md files loaded into prompt
        ├── channels/        # *.env files with tokens
        └── sessions/        # Session state
```

## Inspiration & References

- **OpenClaw** (openclaw/openclaw): Full-featured TypeScript agent platform. We took the channel normalization pattern, AGENTS.md/SOUL.md convention, and cron-through-message-bus idea.
- **Nanobot** (HKUDS/nanobot): Ultra-lightweight Python agent. We took the "cron triggers are just messages" pattern and separate job store approach.
- **TARS** (~/.smolclaw/agents/tars/): Magnus's personal assistant, fully running on smolclaw.

## What Works

- [x] Agent discovery from filesystem
- [x] System prompt assembly (USER.md + soul.md + agents.md + skill index + context)
- [x] Progressive skill disclosure (Agent Skills spec — metadata at startup, full SKILL.md on-demand)
- [x] Claude SDK integration with session resume
- [x] Telegram channel adapter (polling, typing indicators, markdown→HTML)
- [x] Message routing (any source → agent → response)
- [x] Namespaced memory (SQLite, per-agent scoping, FTS5, vector search via sqlite-vec)
- [x] Cron scheduler (croniter, fires through router)
- [x] REST API (FastAPI, agent list/detail/send/new-session, cron CRUD, health)
- [x] Dashboard (single HTML file, auto-refresh)
- [x] CLI (up, add, list, send, chat, cron list/add/remove/edit, add-skill, install/uninstall)
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
- [x] Dashboard: agent detail view (click card → Details tab shows config, skills, memory, soul)
- [x] Dashboard: WebSocket live updates instead of polling
- [x] Multiple Telegram bots (one per agent, each with own token — dedup prevents conflicts)
- [x] CLI channel adapter (interactive REPL mode) — `smolclaw chat <agent>`
- [x] LaunchAgent plist generation (`smolclaw install` → auto-start on boot)
- [x] Migrate TARS from ~/.tars/ to run on smolclaw as proof of full migration
- [x] Tests (949 tests, 97% coverage, pytest with mocked Claude SDK)
- [x] OpenTelemetry tracing (optional, zero overhead when disabled)
- [x] Message hooks (pre/post-route middleware)
- [x] Webhook channel adapter (HTTP POST delivery)
- [x] Extensible channel plugin system (entry-point discovery)
- [x] PyPI publish (v0.1.0 on PyPI)

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
