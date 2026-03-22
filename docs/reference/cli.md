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
smolclaw init [--agent NAME] [--model MODEL] [--telegram TOKEN]
```

| Option | Default | Description |
|---|---|---|
| `--agent` | `myagent` | Name of the first agent to create |
| `--model` | `claude-sonnet-4-6` | Model for the first agent |
| `--telegram` | — | Telegram bot token from @BotFather — auto-configures Telegram channel |

Creates `~/.smolclaw/` with config, shared directory, and first agent. When `--telegram` is provided, automatically creates the `channels/telegram.env` file and configures the Telegram channel in `agent.yaml`.

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

Displays each agent's model, channels, skills, and memory status. When configured, also shows budget limits, fallback model, structured output, and file checkpointing. Flags issues like missing `soul.md`.

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
smolclaw add <name> [--model MODEL] [--telegram TOKEN]
```

| Argument/Option | Default | Description |
|---|---|---|
| `name` | required | Agent name |
| `--model` | `claude-sonnet-4-6` | Model to use |
| `--telegram` | — | Telegram bot token — auto-configures Telegram channel |

Creates the agent directory with `agent.yaml` and `soul.md`. When `--telegram` is provided, also sets up `channels/telegram.env` and configures the channel in `agent.yaml`.

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

Uses the running gateway API when available, falls back to starting a temporary gateway.

---

### `chat`

Start an interactive REPL with an agent.

```bash
smolclaw chat <agent>
```

Opens a persistent conversation session. Type messages and see responses inline. Session state is preserved between runs (use `/new` to reset).

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

### `create-skill`

Scaffold a new skill directory with a SKILL.md template.

```bash
# Create in shared/skills/ (usable by any agent via add-skill)
smolclaw create-skill my-tool

# Create directly in an agent's skills/ directory
smolclaw create-skill my-tool --agent tars

# With a custom description
smolclaw create-skill my-tool -d "Interact with external API"
```

Creates a skill directory with a properly formatted `SKILL.md` containing YAML frontmatter (name, description) and placeholder sections for documentation.

**Options:**
- `--agent AGENT` — Create in the agent's `skills/` directory instead of `shared/skills/`
- `-d, --description TEXT` — Short description for the SKILL.md frontmatter

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

### `cron edit`

Edit an existing scheduled job's fields without remove+re-add.

```bash
smolclaw cron edit <job_id> [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--schedule` | New cron expression |
| `--prompt` | New prompt text or prompt file path |
| `--delivery` | New delivery channel type (e.g. `telegram`) |
| `--chat-id` | New delivery chat ID |
| `--session-mode` | `isolated` or `shared` |

---

### `cron run`

Manually trigger a scheduled job (for testing/debugging).

```bash
smolclaw cron run <job_id>
```

Sends the job's prompt through the gateway API and delivers the response via the configured channel.

---

### `cron enable`

Enable a disabled job.

```bash
smolclaw cron enable <job_id>
```

---

### `cron disable`

Disable a job without removing it.

```bash
smolclaw cron disable <job_id>
```

---

### `cron remove`

Remove a scheduled job.

```bash
smolclaw cron remove <job_id>
```

---

### `memory stats`

Show memory statistics for an agent.

```bash
smolclaw memory stats <agent>
```

---

### `memory list`

List stored facts.

```bash
smolclaw memory list <agent>
```

---

### `memory search`

Search agent memory.

```bash
smolclaw memory search <agent> <query>
```

---

### `memory add`

Add a fact to an agent's memory.

```bash
smolclaw memory add <agent> <fact>
```

---

### `memory get`

Show a single fact by ID.

```bash
smolclaw memory get <agent> <fact_id>
```

---

### `memory update`

Update a fact's content and/or category.

```bash
smolclaw memory update <agent> <fact_id> --content "new text" -c category
```

---

### `memory delete`

Delete a specific fact.

```bash
smolclaw memory delete <agent> <fact_id>
```

---

### `install`

Install smolclaw as a login service that auto-starts and restarts on crash.

```bash
smolclaw install
```

**macOS:** Creates a LaunchAgent plist at `~/Library/LaunchAgents/` and loads it with `launchctl`.

**Linux:** Creates a systemd user service at `~/.config/systemd/user/smolclaw.service` and enables it with `systemctl --user`.

---

### `uninstall`

Remove the login service created by `install`.

```bash
smolclaw uninstall
```

**macOS:** Unloads and removes the LaunchAgent plist.

**Linux:** Stops, disables, and removes the systemd user service.

---

### `completion`

Generate shell tab-completion scripts.

```bash
# Bash
eval "$(smolclaw completion bash)"

# Zsh
eval "$(smolclaw completion zsh)"

# Fish
smolclaw completion fish | source
```

For faster shell startup, save to a file:

```bash
# Bash
smolclaw completion bash > ~/.local/share/bash-completion/completions/smolclaw

# Zsh
smolclaw completion zsh > ~/.zfunc/_smolclaw

# Fish
smolclaw completion fish > ~/.config/fish/completions/smolclaw.fish
```

---

### `update`

Check for and install smolclaw updates.

```bash
smolclaw update
```

Checks the latest GitHub release version and installs it if newer.
