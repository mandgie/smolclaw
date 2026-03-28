# Changelog

All notable changes to smolclaw are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

## [0.2.1] — 2026-03-28

### Added
- **Shell completion** — `smolclaw completion bash|zsh|fish` generates tab-completion scripts for all smolclaw commands. Supports eval-on-the-fly or saving to file for faster shell startup.
- **Linux systemd install** — `smolclaw install` now works on Linux, generating a systemd user service (`~/.config/systemd/user/smolclaw.service`) with auto-restart on failure. Previously macOS-only (LaunchAgent). `uninstall` updated to match. Gateway restart logic also supports systemd.
- **`create-skill` CLI command** — `smolclaw create-skill my-tool` scaffolds a new skill directory with a properly formatted SKILL.md containing YAML frontmatter (name, description) and placeholder sections. Supports `--agent` flag to create directly in an agent's skills/ directory, and `-d` for custom descriptions. Shared skills (default) can then be linked to agents via `add-skill`.
- **Gateway uptime in health endpoint** — `GET /api/health` now returns `uptime_seconds` and `started_at` fields for monitoring how long the gateway has been running. Useful for health dashboards and debugging restarts.
- **`--telegram` flag for `init` and `add`** — `smolclaw init --telegram TOKEN` and `smolclaw add NAME --telegram TOKEN` auto-configure Telegram: creates `channels/telegram.env` with the bot token and sets up the Telegram channel in `agent.yaml`. Eliminates the #1 setup friction point — no more manual env file creation or YAML editing.
- **`doctor` channel token validation** — The `doctor` command now checks that channel token env vars (e.g. `TARS_TELEGRAM_TOKEN`) are actually set, either in the process environment or in the agent's `channels/*.env` files. Catches the most common misconfiguration (forgetting to set the Telegram token). Gracefully handles malformed YAML, non-dict channel configs, and unreadable env files.
- **`memory clear` CLI command** — `smolclaw memory clear <agent>` permanently deletes all facts and conversation chunks for an agent. Shows entry count before deletion, requires confirmation (or `--yes` to skip). Other agents' memory is unaffected.
- **`ChannelConfig` in public API** — `ChannelConfig` is now exported from the top-level `smolclaw` package, making it available for custom channel authors who need to type-hint their constructors.
- **`examples/README.md`** — Complete walkthrough for the example two-agent setup: file structure, customization guide, Telegram setup, and key concepts explained.

### Fixed
- **Scheduler CancelledError resilience** — The Claude Agent SDK leaks `CancelledError` from anyio cancel scopes at arbitrary `await` points. A single leaked cancellation would kill the scheduler loop, stopping all cron jobs until gateway restart. Now the scheduler absorbs spurious cancellations and continues running. New `_drain_cancellation()` helper handles the SDK's pattern of firing `cancel()` multiple times via nested scopes. Production-tested fix — prevented 5+ scheduler deaths over 2 weeks.
- **Telegram polling watchdog** — `python-telegram-bot`'s updater loop can silently stop without raising errors, leaving the process alive but unable to receive messages. Added a watchdog that checks `updater.running` every 30s and auto-restarts polling (up to 3 consecutive failures). Also added error handlers for handler-level and network-level Telegram errors. Production-tested — prevents multi-day Telegram outages.
- **SDK disconnect cancel scope isolation** — `Agent._disconnect_stale()` now runs `disconnect()` in an isolated background `asyncio.Task` instead of the caller's task. The SDK's anyio cancel scope previously leaked into the caller, killing Telegram polling and scheduler sleep. Task reference stored to prevent GC warnings.
- **WebSocket broadcast CancelledError** — `asyncio.CancelledError` is a `BaseException`, not `Exception`. The broadcast handler's `except Exception` missed it, letting leaked SDK cancel scopes kill the WebSocket manager.

### Changed
- `install`/`uninstall` commands now support both macOS (LaunchAgent) and Linux (systemd). Unsupported platforms get a clear error instead of "macOS only".
- SECURITY.md updated for v0.2.1 supported versions.

## [0.2.0] — 2026-03-20

