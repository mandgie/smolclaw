# smolclaw

**Lightweight multi-agent framework for personal AI assistants.**

Run multiple AI agents — each with its own personality, skills, and channels — from a single process. Agents are defined as folders with markdown files. No code required.

---

## Why smolclaw?

Not another enterprise orchestration framework. smolclaw is for people who want a personal AI assistant that runs on their laptop — not a distributed system that needs a DevOps team.

- **~1200 lines of code** — read the whole thing in an afternoon
- **Filesystem-as-config** — folders and markdown files, not Python classes
- **Batteries included** — Telegram, cron, memory, dashboard, API — all built in
- **Claude-native** — built on Anthropic's Claude Agent SDK

| | smolclaw | CrewAI | LangGraph | OpenAI Agents SDK |
|---|---|---|---|---|
| **Setup** | `pip install` + folder | `pip install` + code | `pip install` + code | `pip install` + code |
| **Config** | Markdown files | Python classes | Python code | Python decorators |
| **Channels** | Telegram built-in | No built-in | No built-in | No built-in |
| **Scheduler** | Built-in cron | No built-in | No built-in | No built-in |
| **Dashboard** | Built-in | Studio (paid) | LangSmith (paid) | No built-in |
| **Memory** | Built-in SQLite | External | External | External |
| **Focus** | Personal assistant | Enterprise teams | Workflows | General agents |

## Quick Start

```bash
pip install smolclaw
smolclaw init --agent tars
# Edit ~/.smolclaw/agents/tars/soul.md — give your agent a personality
smolclaw up
```

Your gateway is now running at `http://localhost:7890` with a dashboard, REST API, and your first agent ready to go.

!!! tip "Send a test message"
    ```bash
    smolclaw send tars "Hello, who are you?"
    ```

## Next Steps

- [Getting Started](getting-started.md) — full installation and setup guide
- [Agents](guides/agents.md) — how agents work and how to configure them
- [Channels](guides/channels.md) — connect agents to Telegram
- [CLI Reference](reference/cli.md) — all available commands
