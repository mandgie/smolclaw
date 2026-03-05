# CLI Reference

smolclaw provides a comprehensive command-line interface built with [Click](https://click.palletsprojects.com/).

## Global Options

```bash
smolclaw [--home PATH] <command>
```

| Option | Default | Description |
|---|---|---|
| `--home` | `~/.smolclaw` or `$SMOLCLAW_HOME` | Path to smolclaw home directory |

## Commands

### `init`

Initialize a new smolclaw project.

```bash
smolclaw init [--agent NAME] [--model MODEL]
```

| Option | Default | Description |
|---|---|---|
| `--agent` | `myagent` | Name of the first agent to create |
| `--model` | `claude-sonnet-4-6` | Model for the first agent |

Creates `~/.smolclaw/` with config, shared directory, and first agent.

---

### `up`

Start the gateway — all agents, channels, scheduler, and API.

```bash
smolclaw up [--no-api]
```

| Option | Description |
|---|---|
| `--no-api` | Start without the REST API server |

Auto-scaffolds on first run if the home directory doesn't exist.

---

### `status`

Show system overview — agents, jobs, memory, API config.

```bash
smolclaw status
```

Displays each agent's model, channels, skills, memory status, MCP servers, thinking config, and max_turns. Flags issues like missing `soul.md`.

---

### `doctor`

Check system health and diagnose problems.

```bash
smolclaw doctor
```

Checks:

- Python version (3.11+ required)
- Claude CLI availability
- Required and optional dependencies
- Home directory and agent configs
- Memory database health
- API port availability

---

### `add`

Scaffold a new agent.

```bash
smolclaw add <name> [--model MODEL]
```

| Argument/Option | Default | Description |
|---|---|---|
| `name` | required | Agent name |
| `--model` | `claude-sonnet-4-6` | Model to use |

Creates the agent directory with `agent.yaml` and `soul.md`.

---

### `remove`

Remove an agent.

```bash
smolclaw remove <name> [--yes]
```

| Option | Description |
|---|---|
| `-y`, `--yes` | Skip confirmation prompt |

---

### `list`

List all discovered agents.

```bash
smolclaw list
```

Shows agent name, model, channels, and skill count.

---

### `send`

Send a one-shot message to an agent.

```bash
smolclaw send <agent> <message>
```

Starts a temporary gateway, routes the message, prints the response, and exits.

---

### `logs`

Show gateway log output.

```bash
smolclaw logs [-n LINES] [-f]
```

| Option | Default | Description |
|---|---|---|
| `-n`, `--lines` | `50` | Number of lines to show |
| `-f`, `--follow` | off | Tail the log file continuously |

---

### `config`

View or modify gateway configuration.

```bash
smolclaw config                      # Show current config
smolclaw config get <key>            # Get a specific value
smolclaw config set <key> <value>    # Set a value (validates before writing)
```

**Subcommands:**

| Subcommand | Description |
|---|---|
| *(none)* | Display full `config.yaml` contents |
| `get <key>` | Get a single configuration value |
| `set <key> <value>` | Set a value with validation |

`config set` validates the new value against the `GatewayConfig` schema before writing. For example, setting `port` to a value outside 1–65535 will be rejected.

```bash
# Examples
smolclaw config                      # Show all config
smolclaw config get port             # → 7890
smolclaw config set port 8080        # Updates config.yaml
smolclaw config set host 0.0.0.0     # Bind to all interfaces
smolclaw config set log_level DEBUG  # More verbose logging
```

---

### `add-skill`

Link a shared skill to an agent.

```bash
smolclaw add-skill <agent> <skill>
```

Creates a symlink from `agents/<agent>/skills/<skill>` to `shared/skills/<skill>`.

---

### `version`

Show the installed smolclaw version.

```bash
smolclaw version
```

---

### `cron list`

List all scheduled jobs.

```bash
smolclaw cron list
```

---

### `cron add`

Add a new scheduled job.

```bash
smolclaw cron add --agent NAME --schedule EXPR --prompt TEXT [OPTIONS]
```

| Option | Required | Description |
|---|---|---|
| `--agent` | yes | Target agent |
| `--schedule` | yes | Cron expression |
| `--prompt` | yes | Prompt text or path to prompt file |
| `--delivery` | no | Delivery channel (e.g., `telegram`) |
| `--chat-id` | no | Chat ID for delivery |
| `--id` | no | Job ID (auto-generated if omitted) |

---

### `cron remove`

Remove a scheduled job.

```bash
smolclaw cron remove <job_id>
```
