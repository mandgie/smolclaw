# Changelog

All notable changes to smolclaw are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- **Extensible channel plugin system** — `register_channel()` for programmatic registration, entry-point discovery via `smolclaw.channels` for third-party packages. Resolution order: built-in → custom → entry points. `list_channel_types()` for enumeration.
- **Webhook channel** — Outgoing HTTP POST channel for delivering messages to Slack webhooks, Discord, or custom APIs. Zero dependencies.
- **Message hooks** — Pre-route and post-route hook system at the router level. Hooks can modify messages, transform responses, short-circuit routing, redirect to different agents, or run side effects like logging. HookRegistry with named hooks, error isolation, and GET /api/hooks endpoint.
- **Manual job trigger** — `smolclaw cron run <job_id>` to manually trigger a scheduled job via the running gateway. Also adds `POST /api/cron/jobs/{job_id}/trigger` API endpoint.
- **Dashboard agent detail view** — click an agent card → Details tab shows config, memory stats, skills, peers, soul, operational rules, and context files in collapsible sections
- **Enhanced agent detail API** — `GET /api/agents/{name}` now returns full soul, agents_md, skill names, config details, peers, and context file content
- **OpenTelemetry tracing** — optional OTEL instrumentation for message routing, LLM calls, memory operations, and cron jobs. Zero overhead when disabled. `pip install smolclaw[otel]`. Follows GenAI semantic conventions.
- **API key authentication** — optional Bearer token auth for the REST API. Set `api_key` in config.yaml. Health and dashboard remain public. Uses constant-time comparison.
- **py.typed marker** — PEP 561 typed package marker for downstream type checking
- **Cross-agent awareness** — agents see peer agents in system prompt with API-based messaging
- **Smart send** — `smolclaw send` uses running gateway API when available, falls back to temporary gateway
- **Memory APIs** — search (`GET /api/agents/{name}/memory/search`), add-fact (`POST .../facts`), stats (`GET .../stats`), and CLI commands (`smolclaw memory search/list/stats/add/delete`)
- **Codecov CI integration** — coverage reports uploaded on every push/PR
- `[all]`, `[otel]`, `[otel-otlp]`, `[discord]`, `[slack]` optional dependency extras

### Fixed
- **Telegram auth with string user IDs** — `authorized_users` now correctly handles both int and string IDs in the polling handler (previously, the inner auth check only matched ints, ignoring string IDs added for multi-platform support)
- **`trigger_job` now suppresses NO_SUGGESTIONS** — manual job triggers via `smolclaw cron run` filter the NO_SUGGESTIONS sentinel, consistent with the scheduled loop (previously delivered the sentinel text to Telegram)
- Replaced deprecated `asyncio.get_event_loop()` with `get_running_loop()` in scheduler crash recovery
- **Graceful config error handling** — malformed YAML, non-mapping agent.yaml, and unreadable skill/context files now produce clear error messages instead of crashing the gateway

### Changed
- `ChannelConfig.authorized_users` broadened to `list[int | str]` for multi-platform support (Slack/Discord string user IDs)
- `ChannelConfig.app_token_env` field added for dual-token auth patterns (Slack Socket Mode)
- Comprehensive documentation overhaul — all 10 docs files synced with current ~5300-line, 14-module codebase
- CI now tests with `[all]` extras to cover sqlite-vec and watchfiles code paths
- 807 tests, 98% coverage (up from 524 at v0.1.0)

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
