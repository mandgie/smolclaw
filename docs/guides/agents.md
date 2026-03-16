# Agents

An agent in smolclaw is a folder. Drop a folder in `~/.smolclaw/agents/`, add a few markdown files, and you have an agent.

## Agent Directory Structure

```
~/.smolclaw/agents/tars/
├── agent.yaml       # Required — model, channels, memory config
├── soul.md          # Personality and voice
├── agents.md        # Operational rules and tool access
├── skills/          # One folder per skill (or symlinks to shared/)
│   └── remindctl/
│       └── SKILL.md
├── context/         # Extra .md files loaded into system prompt
│   └── COMPANY.md
├── channels/        # Channel credentials (*.env files)
│   └── telegram.env
├── prompts/         # Templates for scheduled jobs
│   └── morning-briefing.md
└── sessions/        # Session state (auto-managed)
```

## Configuration (`agent.yaml`)

```yaml
name: tars
model: claude-opus-4-6

# Limits and safety
max_turns: 25                    # Cap agent turns per query
max_budget_usd: 5.0             # Per-run spending limit in USD

# Fallback and recovery
fallback_model: claude-sonnet-4-6  # Used if primary model unavailable
enable_file_checkpointing: true # Crash recovery via file checkpoints

# Structured output (optional)
# output_format:
#   type: json
#   schema:
#     type: object
#     properties:
#       answer: { type: string }

channels:
  telegram:
    token_env: TARS_TELEGRAM_TOKEN
    authorized_users: [123456789]

memory:
  enabled: true
  cross_agent: true   # Can search other agents' memory
```

### Fields

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | string | required | Agent identifier |
| `model` | string | `claude-sonnet-4-6` | Claude model to use |
| `max_turns` | int | none | Max agent turns per query (prevents runaway) |
| `max_budget_usd` | float | none | Per-run spending limit in USD |
| `fallback_model` | string | none | Fallback model if primary unavailable |
| `output_format` | dict | none | Structured JSON output schema |
| `enable_file_checkpointing` | bool | `false` | Enable crash recovery checkpoints |
| `channels` | dict | `{}` | Channel configurations |
| `memory.enabled` | bool | `true` | Enable persistent memory |
| `memory.cross_agent` | bool | `false` | Search across agent boundaries |

## System Prompt Assembly

The system prompt is built automatically by concatenating these files (in order):

1. **`shared/USER.md`** — shared context about the user (all agents see this)
2. **`soul.md`** — agent personality and voice
3. **`agents.md`** — operational rules, tool access, responsibilities
4. **`skills/*/SKILL.md`** — all skill files from the skills directory
5. **`context/*.md`** — all context files
6. **Peer agents** — names and models of other agents in the gateway
7. **Runtime section** — today's date, agent name, model, workspace path

With [hot-reload](../architecture.md) enabled (requires `pip install smolclaw[watch]`), changes to any of these files take effect immediately — no restart needed. The gateway watches for file changes and automatically rebuilds the system prompt.

## Adding an Agent

Use the CLI:

```bash
smolclaw add coach --model claude-sonnet-4-6
```

Or manually create the directory:

```bash
mkdir -p ~/.smolclaw/agents/coach
```

Then add `agent.yaml` and `soul.md`.

## Removing an Agent

```bash
smolclaw remove coach
```

This deletes the agent directory after confirmation. Use `-y` to skip confirmation.

## Skills

Skills are folders containing a `SKILL.md` file. Place them in the agent's `skills/` directory or share them across agents using symlinks.

### Shared Skills

Store reusable skills in `~/.smolclaw/shared/skills/` and link them:

```bash
smolclaw add-skill tars remindctl
```

This creates a symlink from `agents/tars/skills/remindctl` to `shared/skills/remindctl`.

### Writing a Skill

Create a folder with a `SKILL.md`:

```
~/.smolclaw/shared/skills/weather/
└── SKILL.md
```

The `SKILL.md` content is injected into the agent's system prompt. It should describe what the skill does and how to use it.

## Multiple Agents

smolclaw runs all agents in a single process. Each agent has:

- Its own Claude SDK session (isolated)
- Its own working directory (cwd set to agent folder)
- Its own memory namespace (shared DB, scoped by agent name)
- Its own channels and skills

```bash
smolclaw list
```

Shows all discovered agents with their model, channels, and skills.
