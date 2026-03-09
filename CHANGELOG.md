# Changelog

All notable changes to smolclaw are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- **Dashboard agent detail view** — click an agent card → Details tab shows config, memory stats, skills, peers, soul, operational rules, and context files in collapsible sections
- **Enhanced agent detail API** — `GET /api/agents/{name}` now returns full soul, agents_md, skill names, config details, peers, and context file content
- **OpenTelemetry tracing** — optional OTEL instrumentation for message routing, LLM calls, memory operations, and cron jobs. Zero overhead when disabled. Install with `pip install smolclaw[otel]`. Follows GenAI semantic conventions.
- **API key authentication** — optional Bearer token auth for the REST API. Set `api_key` in config.yaml. Health and dashboard remain public. Uses constant-time comparison.
- **py.typed marker** — PEP 561 typed package marker for downstream type checking
- **Cross-agent awareness** — agents see peer agents in system prompt with API-based messaging
- **Smart send** — `smolclaw send` uses running gateway API when available, falls back to temporary gateway
- **Memory search API** — `GET /api/agents/{name}/memory/search` with auto/vector/hybrid modes
- **Memory add-fact API** — `POST /api/agents/{name}/memory/facts` for programmatic fact ingestion
- **Memory stats API** — `GET /api/agents/{name}/memory/stats` for monitoring
- **CLI memory commands** — `smolclaw memory search/list/stats/add/delete` for managing agent memory from the terminal
- Doctor edge case tests (Python version, Claude CLI, packages, memory DB, port conflicts)
- `[all]` optional dependency extra — `pip install smolclaw[all]` for all features
- `[otel]` and `[otel-otlp]` optional extras for OpenTelemetry tracing

### Fixed
- Replaced deprecated `asyncio.get_event_loop()` with `get_running_loop()` in scheduler crash recovery callback
- Scheduler crash recovery now handles missing event loop gracefully

### Changed
- CI now tests with `[all]` extras to cover sqlite-vec and watchfiles code paths
- Updated README — REST API examples section, accurate line counts, roadmap updated
- Updated CLAUDE.md TODO — marked cron delivery, tests, and cross-agent as done
- Test coverage improved: scheduler 89%→97%, tracing 88%→93%, memory 91%→98%. 630 tests, 96% overall.

## [0.1.0] — 2026-03-07

First feature-complete release. Everything works end-to-end: agents, channels, scheduler, memory, API, dashboard, CLI.

### Added
- **Vector search** — sqlite-vec integration with FTS5 full-text search and hybrid retrieval via Reciprocal Rank Fusion (RRF)
- **Hot-reload** — watchfiles-based file watcher for agent config, skills, and context changes (no restart needed)
- **Session persistence** — save/resume session IDs per agent per chat
- **Interactive REPL** — `smolclaw chat <agent>` with `/help`, `/new`, `/cost`, `/quit` commands
- **LaunchAgent install** — `smolclaw install/uninstall` for macOS auto-start on login
- **MCP server support** — stdio/SSE/HTTP via Claude SDK, configurable in agent.yaml
- **Extended thinking** — thinking budget, effort level, betas config per agent
- **Budget limits** — per-run spending limits, fallback models, file checkpointing
- **FTS5 search** — full-text search in memory module with BM25 ranking
- **Cost tracking** — per-query cost, usage, and duration metrics
- **Dashboard chat** — send messages to agents from the web dashboard
- **Session history** — browse past sessions in dashboard
- **REST API** — FastAPI on :7890 with agent management, messaging, cron CRUD, health check
- **Dashboard** — single-file dark-mode dashboard with auto-refresh
- **Cron scheduler** — croniter-based with delivery to Telegram
- **Telegram channel** — polling, typing indicators, markdown→HTML, user authorization
- **Memory** — namespaced SQLite with per-agent isolation, cross-agent opt-in
- **CLI** — init, up, chat, status, doctor, add, remove, list, send, logs, config, cron, add-skill, version
- **Agent discovery** — filesystem-based, YAML config, markdown identity files
- **System prompt assembly** — USER.md + soul.md + agents.md + skills + context

### Infrastructure
- GitHub Actions CI (lint + test on Python 3.11/3.12/3.13)
- PyPI publish workflow (trusted publishing)
- MkDocs documentation site
- 524 tests, 96% coverage
- ruff linting and formatting
- CONTRIBUTING.md and issue templates

## [0.0.1] — 2026-02-21

### Added
- Initial framework: gateway, agents, channels, memory, scheduler, API, dashboard
- MIT license