### Added
- **Dashboard WebSocket live updates** — Dashboard now connects via WebSocket (`/ws`) for instant updates instead of 10-second polling. Job completions, agent config changes, and API mutations broadcast events to all connected clients. Automatic reconnection with polling fallback when WebSocket is unavailable. Status indicator shows "● live" or "○ polling". New `WebSocketManager` class, health endpoint includes `ws_connections` count.
- **Cron job editing** — `smolclaw cron edit <job_id>` to modify schedule, prompt, delivery, session mode, or enabled state of existing jobs without remove+re-add. Also adds `Scheduler.edit_job()` method and `PUT /api/cron/jobs/{id}` REST endpoint. Validates new cron expressions before applying, recomputes `next_run` when schedule changes or job is re-enabled.
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
- **Job enable/disable API** — `POST /api/cron/jobs/{id}/enable` and `.../disable` endpoints for managing job state at runtime via the API (previously CLI-only). Also adds `Scheduler.enable_job()` and `disable_job()` methods.
- **Memory CRUD** — complete REST API for facts: `GET /api/agents/{name}/memory/facts/{id}` (retrieve), `PUT .../facts/{id}` (update content/category with FTS5 + vector re-sync). Also adds `Memory.get_fact()` and `Memory.update_fact()` methods. CLI commands: `smolclaw memory get <agent> <id>` and `smolclaw memory update <agent> <id> --content "..." -c category`.
- **Agent export/import** — `smolclaw export <agent>` creates a portable `.tar.gz` archive with all agent files (config, soul, skills, prompts, context). `smolclaw import <archive>` restores it on any machine. Follows symlinks to include shared skills. Excludes sessions and `.env` secrets by default (`--include-env` to override). Supports `--rename` for importing under a different name.
- **`--version` CLI flag** — `smolclaw --version` now works alongside the existing `smolclaw version` command (standard Click pattern).
- **Codecov CI integration** — coverage reports uploaded on every push/PR
- `[all]`, `[otel]`, `[otel-otlp]`, `[discord]`, `[slack]` optional dependency extras

### Fixed
- **Disabled jobs lost on restart** — `load_jobs()` filtered out disabled and promptless jobs from `self.jobs`, then `save_jobs()` wrote only that filtered list back to disk — permanently deleting disabled jobs. Now all valid jobs are loaded (disabled ones are kept but not scheduled).
- **Atomic file writes for jobs.json** — `save_jobs()` now writes to a temp file and renames, preventing file corruption if the process crashes mid-write.
- **Telegram auth with string user IDs** — `authorized_users` now correctly handles both int and string IDs in the polling handler (previously, the inner auth check only matched ints, ignoring string IDs added for multi-platform support)
- **`trigger_job` now suppresses NO_SUGGESTIONS** — manual job triggers via `smolclaw cron run` filter the NO_SUGGESTIONS sentinel, consistent with the scheduled loop (previously delivered the sentinel text to Telegram)
- **`enable_job` stale next_run** — re-enabling a disabled job kept its old `next_run` timestamp (potentially hours/days in the past), causing an unexpected immediate fire. Now always recomputes `next_run` from the current time.
- **`trigger_job` skipped session cleanup** — manually triggered isolated-mode jobs (`smolclaw cron run`) didn't disconnect the SDK session afterward, leaving stale connections that accumulate CPU and file descriptors. Now mirrors the scheduled loop's cleanup behavior.
- Replaced deprecated `asyncio.get_event_loop()` with `get_running_loop()` in scheduler crash recovery
- **Graceful config error handling** — malformed YAML, non-mapping agent.yaml, and unreadable skill/context files now produce clear error messages instead of crashing the gateway
- **`split_message` oversized line bug** — single lines longer than `max_len` (e.g. very long URLs or code lines) were not split, producing chunks that exceed the Telegram 4000-char limit. Now splits at word boundaries when possible, hard character-boundary as fallback. Every chunk is guaranteed ≤ `max_len`.

### Changed
- `ChannelConfig.authorized_users` broadened to `list[int | str]` for multi-platform support (Slack/Discord string user IDs)
- `ChannelConfig.app_token_env` field added for dual-token auth patterns (Slack Socket Mode)
- **Cron job execution timing** — both scheduled and manually triggered jobs now log their execution duration (e.g. "job 'heartbeat' completed in 42.3s")
- Comprehensive documentation overhaul — all 10 docs files synced with current ~6300-line, 14-module codebase
- CI now tests with `[all]` extras to cover sqlite-vec and watchfiles code paths
- 963 tests, 98% coverage (up from 524 at v0.1.0). agent.py and scheduler.py at 100%.
- Publish workflow now gates on CI (lint + tests must pass before PyPI release)

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
