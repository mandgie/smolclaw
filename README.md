# smolclaw

Lightweight multi-agent framework for personal AI assistants.

## Quick Start

```bash
pip install smolclaw
smolclaw add myagent
smolclaw up
```

## What is this?

smolclaw lets you run multiple AI agents — each with its own personality, skills, and Telegram bot — from a single process. Agents are defined as folders with markdown files. No code required.

## Architecture

```
~/.smolclaw/
├── config.yaml              # Gateway config
├── shared/
│   ├── USER.md              # Who you are (shared across agents)
│   ├── memory.db            # Shared memory, namespaced per agent
│   └── cron/jobs.json       # Scheduled jobs
└── agents/
    ├── tars/
    │   ├── agent.yaml       # Model, channels
    │   ├── soul.md          # Personality
    │   ├── agents.md        # Rules & tools
    │   └── skills/          # Folder = enabled
    └── coach/
        ├── agent.yaml
        ├── soul.md
        ├── agents.md
        └── skills/
```

## CLI

```bash
smolclaw up                     # Start gateway (all agents + API)
smolclaw add <name>             # Scaffold a new agent
smolclaw list                   # List agents
smolclaw send <agent> "msg"     # One-shot message
smolclaw cron list              # List scheduled jobs
smolclaw cron add --agent tars --schedule "0 8 * * 1-5" --prompt "morning briefing"
smolclaw add-skill <agent> <skill>   # Link shared skill to agent
```

## Dashboard

Runs at `http://localhost:7890` when the gateway starts.
