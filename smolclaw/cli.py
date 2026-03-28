"""CLI entry point — smolclaw up, add, list, send, cron."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import click
import yaml

DEFAULT_BASE = Path.home() / ".smolclaw"


def get_base_dir(base: str | None = None) -> Path:
    """Resolve the smolclaw home directory from explicit path, env var, or default."""
    if base:
        return Path(base)
    env = os.environ.get("SMOLCLAW_HOME")
    if env:
        return Path(env)
    return DEFAULT_BASE


def _get_version() -> str:
    from . import __version__

    return __version__


@click.group()
@click.version_option(version=_get_version(), prog_name="smolclaw")
@click.option("--home", envvar="SMOLCLAW_HOME", default=None, help="Base directory")
@click.pass_context
def cli(ctx, home):
    """smolclaw — lightweight multi-agent framework."""
    ctx.ensure_object(dict)
    ctx.obj["base"] = get_base_dir(home)


def _setup_telegram(agent_dir: Path, agent_name: str, token: str) -> None:
    """Configure Telegram channel for an agent.

    Creates the channels/telegram.env file with the bot token and updates
    agent.yaml to reference the Telegram channel configuration.

    Args:
        agent_dir: Path to the agent directory.
        agent_name: Name of the agent (used for env var naming).
        token: Telegram bot token from @BotFather.
    """
    env_var = f"{agent_name.upper()}_TELEGRAM_TOKEN"

    # Write token to channels/telegram.env
    env_file = agent_dir / "channels" / "telegram.env"
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text(f"{env_var}={token}\n")

    # Update agent.yaml with Telegram channel config
    yaml_path = agent_dir / "agent.yaml"
    config = (yaml.safe_load(yaml_path.read_text()) or {}) if yaml_path.exists() else {}

    if "channels" not in config or not isinstance(config["channels"], dict):
        config["channels"] = {}

    config["channels"]["telegram"] = {
        "token_env": env_var,
        "authorized_users": [],
    }

    yaml_path.write_text(yaml.dump(config, default_flow_style=False, sort_keys=False))

    click.echo("  Telegram configured (token in channels/telegram.env)")
    click.echo(f"  Env var: {env_var}")


def _setup_discord(agent_dir: Path, agent_name: str, token: str) -> None:
    """Configure Discord channel for an agent.

    Creates the channels/discord.env file with the bot token and updates
    agent.yaml to reference the Discord channel configuration.

    Args:
        agent_dir: Path to the agent directory.
        agent_name: Name of the agent (used for env var naming).
        token: Discord bot token from the Discord Developer Portal.
    """
    env_var = f"{agent_name.upper()}_DISCORD_TOKEN"

    # Write token to channels/discord.env
    env_file = agent_dir / "channels" / "discord.env"
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text(f"{env_var}={token}\n")

    # Update agent.yaml with Discord channel config
    yaml_path = agent_dir / "agent.yaml"
    config = (yaml.safe_load(yaml_path.read_text()) or {}) if yaml_path.exists() else {}

    if "channels" not in config or not isinstance(config["channels"], dict):
        config["channels"] = {}

    config["channels"]["discord"] = {
        "token_env": env_var,
        "authorized_users": [],
    }

    yaml_path.write_text(yaml.dump(config, default_flow_style=False, sort_keys=False))

    click.echo("  Discord configured (token in channels/discord.env)")
    click.echo(f"  Env var: {env_var}")


def _scaffold(
    base: Path,
    agent_name: str = "myagent",
    model: str = "claude-sonnet-4-6",
    telegram_token: str | None = None,
    discord_token: str | None = None,
):
    """Scaffold smolclaw home directory and first agent. Safe to re-run."""
    click.echo(f"\n  First run — setting up smolclaw at {base}\n")

    # Shared directories
    for d in ["shared/skills", "shared/cron"]:
        (base / d).mkdir(parents=True, exist_ok=True)

    # Shared USER.md
    user_md = base / "shared" / "USER.md"
    if not user_md.exists():
        user_md.write_text(
            "# User\n\n"
            "Describe yourself here. All agents see this file.\n\n"
            "- Name: \n"
            "- Location: \n"
            "- Preferences: \n"
        )
        click.echo("  Created shared/USER.md")

    # Create the first agent
    agent_dir = base / "agents" / agent_name
    for subdir in ["skills", "prompts", "context", "channels", "sessions"]:
        (agent_dir / subdir).mkdir(parents=True, exist_ok=True)

    # agent.yaml
    yaml_path = agent_dir / "agent.yaml"
    if not yaml_path.exists():
        yaml_path.write_text(
            f"name: {agent_name}\n"
            f"model: {model}\n"
            "channels: {}\n"
            "memory:\n"
            "  enabled: true\n"
            "  cross_agent: false\n"
        )
        click.echo(f"  Created agents/{agent_name}/agent.yaml")

    # Telegram setup (if token provided)
    if telegram_token:
        _setup_telegram(agent_dir, agent_name, telegram_token)

    # Discord setup (if token provided)
    if discord_token:
        _setup_discord(agent_dir, agent_name, discord_token)

    # soul.md
    soul_path = agent_dir / "soul.md"
    if not soul_path.exists():
        soul_path.write_text(
            f"# {agent_name.upper()}\n\n"
            "You are a helpful personal AI assistant.\n\n"
            "## Personality\n"
            "- Friendly but concise. Respect the user's time.\n"
            "- Lead with actions and answers, not explanations.\n"
            "- Use structured output (bullets, tables) when it helps.\n"
            "- Be honest when you don't know something.\n"
            "- Light humor is welcome, never forced.\n"
        )
        click.echo(f"  Created agents/{agent_name}/soul.md")

    # agents.md
    agents_path = agent_dir / "agents.md"
    if not agents_path.exists():
        agents_path.write_text(
            f"# {agent_name.upper()} — Operational Rules\n\n"
            "## Core Behavior\n"
            "- Default to doing, not explaining. Deliver results first.\n"
            "- Keep responses short. If it fits in 2 lines, don't use 10.\n"
            "- Ask clarifying questions only when truly ambiguous.\n"
            "- Remember context from previous conversations when possible.\n\n"
            "## Tools & Skills\n"
            "- Use available tools proactively to get things done.\n"
            "- Skills are loaded from the skills/ directory.\n"
            "- Each skill folder contains a SKILL.md with instructions.\n\n"
            "## Memory\n"
            "- Store important facts and user preferences in memory.\n"
            "- Reference past context to avoid asking the same questions.\n"
        )
        click.echo(f"  Created agents/{agent_name}/agents.md")

    # Gateway config
    config_path = base / "config.yaml"
    if not config_path.exists():
        config_path.write_text("host: 127.0.0.1\nport: 7890\nlog_level: INFO\n")
        click.echo("  Created config.yaml")

    click.echo(f"\n  Agent '{agent_name}' ready. Starting gateway...\n")


@cli.command()
def version():
    """Show the smolclaw version."""
    from . import __version__

    click.echo(f"smolclaw {__version__}")


@cli.command()
@click.argument("shell", type=click.Choice(["bash", "zsh", "fish"]))
def completion(shell):
    """Generate shell completion script.

    Print the completion script for your shell. Add the output to your
    shell config to enable tab-completion for all smolclaw commands.

    \b
    Setup:
      bash:  eval "$(smolclaw completion bash)"
      zsh:   eval "$(smolclaw completion zsh)"
      fish:  smolclaw completion fish | source

    \b
    Or save to a file for faster shell startup:
      bash:  smolclaw completion bash > ~/.local/share/bash-completion/completions/smolclaw
      zsh:   smolclaw completion zsh > ~/.zfunc/_smolclaw && echo 'fpath+=~/.zfunc' >> ~/.zshrc
      fish:  smolclaw completion fish > ~/.config/fish/completions/smolclaw.fish
    """
    from click.shell_completion import get_completion_class

    comp_cls = get_completion_class(shell)
    if comp_cls is None:
        click.echo(f"Unsupported shell: {shell}", err=True)
        raise SystemExit(1)

    comp = comp_cls(cli, {}, "smolclaw", "_SMOLCLAW_COMPLETE")
    click.echo(comp.source())


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

GITHUB_REPO = "mandgie/smolclaw"


def _parse_version_tuple(version_str: str) -> tuple[int, ...]:
    """Parse '0.1.0' into a comparable tuple (0, 1, 0)."""
    return tuple(int(x) for x in version_str.strip().split("."))


def _get_latest_version() -> tuple[str | None, str]:
    """Fetch the latest smolclaw version from GitHub.

    Returns (version_string, source) where source is 'release' or 'main'.
    Returns (None, '') on failure.
    """
    import urllib.error
    import urllib.request

    # Try GitHub releases first
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            tag = data.get("tag_name", "")
            ver = tag.lstrip("v")
            if ver:
                return ver, "release"
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, json.JSONDecodeError):
        pass

    # Fall back: read pyproject.toml from main branch
    try:
        url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/pyproject.toml"
        with urllib.request.urlopen(url, timeout=10) as resp:
            for line in resp.read().decode().splitlines():
                if line.strip().startswith("version"):
                    # version = "0.1.0"
                    ver = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if ver:
                        return ver, "main"
    except (urllib.error.URLError, OSError):
        pass

    return None, ""


def _is_editable_install() -> bool:
    """Check if smolclaw is installed in editable (development) mode."""
    try:
        import importlib.metadata

        dist = importlib.metadata.distribution("smolclaw")
        # Editable installs have a direct_url.json with "dir_info": {"editable": true}
        direct_url = dist.read_text("direct_url.json")
        if direct_url:
            data = json.loads(direct_url)
            return data.get("dir_info", {}).get("editable", False)
    except Exception:
        pass
    return False


def _is_gateway_running(base: Path) -> bool:
    """Check if the gateway is running by probing the health endpoint.

    Uses /api/health which is always public (no auth required), so this
    works correctly regardless of whether api_key is configured.
    """
    import urllib.error
    import urllib.request

    from .config import load_gateway_config

    try:
        config = load_gateway_config(base)
    except Exception:
        return False

    try:
        url = f"http://{config.host}:{config.port}/api/health"
        with urllib.request.urlopen(url, timeout=3) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def _restart_gateway(base: Path) -> str:
    """Restart the gateway. Returns a status message."""
    system = platform.system()

    if system == "Darwin":
        plist = _plist_path()
        if plist.exists():
            subprocess.run(["launchctl", "unload", str(plist)], capture_output=True)
            result = subprocess.run(
                ["launchctl", "load", str(plist)], capture_output=True, text=True
            )
            if result.returncode == 0:
                return "Gateway restarted via LaunchAgent."
            return f"LaunchAgent reload failed: {result.stderr.strip()}"
    elif system == "Linux":
        unit_path = _systemd_unit_path()
        if unit_path.exists():
            result = subprocess.run(
                ["systemctl", "--user", "restart", SYSTEMD_SERVICE_NAME],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return "Gateway restarted via systemd."
            return f"Systemd restart failed: {result.stderr.strip()}"

    return "Gateway is running but not managed by a service. Restart manually: smolclaw up"


@cli.command()
@click.option("--check", is_flag=True, help="Check for updates without installing")
@click.option("--restart/--no-restart", default=True, help="Restart gateway after update")
@click.option("--force", is_flag=True, help="Force update even if already at latest")
@click.pass_context
def update(ctx, check, restart, force):
    """Update smolclaw to the latest version."""
    from . import __version__

    base = ctx.obj["base"]
    current = __version__

    click.echo(f"  Current version: {current}")
    click.echo("  Checking for updates...")

    latest, source = _get_latest_version()
    if latest is None:
        click.echo("  Could not check for updates (no internet?)")
        sys.exit(1)

    click.echo(f"  Latest version:  {latest} ({source})")

    try:
        is_newer = _parse_version_tuple(latest) > _parse_version_tuple(current)
    except (ValueError, TypeError):
        click.echo(f"  Could not parse version: {latest}")
        sys.exit(1)

    if not is_newer and not force:
        click.echo(f"\n  smolclaw {current} is already up to date.")
        return

    if is_newer:
        click.echo(f"\n  Update available: {current} → {latest}")

    if check:
        return

    # Editable install guard
    if _is_editable_install():
        click.echo("\n  You're running an editable (development) install.")
        click.echo("  Update via git instead:")
        repo = Path(__file__).resolve().parent.parent
        click.echo(f"    cd {repo} && git pull && pip install -e .")
        if not force:
            return
        click.echo("  --force passed, updating anyway...")

    # Check gateway before update
    gateway_was_running = _is_gateway_running(base)

    # Install
    click.echo("\n  Installing...")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--upgrade",
            f"git+https://github.com/{GITHUB_REPO}.git",
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        click.echo("  Update failed:")
        click.echo(result.stderr or result.stdout)
        sys.exit(1)

    # Verify new version
    verify = subprocess.run(
        [sys.executable, "-c", "import smolclaw; print(smolclaw.__version__)"],
        capture_output=True,
        text=True,
    )
    new_version = verify.stdout.strip() if verify.returncode == 0 else "unknown"

    click.echo(f"  Updated: {current} → {new_version}")

    # Restart gateway if it was running
    if restart and gateway_was_running:
        click.echo(f"  {_restart_gateway(base)}")
    elif gateway_was_running:
        click.echo("  Gateway is still running with old code — restart when ready.")


@cli.command()
@click.option("--agent", default="myagent", help="Name of the first agent to create")
@click.option("--model", default="claude-sonnet-4-6", help="Default model for the agent")
@click.option(
    "--telegram",
    "telegram_token",
    default=None,
    help="Telegram bot token from @BotFather — auto-configures Telegram channel",
)
@click.option(
    "--discord",
    "discord_token",
    default=None,
    help="Discord bot token — auto-configures Discord channel",
)
@click.pass_context
def init(ctx, agent, model, telegram_token, discord_token):
    """Initialize a new smolclaw project directory."""
    base = ctx.obj["base"]

    if (base / "agents").exists() and any(
        d.is_dir() and (d / "agent.yaml").exists() for d in (base / "agents").iterdir()
    ):
        click.echo(f"smolclaw is already initialized at {base}")
        click.echo("Use 'smolclaw add <name>' to create additional agents.")
        return

    _scaffold(
        base,
        agent_name=agent,
        model=model,
        telegram_token=telegram_token,
        discord_token=discord_token,
    )

    click.echo("Next steps:")
    click.echo(f"  1. Edit {base / 'agents' / agent / 'soul.md'} — define personality")
    click.echo(f"  2. Edit {base / 'shared' / 'USER.md'} — describe yourself")
    has_channel = telegram_token or discord_token
    if not has_channel:
        click.echo("  3. (Optional) Re-run with --telegram TOKEN or --discord TOKEN")
    click.echo(f"  {'3' if has_channel else '4'}. Run: smolclaw up")


@cli.command()
@click.pass_context
def status(ctx):
    """Show the current smolclaw setup and validate configuration."""
    from .config import discover_all_agents, load_gateway_config

    base = ctx.obj["base"]

    if not base.exists():
        click.echo(f"No smolclaw home at {base}")
        click.echo("Run 'smolclaw init' to set up.")
        return

    config = load_gateway_config(base)

    # Header
    click.echo(f"\nsmolclaw — {base}\n")

    # Agents
    agents = discover_all_agents(base)
    if not agents:
        click.echo("  Agents: (none)")
        click.echo("  Run 'smolclaw init' or 'smolclaw add <name>' to create an agent.\n")
        return

    click.echo(f"  {'AGENT':<15} {'MODEL':<25} {'CHANNELS':<15} {'SKILLS':<8} {'MEMORY'}")
    click.echo(f"  {'─' * 73}")
    issues: list[str] = []
    for name, info in agents.items():
        channels = ", ".join(info.config.channels.keys()) or "—"
        skill_count = len(info.skills)
        mem = "on" if info.config.memory.enabled else "off"
        click.echo(f"  {name:<15} {info.config.model:<25} {channels:<15} {skill_count:<8} {mem}")

        # Show optional SDK settings when configured
        extras = []
        if info.config.max_turns is not None:
            extras.append(f"max_turns={info.config.max_turns}")
        if info.config.max_budget_usd is not None:
            extras.append(f"budget=${info.config.max_budget_usd}")
        if info.config.fallback_model:
            extras.append(f"fallback={info.config.fallback_model}")
        if info.config.output_format:
            extras.append("structured_output")
        if info.config.enable_file_checkpointing:
            extras.append("checkpointing")
        if info.config.mcp_servers:
            if isinstance(info.config.mcp_servers, str):
                extras.append(f"mcp={info.config.mcp_servers}")
            else:
                names = ", ".join(info.config.mcp_servers.keys())
                extras.append(f"mcp=[{names}]")
        if info.config.thinking:
            t_type = info.config.thinking.get("type", "adaptive")
            extras.append(f"thinking={t_type}")
        if info.config.effort:
            extras.append(f"effort={info.config.effort}")
        if info.config.betas:
            extras.append(f"betas={info.config.betas}")
        if info.config.add_dirs:
            extras.append(f"add_dirs={len(info.config.add_dirs)}")
        if extras:
            click.echo(f"  {'':15} {', '.join(extras)}")

        # Collect issues
        if not info.soul:
            issues.append(f"Agent '{name}' has no soul.md — add a personality file")
        if not info.config.channels:
            issues.append(f"Agent '{name}' has no channels — add a channel config to agent.yaml")

    # Cron jobs
    jobs_path = base / config.shared_dir / "cron" / "jobs.json"
    click.echo("")
    if jobs_path.exists():
        try:
            jobs = json.loads(jobs_path.read_text())
            click.echo(f"  Jobs: {len(jobs)} scheduled")
            for job in jobs[:5]:
                status_icon = "✓" if job.get("status") == "ok" else "·"
                click.echo(f"    {status_icon} {job['id']} ({job['schedule']}) → {job['agent']}")
            if len(jobs) > 5:
                click.echo(f"    ... and {len(jobs) - 5} more")
        except (json.JSONDecodeError, OSError):
            click.echo("  Jobs: (error reading jobs.json)")
    else:
        click.echo("  Jobs: (none)")

    # Memory
    memory_db = base / config.shared_dir / "memory.db"
    if memory_db.exists():
        size_kb = memory_db.stat().st_size / 1024
        size_str = f"{size_kb / 1024:.1f} MB" if size_kb > 1024 else f"{size_kb:.0f} KB"
        click.echo(f"  Memory: {memory_db} ({size_str})")
    else:
        click.echo("  Memory: (no database yet — created on first gateway start)")

    # API
    click.echo(f"  API: http://{config.host}:{config.port}")

    # Issues
    if issues:
        click.echo("\n  Issues:")
        for issue in issues:
            click.echo(f"    ! {issue}")

    click.echo("")


@cli.group(invoke_without_command=True)
@click.pass_context
def config(ctx):
    """View or modify gateway configuration."""
    if ctx.invoked_subcommand is not None:
        return

    base = ctx.obj["base"]
    config_path = base / "config.yaml"

    if not config_path.exists():
        click.echo(f"No config.yaml at {config_path}")
        click.echo("Run 'smolclaw init' to set up.")
        return

    click.echo(config_path.read_text().rstrip())


@config.command("get")
@click.argument("key")
@click.pass_context
def config_get(ctx, key):
    """Get a configuration value."""
    base = ctx.obj["base"]
    config_path = base / "config.yaml"

    if not config_path.exists():
        click.echo(f"No config.yaml at {config_path}")
        sys.exit(1)

    with config_path.open() as f:
        data = yaml.safe_load(f) or {}

    if key not in data:
        click.echo(f"Key '{key}' not found in config.yaml")
        click.echo(f"Available keys: {', '.join(data.keys())}")
        sys.exit(1)

    click.echo(data[key])


@config.command("set")
@click.argument("key")
@click.argument("value")
@click.pass_context
def config_set(ctx, key, value):
    """Set a configuration value."""
    from .config import GatewayConfig

    base = ctx.obj["base"]
    config_path = base / "config.yaml"

    if not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        data: dict = {}
    else:
        with config_path.open() as f:
            data = yaml.safe_load(f) or {}

    # Coerce value to int if possible (for port)
    with contextlib.suppress(ValueError):
        value = int(value)

    # Validate by creating a config with the new value
    test_data = {**data, key: value}
    try:
        GatewayConfig(**test_data)
    except Exception as e:
        click.echo(f"Invalid config: {e}")
        sys.exit(1)

    data[key] = value
    config_path.write_text(yaml.dump(data, default_flow_style=False))
    click.echo(f"Set {key} = {value}")


@cli.command()
@click.option("--no-api", is_flag=True, help="Disable the API server")
@click.pass_context
def up(ctx, no_api):
    """Start the gateway (all agents, channels, scheduler, API)."""
    from .gateway import run_gateway

    base = ctx.obj["base"]

    # Auto-scaffold on first run
    if not (base / "agents").exists() or not any(d.is_dir() for d in (base / "agents").iterdir()):
        _scaffold(base)

    asyncio.run(run_gateway(base, with_api=not no_api))


@cli.command()
@click.argument("name")
@click.option("--model", default="claude-sonnet-4-6", help="Default model")
@click.option(
    "--telegram",
    "telegram_token",
    default=None,
    help="Telegram bot token from @BotFather — auto-configures Telegram channel",
)
@click.option(
    "--discord",
    "discord_token",
    default=None,
    help="Discord bot token — auto-configures Discord channel",
)
@click.pass_context
def add(ctx, name, model, telegram_token, discord_token):
    """Scaffold a new agent."""
    base = ctx.obj["base"]
    agent_dir = base / "agents" / name

    if agent_dir.exists():
        click.echo(f"Agent '{name}' already exists at {agent_dir}")
        sys.exit(1)

    # Create directory structure
    for subdir in ["skills", "prompts", "context", "channels", "sessions"]:
        (agent_dir / subdir).mkdir(parents=True, exist_ok=True)

    # Create shared dir if needed
    (base / "shared" / "skills").mkdir(parents=True, exist_ok=True)

    # Write agent.yaml
    config = f"""name: {name}
model: {model}
channels: {{}}
memory:
  enabled: true
  cross_agent: false
"""
    (agent_dir / "agent.yaml").write_text(config)

    # Write soul.md template
    (agent_dir / "soul.md").write_text(
        f"# {name.upper()}\n\nDescribe this agent's personality and role here.\n"
    )

    # Write agents.md template
    (agent_dir / "agents.md").write_text(
        f"# {name.upper()} — Operational Rules\n\nDefine tools, skills, and behavior rules here.\n"
    )

    # Channel setup (if tokens provided)
    if telegram_token:
        _setup_telegram(agent_dir, name, telegram_token)
    if discord_token:
        _setup_discord(agent_dir, name, discord_token)

    # Create USER.md if it doesn't exist
    user_md = base / "shared" / "USER.md"
    if not user_md.exists():
        user_md.write_text("# User\n\nDescribe yourself here. Shared across all agents.\n")

    click.echo(f"Created agent '{name}' at {agent_dir}")
    click.echo(f"  Edit: {agent_dir}/soul.md")
    click.echo(f"  Config: {agent_dir}/agent.yaml")


@cli.command("list")
@click.pass_context
def list_agents(ctx):
    """List all agents."""
    from .config import discover_all_agents

    base = ctx.obj["base"]
    agents = discover_all_agents(base)

    if not agents:
        click.echo("No agents found.")
        return

    click.echo(f"{'NAME':<15} {'MODEL':<25} {'CHANNELS':<20} {'SKILLS'}")
    click.echo("─" * 75)
    for name, info in agents.items():
        channels = ", ".join(info.config.channels.keys()) or "none"
        skill_count = len(info.skills)
        click.echo(f"{name:<15} {info.config.model:<25} {channels:<20} {skill_count} skills")


def _try_api_send(base: Path, agent_name: str, message: str) -> str | None:
    """Try sending a message via the running gateway API. Returns response or None.

    Includes Authorization header when api_key is configured in config.yaml.
    """
    import urllib.error
    import urllib.request

    from .config import load_gateway_config

    config = load_gateway_config(base)
    url = f"http://{config.host}:{config.port}/api/agents/{agent_name}/send"

    try:
        data = json.dumps({"text": message}).encode()
        headers = {"Content-Type": "application/json"}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"
        req = urllib.request.Request(url, data=data, headers=headers)
        with urllib.request.urlopen(req, timeout=900) as resp:
            result = json.loads(resp.read())
            return result.get("response", "")
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return None


@cli.command()
@click.argument("agent_name")
@click.argument("message")
@click.pass_context
def send(ctx, agent_name, message):
    """Send a one-shot message to an agent.

    Tries the running gateway API first (fast). Falls back to starting
    a temporary gateway if the API isn't available.
    """
    from .gateway import Gateway

    base = ctx.obj["base"]

    # Fast path: use the running gateway API
    response = _try_api_send(base, agent_name, message)
    if response is not None:
        click.echo(response)
        return

    # Slow path: boot a temporary gateway
    async def _send():
        gw = Gateway(base)
        await gw.start()
        try:
            response = await gw.send(agent_name, message)
            click.echo(response)
        finally:
            await gw.stop()

    asyncio.run(_send())


def _session_file_path(base: Path, agent_name: str) -> Path:
    """Return the path for persisting a CLI chat session ID."""
    return base / "agents" / agent_name / "sessions" / "cli.json"


def _load_session_id(session_file: Path) -> str | None:
    """Load a persisted session ID from disk, or None if not found."""
    if not session_file.exists():
        return None
    try:
        data = json.loads(session_file.read_text())
        return data.get("session_id")
    except (json.JSONDecodeError, OSError):
        return None


def _save_session_id(session_file: Path, session_id: str) -> None:
    """Persist a session ID to disk."""
    session_file.parent.mkdir(parents=True, exist_ok=True)
    session_file.write_text(json.dumps({"session_id": session_id}))


def _clear_session_file(session_file: Path) -> None:
    """Remove the persisted session file."""
    if session_file.exists():
        session_file.unlink()


@cli.command()
@click.argument("agent_name")
@click.option("--no-api", is_flag=True, default=True, help="Start API server alongside chat")
@click.option("--new-session", is_flag=True, help="Start a fresh session (ignore saved)")
@click.pass_context
def chat(ctx, agent_name, no_api, new_session):
    """Interactive chat session with an agent.

    Start a REPL-style conversation. Type messages and get responses.
    Sessions are automatically saved and resumed between runs.
    Commands: /new (reset session), /cost (show last cost), /help, /quit.
    """
    from .config import discover_all_agents
    from .gateway import Gateway, setup_logging

    base = ctx.obj["base"]

    # Validate agent exists before starting
    agents = discover_all_agents(base)
    if agent_name not in agents:
        available = ", ".join(agents.keys()) if agents else "(none)"
        click.echo(f"Agent '{agent_name}' not found. Available: {available}")
        sys.exit(1)

    agent_info = agents[agent_name]

    session_file = _session_file_path(base, agent_name)

    async def _chat():
        setup_logging(base, level="WARNING")
        gw = Gateway(base)
        await gw.start()

        agent = gw.agents.get(agent_name)
        if not agent:
            click.echo(f"Agent '{agent_name}' failed to load.")
            await gw.stop()
            return

        # Resume previous session if available
        resumed = False
        if not new_session:
            saved_id = _load_session_id(session_file)
            if saved_id:
                agent._session_id = saved_id
                resumed = True

        click.echo(f"\nsmolclaw chat — {agent_name} ({agent_info.config.model})")
        if resumed:
            click.echo(click.style("  Resuming previous session", fg="bright_black"))
        click.echo("Type a message, or /help for commands\n")

        try:
            while True:
                try:
                    text = click.prompt(
                        click.style("you", fg="green", bold=True),
                        prompt_suffix=click.style(" > ", fg="green"),
                    )
                except (EOFError, click.Abort):
                    break

                text = text.strip()
                if not text:
                    continue

                # Handle commands
                if text.lower() in ("/quit", "/exit", "/q"):
                    break
                if text.lower() in ("/help", "/h", "/?"):
                    click.echo("  Commands:")
                    click.echo("    /new     Reset session (start fresh)")
                    click.echo("    /cost    Show last query cost and tokens")
                    click.echo("    /quit    Exit chat (/exit, /q also work)")
                    click.echo("    /help    Show this help (/h, /? also work)")
                    click.echo()
                    continue
                if text.lower() == "/new":
                    await agent.new_session()
                    _clear_session_file(session_file)
                    click.echo(click.style("  Session reset.\n", fg="yellow"))
                    continue
                if text.lower() == "/cost":
                    if agent.last_cost_usd is not None:
                        usage = agent.last_usage or {}
                        tokens = usage.get("total_tokens", "?")
                        click.echo(
                            f"  Last: ${agent.last_cost_usd:.4f}"
                            f" ({tokens} tokens, {agent.last_duration_ms or 0}ms)"
                        )
                    else:
                        click.echo("  No cost data yet.")
                    click.echo()
                    continue

                # Send message
                click.echo()
                try:
                    response = await gw.send(agent_name, text)
                except Exception as e:
                    click.echo(click.style(f"  Error: {e}\n", fg="red"))
                    continue

                # Print response
                click.echo(click.style(f"{agent_name}", fg="cyan", bold=True))
                click.echo(response)

                # Persist session ID for next run
                if agent._session_id:
                    _save_session_id(session_file, agent._session_id)

                # Show cost inline
                if agent.last_cost_usd is not None:
                    cost_line = f"  ${agent.last_cost_usd:.4f}"
                    if agent.last_duration_ms:
                        cost_line += f" · {agent.last_duration_ms / 1000:.1f}s"
                    click.echo(click.style(cost_line, fg="bright_black"))
                click.echo()

        except KeyboardInterrupt:
            pass
        finally:
            click.echo("\nBye.")
            await gw.stop()

    asyncio.run(_chat())


@cli.group()
def cron():
    """Manage scheduled jobs."""
    pass


@cron.command("list")
@click.option("--all", "show_all", is_flag=True, help="Show disabled jobs too")
@click.pass_context
def cron_list(ctx, show_all):
    """List all scheduled jobs."""
    base = ctx.obj["base"]
    jobs_path = base / "shared" / "cron" / "jobs.json"

    if not jobs_path.exists():
        click.echo("No jobs configured.")
        return

    jobs = json.loads(jobs_path.read_text())
    visible = [j for j in jobs if j.get("enabled", True)] if not show_all else jobs

    if not visible:
        click.echo("No jobs found. Use --all to include disabled jobs.")
        return

    click.echo(
        f"{'ID':<25} {'AGENT':<10} {'SCHEDULE':<18} "
        f"{'ON':<4} {'STATUS':<8} {'LAST RUN':<20} {'NEXT RUN'}"
    )
    click.echo("─" * 110)
    for job in visible:
        enabled = "✓" if job.get("enabled", True) else "✗"
        last_run = job.get("last_run", "") or "—"
        if last_run != "—":
            last_run = last_run[:19]  # Trim to seconds
        next_run = job.get("next_run", "") or "—"
        if next_run != "—":
            next_run = next_run[:19]
        click.echo(
            f"{job['id']:<25} {job['agent']:<10} {job['schedule']:<18} "
            f"{enabled:<4} {job.get('status', 'pending'):<8} {last_run:<20} {next_run}"
        )


@cron.command("add")
@click.option("--agent", required=True, help="Agent name")
@click.option("--schedule", required=True, help="Cron expression (e.g. '0 8 * * 1-5')")
@click.option("--prompt", required=True, help="Prompt text or prompt file path")
@click.option("--delivery", default="", help="Delivery channel (e.g. 'telegram')")
@click.option("--chat-id", default="", help="Delivery chat ID")
@click.option("--id", "job_id", default=None, help="Job ID (auto-generated if omitted)")
@click.pass_context
def cron_add(ctx, agent, schedule, prompt, delivery, chat_id, job_id):
    """Add a new scheduled job."""
    from croniter import croniter

    # Validate cron expression before doing anything
    try:
        croniter(schedule)
    except (ValueError, KeyError, TypeError) as e:
        click.echo(f"Invalid cron schedule '{schedule}': {e}", err=True)
        sys.exit(1)

    base = ctx.obj["base"]
    jobs_path = base / "shared" / "cron" / "jobs.json"
    jobs_path.parent.mkdir(parents=True, exist_ok=True)

    jobs = []
    if jobs_path.exists():
        jobs = json.loads(jobs_path.read_text())

    if not job_id:
        job_id = f"{agent}-{prompt[:20].replace(' ', '-').lower()}"

    # Check if prompt is a file path
    prompt_file = ""
    prompt_path = base / "agents" / agent / "prompts" / prompt
    if prompt_path.exists():
        prompt_file = prompt
        prompt = ""

    job = {
        "id": job_id,
        "agent": agent,
        "schedule": schedule,
        "prompt": prompt,
        "prompt_file": prompt_file,
        "enabled": True,
        "delivery": delivery,
        "delivery_chat_id": chat_id,
        "session_mode": "isolated",
        "last_run": "",
        "next_run": "",
        "status": "pending",
        "failures": 0,
    }

    jobs.append(job)
    jobs_path.write_text(json.dumps(jobs, indent=2))
    click.echo(f"Added job '{job_id}' for agent '{agent}'")


@cron.command("edit")
@click.argument("job_id")
@click.option("--schedule", default=None, help="New cron expression")
@click.option("--prompt", default=None, help="New prompt text or prompt file path")
@click.option("--delivery", default=None, help="New delivery channel (e.g. 'telegram')")
@click.option("--chat-id", default=None, help="New delivery chat ID")
@click.option("--session-mode", default=None, help="Session mode: 'isolated' or 'shared'")
@click.pass_context
def cron_edit(ctx, job_id, schedule, prompt, delivery, chat_id, session_mode):
    """Edit an existing scheduled job."""
    from croniter import croniter

    base = ctx.obj["base"]
    jobs_path = base / "shared" / "cron" / "jobs.json"

    if not jobs_path.exists():
        click.echo("No jobs file found.")
        return

    # Validate new schedule if provided
    if schedule is not None:
        try:
            croniter(schedule)
        except (ValueError, KeyError, TypeError) as e:
            click.echo(f"Invalid cron schedule '{schedule}': {e}", err=True)
            sys.exit(1)

    jobs = json.loads(jobs_path.read_text())
    found = False
    for job in jobs:
        if job["id"] == job_id:
            found = True
            changes = []
            if schedule is not None:
                job["schedule"] = schedule
                changes.append("schedule")
            if prompt is not None:
                # Check if it's a file path
                agent = job.get("agent", "")
                prompt_path = base / "agents" / agent / "prompts" / prompt
                if prompt_path.exists():
                    job["prompt_file"] = prompt
                    job["prompt"] = ""
                    changes.append("prompt_file")
                else:
                    job["prompt"] = prompt
                    job.pop("prompt_file", None)
                    changes.append("prompt")
            if delivery is not None:
                job["delivery"] = delivery
                changes.append("delivery")
            if chat_id is not None:
                job["delivery_chat_id"] = chat_id
                changes.append("delivery_chat_id")
            if session_mode is not None:
                job["session_mode"] = session_mode
                changes.append("session_mode")
            break

    if not found:
        click.echo(f"Job '{job_id}' not found.")
        return

    if not changes:
        click.echo(
            "No changes specified. Use --schedule, --prompt, "
            "--delivery, --chat-id, or --session-mode."
        )
        return

    jobs_path.write_text(json.dumps(jobs, indent=2))
    click.echo(f"Updated job '{job_id}' ({', '.join(changes)})")


@cron.command("remove")
@click.argument("job_id")
@click.pass_context
def cron_remove(ctx, job_id):
    """Remove a scheduled job."""
    base = ctx.obj["base"]
    jobs_path = base / "shared" / "cron" / "jobs.json"

    if not jobs_path.exists():
        click.echo("No jobs file found.")
        return

    jobs = json.loads(jobs_path.read_text())
    before = len(jobs)
    jobs = [j for j in jobs if j["id"] != job_id]

    if len(jobs) == before:
        click.echo(f"Job '{job_id}' not found.")
        return

    jobs_path.write_text(json.dumps(jobs, indent=2))
    click.echo(f"Removed job '{job_id}'")


@cron.command("enable")
@click.argument("job_id")
@click.pass_context
def cron_enable(ctx, job_id):
    """Enable a disabled job."""
    _toggle_job(ctx.obj["base"], job_id, enabled=True)


@cron.command("disable")
@click.argument("job_id")
@click.pass_context
def cron_disable(ctx, job_id):
    """Disable a job without removing it."""
    _toggle_job(ctx.obj["base"], job_id, enabled=False)


def _toggle_job(base: Path, job_id: str, *, enabled: bool) -> None:
    """Enable or disable a job by ID."""
    jobs_path = base / "shared" / "cron" / "jobs.json"

    if not jobs_path.exists():
        click.echo("No jobs file found.")
        return

    jobs = json.loads(jobs_path.read_text())
    found = False
    for job in jobs:
        if job["id"] == job_id:
            job["enabled"] = enabled
            found = True
            break

    if not found:
        click.echo(f"Job '{job_id}' not found.")
        return

    jobs_path.write_text(json.dumps(jobs, indent=2))
    state = "enabled" if enabled else "disabled"
    click.echo(f"Job '{job_id}' {state}.")


@cron.command("run")
@click.argument("job_id")
@click.pass_context
def cron_run(ctx, job_id):
    """Manually trigger a scheduled job (requires running gateway)."""
    import urllib.error
    import urllib.request

    base = ctx.obj["base"]

    # Read gateway config (port, host, api_key) once
    host = "127.0.0.1"
    port = 7890
    api_key = None
    config_path = base / "config.yaml"
    if config_path.exists():
        import yaml

        try:
            cfg = yaml.safe_load(config_path.read_text()) or {}
            host = cfg.get("host", host)
            port = cfg.get("port", port)
            api_key = cfg.get("api_key")
        except Exception:
            pass

    url = f"http://{host}:{port}/api/cron/jobs/{job_id}/trigger"

    # Build request with optional auth
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(url, data=b"{}", headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        click.echo(f"Error ({e.code}): {body}", err=True)
        sys.exit(1)
    except urllib.error.URLError:
        click.echo("Gateway not running. Start it with 'smolclaw up' first.", err=True)
        sys.exit(1)

    click.echo(f"✓ Triggered job '{job_id}'")
    if result.get("response"):
        click.echo(f"\n{result['response']}")


def _resolve_memory_db(base: Path, agent_name: str) -> Path:
    """Validate the agent exists and return the memory DB path."""
    from .config import discover_all_agents, load_gateway_config

    agents = discover_all_agents(base)
    if agent_name not in agents:
        available = ", ".join(agents.keys()) if agents else "(none)"
        click.echo(f"Agent '{agent_name}' not found. Available: {available}")
        sys.exit(1)

    config = load_gateway_config(base)
    return base / config.shared_dir / "memory.db"


def _open_memory(base: Path, agent_name: str):
    """Open a Memory instance for the given agent. Validates agent exists and DB exists."""
    from .memory import Memory

    db_path = _resolve_memory_db(base, agent_name)
    if not db_path.exists():
        click.echo("No memory database yet (created on first gateway start).")
        sys.exit(0)
    return Memory(db_path, agent=agent_name)


@cli.group()
def memory():
    """View and manage agent memory."""
    pass


@memory.command("stats")
@click.argument("agent_name")
@click.pass_context
def memory_stats(ctx, agent_name):
    """Show memory statistics for an agent."""
    base = ctx.obj["base"]
    mem = _open_memory(base, agent_name)
    s = mem.stats()
    click.echo(f"\nMemory — {agent_name}\n")
    click.echo(f"  Facts:    {s['facts']}  (total across agents: {s['total_facts']})")
    click.echo(f"  Chunks:   {s['chunks']}  (total across agents: {s['total_chunks']})")
    click.echo(f"  Vector:   {'enabled' if s['vec_enabled'] else 'disabled'}")
    if s.get("vec_facts") is not None:
        click.echo(f"  Vec facts:  {s['vec_facts']}")
        click.echo(f"  Vec chunks: {s['vec_chunks']}")
    click.echo("")


@memory.command("list")
@click.argument("agent_name")
@click.option("-n", "--limit", default=20, help="Max facts to show")
@click.option("-c", "--category", default=None, help="Filter by category")
@click.pass_context
def memory_list(ctx, agent_name, limit, category):
    """List facts stored in an agent's memory."""
    base = ctx.obj["base"]
    mem = _open_memory(base, agent_name)
    facts = mem.list_facts(limit=limit, category=category)
    if not facts:
        click.echo(f"No facts found for agent '{agent_name}'.")
        return

    click.echo(f"\n{'ID':<6} {'CATEGORY':<12} {'CREATED':<20} CONTENT")
    click.echo("─" * 80)
    for f in facts:
        created = f.get("created_at", "")[:19]
        content = f["content"]
        if len(content) > 60:
            content = content[:57] + "..."
        click.echo(f"{f['id']:<6} {f.get('category', ''):<12} {created:<20} {content}")
    click.echo(f"\n{len(facts)} fact(s) shown.\n")


@memory.command("search")
@click.argument("agent_name")
@click.argument("query")
@click.option("-n", "--limit", default=10, help="Max results")
@click.option("--cross-agent", is_flag=True, help="Search across all agents")
@click.pass_context
def memory_search(ctx, agent_name, query, limit, cross_agent):
    """Search an agent's memory for facts matching a query."""
    base = ctx.obj["base"]
    mem = _open_memory(base, agent_name)
    results = mem.search_facts(query, limit=limit, cross_agent=cross_agent)
    if not results:
        click.echo(f"No results for '{query}'.")
        return

    click.echo(f"\n{'ID':<6} {'CATEGORY':<12} CONTENT")
    click.echo("─" * 70)
    for r in results:
        content = r["content"]
        if len(content) > 60:
            content = content[:57] + "..."
        click.echo(f"{r['id']:<6} {r.get('category', ''):<12} {content}")
    click.echo(f"\n{len(results)} result(s).\n")


@memory.command("add")
@click.argument("agent_name")
@click.argument("content")
@click.option("-c", "--category", default="general", help="Fact category")
@click.pass_context
def memory_add(ctx, agent_name, content, category):
    """Add a fact to an agent's memory."""
    base = ctx.obj["base"]
    mem = _open_memory(base, agent_name)
    fact_id = mem.add_fact(content, category=category)
    click.echo(f"Added fact #{fact_id} to '{agent_name}' [{category}]")


@memory.command("get")
@click.argument("agent_name")
@click.argument("fact_id", type=int)
@click.pass_context
def memory_get(ctx, agent_name, fact_id):
    """Show a single fact by ID."""
    base = ctx.obj["base"]
    mem = _open_memory(base, agent_name)
    fact = mem.get_fact(fact_id)
    if not fact:
        click.echo(f"Fact #{fact_id} not found (or belongs to another agent).")
        sys.exit(1)

    click.echo(f"\n  ID:        {fact['id']}")
    click.echo(f"  Agent:     {fact.get('agent', agent_name)}")
    click.echo(f"  Category:  {fact.get('category', 'general')}")
    click.echo(f"  Created:   {fact.get('created_at', 'unknown')}")
    click.echo(f"  Content:   {fact['content']}\n")


@memory.command("update")
@click.argument("agent_name")
@click.argument("fact_id", type=int)
@click.option("--content", default=None, help="New content for the fact")
@click.option("-c", "--category", default=None, help="New category")
@click.pass_context
def memory_update(ctx, agent_name, fact_id, content, category):
    """Update a fact's content and/or category."""
    if content is None and category is None:
        click.echo("Nothing to update — provide --content and/or --category.")
        sys.exit(1)

    base = ctx.obj["base"]
    mem = _open_memory(base, agent_name)

    if mem.update_fact(fact_id, content=content, category=category):
        parts = []
        if content is not None:
            parts.append("content")
        if category is not None:
            parts.append(f"category → {category}")
        click.echo(f"Updated fact #{fact_id}: {', '.join(parts)}")
    else:
        click.echo(f"Fact #{fact_id} not found (or belongs to another agent).")
        sys.exit(1)


@memory.command("delete")
@click.argument("agent_name")
@click.argument("fact_id", type=int)
@click.pass_context
def memory_delete(ctx, agent_name, fact_id):
    """Delete a fact by ID from an agent's memory."""
    base = ctx.obj["base"]
    mem = _open_memory(base, agent_name)

    if mem.delete_fact(fact_id):
        click.echo(f"Deleted fact #{fact_id}")
    else:
        click.echo(f"Fact #{fact_id} not found (or belongs to another agent).")
        sys.exit(1)


@memory.command("clear")
@click.argument("agent_name")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
@click.pass_context
def memory_clear(ctx, agent_name, yes):
    """Clear all facts and conversation chunks for an agent.

    This permanently deletes all memory entries for the specified agent.
    Other agents' memory is not affected.
    """
    base = ctx.obj["base"]
    mem = _open_memory(base, agent_name)

    # Show what will be deleted
    s = mem.stats()
    total = s["facts"] + s["chunks"]
    if total == 0:
        click.echo(f"Agent '{agent_name}' has no memory entries.")
        return

    click.echo(f"Agent '{agent_name}' memory: {s['facts']} facts, {s['chunks']} chunks")

    if not yes:
        click.confirm("Permanently delete all entries?", abort=True)

    result = mem.clear()
    click.echo(f"Cleared: {result['facts_deleted']} facts, {result['chunks_deleted']} chunks")


@cli.command("add-skill")
@click.argument("agent_name")
@click.argument("skill_name")
@click.pass_context
def add_skill(ctx, agent_name, skill_name):
    """Add a shared skill to an agent (creates symlink)."""
    base = ctx.obj["base"]
    shared_skill = base / "shared" / "skills" / skill_name
    agent_skill = base / "agents" / agent_name / "skills" / skill_name

    if not shared_skill.exists():
        click.echo(f"Shared skill '{skill_name}' not found at {shared_skill}")
        sys.exit(1)

    if agent_skill.exists():
        click.echo(f"Agent '{agent_name}' already has skill '{skill_name}'")
        return

    agent_skill.symlink_to(shared_skill)
    click.echo(f"Linked {skill_name} → {agent_name}")


@cli.command("create-skill")
@click.argument("skill_name")
@click.option(
    "--agent",
    default=None,
    help="Create skill in an agent's skills/ directory (default: shared/skills/)",
)
@click.option(
    "--description",
    "-d",
    default="",
    help="Short description of what the skill does (for SKILL.md frontmatter)",
)
@click.pass_context
def create_skill(ctx, skill_name, agent, description):
    """Scaffold a new skill directory with SKILL.md template.

    Creates a skill in shared/skills/ (usable by any agent via add-skill) or
    directly in an agent's skills/ directory with --agent.

    \b
    Examples:
        smolclaw create-skill my-tool
        smolclaw create-skill my-tool --agent tars -d "Tool integration"
    """
    base = ctx.obj["base"]

    if agent:
        skill_dir = base / "agents" / agent / "skills" / skill_name
        agent_dir = base / "agents" / agent
        if not agent_dir.exists():
            click.echo(f"Agent '{agent}' not found at {agent_dir}")
            sys.exit(1)
    else:
        skill_dir = base / "shared" / "skills" / skill_name

    if skill_dir.exists():
        click.echo(f"Skill '{skill_name}' already exists at {skill_dir}")
        sys.exit(1)

    # Create skill directory structure
    skill_dir.mkdir(parents=True)

    # Write SKILL.md with frontmatter
    desc = description or f"{skill_name} skill"
    skill_md = (
        f"---\n"
        f"name: {skill_name}\n"
        f"description: {desc}\n"
        f"---\n\n"
        f"# {skill_name}\n\n"
        f"## Overview\n\n"
        f"Describe what this skill does and when the agent should use it.\n\n"
        f"## Usage\n\n"
        f"Add usage instructions, examples, and available commands here.\n"
    )
    (skill_dir / "SKILL.md").write_text(skill_md)

    location = f"agent '{agent}'" if agent else "shared"
    click.echo(f"Created skill '{skill_name}' ({location})")
    click.echo(f"  Edit: {skill_dir}/SKILL.md")
    if not agent:
        click.echo(f"  Link to agent: smolclaw add-skill <agent> {skill_name}")


@cli.command("export")
@click.argument("name")
@click.option("-o", "--output", default=None, help="Output file path (default: <name>.tar.gz)")
@click.option("--include-env", is_flag=True, help="Include .env files (contains secrets!)")
@click.pass_context
def export_agent(ctx, name, output, include_env):
    """Export an agent as a portable archive (.tar.gz).

    Creates a self-contained archive of an agent's configuration, personality,
    skills, prompts, and context files. Symlinked skills are resolved (actual
    files are included). Sessions, __pycache__, and .env files (secrets) are
    excluded by default.

    Import on another machine with: smolclaw import <archive>
    """
    import tarfile

    base = ctx.obj["base"]
    agent_dir = base / "agents" / name

    if not agent_dir.exists() or not (agent_dir / "agent.yaml").exists():
        click.echo(f"Agent '{name}' not found at {agent_dir}")
        sys.exit(1)

    # Determine output path
    if output is None:
        output = f"{name}.tar.gz"
    output_path = Path(output).resolve()

    # Directories and patterns to exclude
    exclude_dirs = {"sessions", "__pycache__"}
    exclude_patterns = {".pyc"}
    if not include_env:
        exclude_patterns.add(".env")

    def should_exclude(path: Path) -> bool:
        """Check if a path should be excluded from the archive."""
        for part in path.parts:
            if part in exclude_dirs:
                return True
        return path.suffix in exclude_patterns

    try:
        with tarfile.open(str(output_path), "w:gz") as tar:
            # Walk the agent directory, following symlinks so shared skills
            # (which are typically symlinked from shared/) get included.
            for root, _dirs, files in os.walk(agent_dir, followlinks=True):
                root_path = Path(root)
                for filename in sorted(files):
                    file_path = root_path / filename
                    relative = file_path.relative_to(agent_dir)
                    if should_exclude(relative):
                        continue
                    arcname = f"{name}/{relative}"
                    tar.add(str(file_path.resolve()), arcname=arcname)

        size_kb = output_path.stat().st_size / 1024
        click.echo(f"Exported agent '{name}' → {output_path} ({size_kb:.1f} KB)")

        # Summary of what's included
        file_count = 0
        with tarfile.open(str(output_path), "r:gz") as tar:
            file_count = len(tar.getnames())
        click.echo(f"  {file_count} files")
        if not include_env:
            click.echo("  .env files excluded (use --include-env to include)")
        click.echo(f"\n  Import: smolclaw import {output_path.name}")

    except OSError as e:
        click.echo(f"Export failed: {e}", err=True)
        sys.exit(1)


@cli.command("import")
@click.argument("archive")
@click.option("--rename", default=None, help="Import under a different agent name")
@click.option("--force", is_flag=True, help="Overwrite if agent already exists")
@click.pass_context
def import_agent(ctx, archive, rename, force):
    """Import an agent from a .tar.gz archive.

    Extracts an exported agent into the agents directory. Use --rename to
    import under a different name.
    """
    import tarfile

    base = ctx.obj["base"]
    archive_path = Path(archive).resolve()

    if not archive_path.exists():
        click.echo(f"Archive not found: {archive_path}")
        sys.exit(1)

    try:
        with tarfile.open(str(archive_path), "r:gz") as tar:
            # Determine agent name from archive structure
            names = tar.getnames()
            if not names:
                click.echo("Archive is empty.")
                sys.exit(1)

            # Security: check for path traversal (e.g. ../../etc/passwd)
            for member_name in names:
                if member_name.startswith("/") or ".." in member_name:
                    click.echo(f"Unsafe path in archive: {member_name}")
                    sys.exit(1)

            # Extract the top-level directory name (= agent name)
            original_name = names[0].split("/")[0]
            agent_name = rename or original_name

            agent_dir = base / "agents" / agent_name

            if agent_dir.exists() and not force:
                click.echo(f"Agent '{agent_name}' already exists. Use --force to overwrite.")
                sys.exit(1)

            if agent_dir.exists() and force:
                shutil.rmtree(agent_dir)

            # Extract, remapping the top-level directory if renamed
            agent_dir.mkdir(parents=True, exist_ok=True)
            for member in tar.getmembers():
                # Strip the original top-level directory, remap to agent_name
                parts = member.name.split("/", 1)
                if len(parts) < 2:
                    continue  # Skip the top-level dir entry itself
                relative = parts[1]
                if not relative:
                    continue

                member_copy = tarfile.TarInfo(name=relative)
                member_copy.size = member.size
                member_copy.mode = member.mode

                target = agent_dir / relative
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    fileobj = tar.extractfile(member)
                    if fileobj:
                        target.write_bytes(fileobj.read())

            # Update agent name in agent.yaml if renamed
            if rename and rename != original_name:
                yaml_path = agent_dir / "agent.yaml"
                if yaml_path.exists():
                    content = yaml_path.read_text()
                    content = content.replace(f"name: {original_name}", f"name: {rename}", 1)
                    yaml_path.write_text(content)

        click.echo(f"Imported agent '{agent_name}' from {archive_path.name}")
        click.echo(f"  Location: {agent_dir}")
        click.echo(f"  Edit: {agent_dir / 'soul.md'}")

    except tarfile.TarError as e:
        click.echo(f"Failed to read archive: {e}", err=True)
        sys.exit(1)
    except OSError as e:
        click.echo(f"Import failed: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("name")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def remove(ctx, name, yes):
    """Remove an agent and its directory."""
    base = ctx.obj["base"]
    agent_dir = base / "agents" / name

    if not agent_dir.exists():
        click.echo(f"Agent '{name}' not found at {agent_dir}")
        sys.exit(1)

    if not yes:
        click.confirm(f"Remove agent '{name}' at {agent_dir}?", abort=True)

    shutil.rmtree(agent_dir)
    click.echo(f"Removed agent '{name}'")


@cli.command()
@click.option("-n", "--lines", default=50, help="Number of lines to show")
@click.option("-f", "--follow", is_flag=True, help="Follow the log in real time (like tail -f)")
@click.pass_context
def logs(ctx, lines, follow):
    """Show gateway log output."""
    from .gateway import get_log_path

    base = ctx.obj["base"]
    log_path = get_log_path(base)

    if not log_path.exists():
        click.echo(f"No log file found at {log_path}")
        click.echo("Start the gateway first: smolclaw up")
        return

    # Read last N lines
    try:
        all_lines = log_path.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        click.echo(f"Error reading log file: {e}")
        return

    for line in all_lines[-lines:]:
        click.echo(line)

    if not follow:
        return

    # Follow mode: watch for new lines
    import time

    click.echo("--- following (Ctrl+C to stop) ---")
    try:
        offset = log_path.stat().st_size
        while True:
            time.sleep(0.5)
            current_size = log_path.stat().st_size
            if current_size > offset:
                with log_path.open(encoding="utf-8") as f:
                    f.seek(offset)
                    new_text = f.read()
                    if new_text:
                        click.echo(new_text, nl=False)
                offset = current_size
            elif current_size < offset:
                # File was rotated
                offset = 0
    except KeyboardInterrupt:
        pass


@cli.command()
@click.pass_context
def doctor(ctx):
    """Check system health and diagnose common issues."""
    import shutil
    import sqlite3

    base = ctx.obj["base"]
    issues: list[str] = []
    ok_count = 0

    click.echo("\nsmolclaw doctor\n")

    # 1. Python version
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 11):  # noqa: UP036 — runtime check, not dead code
        click.echo(f"  [ok] Python {py_ver}")
        ok_count += 1
    else:
        click.echo(f"  [!!] Python {py_ver} — requires 3.11+")
        issues.append("Python 3.11+ required")

    # 2. Claude CLI + auth
    claude_path = shutil.which("claude")
    if claude_path:
        click.echo(f"  [ok] Claude CLI found: {claude_path}")
        ok_count += 1

        # Check Claude auth status
        import subprocess

        try:
            result = subprocess.run(
                [claude_path, "auth", "status"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            output = result.stdout + result.stderr
            if "loggedIn" in output and "true" in output.lower():
                click.echo("  [ok] Claude CLI authenticated")
                ok_count += 1
            else:
                click.echo("  [!!] Claude CLI not authenticated")
                issues.append("Run 'claude auth login' to authenticate")
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            click.echo("  [--] Could not check Claude auth status")
    else:
        click.echo("  [!!] Claude CLI not found in PATH")
        issues.append("Install Claude CLI: npm install -g @anthropic-ai/claude-code")

    # 3. Key dependencies
    for pkg_name, import_name in [
        ("claude-agent-sdk", "claude_agent_sdk"),
        ("pyyaml", "yaml"),
        ("croniter", "croniter"),
        ("click", "click"),
        ("pydantic", "pydantic"),
    ]:
        try:
            __import__(import_name)
            click.echo(f"  [ok] {pkg_name}")
            ok_count += 1
        except ImportError:
            click.echo(f"  [!!] {pkg_name} not installed")
            issues.append(f"pip install {pkg_name}")

    # 4. Optional dependencies
    optional_deps = [
        ("fastapi", "fastapi", "API server"),
        ("uvicorn", "uvicorn", "API server"),
        ("discord.py", "discord", "Discord channel — pip install smolclaw[discord]"),
        ("watchfiles", "watchfiles", "hot-reload"),
        ("sqlite-vec", "sqlite_vec", "vector search — pip install smolclaw[all]"),
    ]
    for pkg_name, import_name, purpose in optional_deps:
        try:
            __import__(import_name)
            click.echo(f"  [ok] {pkg_name} (optional — {purpose})")
            ok_count += 1
        except ImportError:
            click.echo(f"  [--] {pkg_name} not installed (optional — {purpose})")

    # 5. Home directory
    if base.exists():
        click.echo(f"  [ok] Home directory: {base}")
        ok_count += 1
    else:
        click.echo(f"  [!!] Home directory not found: {base}")
        issues.append("Run 'smolclaw init' to set up")

    # 6. Agents
    agents_dir = base / "agents"
    if agents_dir.exists():
        agent_dirs = [d for d in agents_dir.iterdir() if d.is_dir() and (d / "agent.yaml").exists()]
        if agent_dirs:
            click.echo(f"  [ok] {len(agent_dirs)} agent(s) configured")
            ok_count += 1
            for agent_dir in agent_dirs:
                agent_issues = []
                if not (agent_dir / "soul.md").exists():
                    agent_issues.append("missing soul.md")
                if not (agent_dir / "agents.md").exists():
                    agent_issues.append("missing agents.md")
                if agent_issues:
                    click.echo(f"       {agent_dir.name}: {', '.join(agent_issues)}")
                    issues.extend(f"Agent '{agent_dir.name}': {issue}" for issue in agent_issues)
        else:
            click.echo("  [!!] No agents configured")
            issues.append("Run 'smolclaw add <name>' to create an agent")
    else:
        click.echo("  [--] No agents directory")

    # 7. Channel tokens
    if agents_dir.exists():
        for agent_dir in sorted(agents_dir.iterdir()):
            if not agent_dir.is_dir() or not (agent_dir / "agent.yaml").exists():
                continue
            try:
                agent_cfg = yaml.safe_load((agent_dir / "agent.yaml").read_text()) or {}
            except (yaml.YAMLError, OSError):
                continue

            channels_cfg = agent_cfg.get("channels", {})
            if not isinstance(channels_cfg, dict):
                continue

            # Load env files from agent's channels/ directory (same as gateway startup)
            channels_env_dir = agent_dir / "channels"
            agent_env: dict[str, str] = {}
            if channels_env_dir.exists():
                for env_file in channels_env_dir.glob("*.env"):
                    try:
                        for line in env_file.read_text().splitlines():
                            line = line.strip()
                            if line and not line.startswith("#") and "=" in line:
                                key, _, value = line.partition("=")
                                agent_env[key.strip()] = value.strip()
                    except OSError:
                        pass

            for ch_type, ch_cfg in channels_cfg.items():
                if not isinstance(ch_cfg, dict):
                    continue
                token_env = ch_cfg.get("token_env", "")
                if not token_env:
                    continue
                # Check both process env and agent's .env files
                token_set = token_env in os.environ or token_env in agent_env
                if token_set:
                    click.echo(f"  [ok] {agent_dir.name}/{ch_type}: {token_env} set")
                    ok_count += 1
                else:
                    click.echo(f"  [!!] {agent_dir.name}/{ch_type}: {token_env} not set")
                    issues.append(
                        f"Agent '{agent_dir.name}' channel '{ch_type}': "
                        f"env var {token_env} not found — "
                        f"add it to agents/{agent_dir.name}/channels/{ch_type}.env"
                    )

    # 8. Memory DB
    memory_db = base / "shared" / "memory.db"
    if memory_db.exists():
        try:
            conn = sqlite3.connect(str(memory_db), timeout=2.0)
            conn.execute("SELECT COUNT(*) FROM facts")
            conn.close()
            size_kb = memory_db.stat().st_size / 1024
            click.echo(f"  [ok] Memory DB: {size_kb:.0f} KB")
            ok_count += 1
        except Exception as e:
            click.echo(f"  [!!] Memory DB error: {e}")
            issues.append(f"Memory DB issue: {e}")
    else:
        click.echo("  [--] Memory DB not created yet (created on first gateway start)")

    # 9. Cron jobs
    jobs_path = base / "shared" / "cron" / "jobs.json"
    if jobs_path.exists():
        try:
            import json

            jobs_data = json.loads(jobs_path.read_text())
            total = len(jobs_data)
            enabled = sum(1 for j in jobs_data if j.get("enabled", True))
            failing = sum(1 for j in jobs_data if j.get("failures", 0) > 0)
            status_parts = [f"{total} jobs ({enabled} enabled)"]
            if failing:
                status_parts.append(f"{failing} with failures")
                click.echo(f"  [!!] Cron: {', '.join(status_parts)}")
                issues.append(f"{failing} cron job(s) have recorded failures")
            else:
                click.echo(f"  [ok] Cron: {', '.join(status_parts)}")
                ok_count += 1
        except (json.JSONDecodeError, OSError) as e:
            click.echo(f"  [!!] Cron jobs.json error: {e}")
            issues.append(f"Cron config issue: {e}")
    else:
        click.echo("  [--] No cron jobs configured")

    # 10. Port availability
    from .config import load_gateway_config

    if base.exists():
        config = load_gateway_config(base)
        import socket

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex((config.host, config.port))
            sock.close()
            if result == 0:
                click.echo(f"  [ok] Port {config.port} in use (gateway running)")
                ok_count += 1
            else:
                click.echo(f"  [ok] Port {config.port} available")
                ok_count += 1
        except Exception:
            click.echo(f"  [ok] Port {config.port} (could not check)")
            ok_count += 1

    # Summary
    click.echo(f"\n  {ok_count} checks passed", nl=False)
    if issues:
        click.echo(f", {len(issues)} issue(s):\n")
        for issue in issues:
            click.echo(f"    ! {issue}")
    else:
        click.echo(" — all good!")
    click.echo("")


LAUNCHAGENT_LABEL = "com.smolclaw.gateway"
SYSTEMD_SERVICE_NAME = "smolclaw"


def _plist_path() -> Path:
    """Return the LaunchAgent plist path for smolclaw."""
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHAGENT_LABEL}.plist"


def _systemd_unit_path() -> Path:
    """Return the systemd user service unit path for smolclaw."""
    return Path.home() / ".config" / "systemd" / "user" / f"{SYSTEMD_SERVICE_NAME}.service"


def _generate_plist(base: Path) -> str:
    """Generate a macOS LaunchAgent plist for auto-starting the gateway."""
    smolclaw_bin = shutil.which("smolclaw")
    if not smolclaw_bin:
        # Fall back to python -m smolclaw
        smolclaw_bin = sys.executable
        program_args = f"""\
    <array>
        <string>{smolclaw_bin}</string>
        <string>-m</string>
        <string>smolclaw</string>
        <string>--home</string>
        <string>{base}</string>
        <string>up</string>
    </array>"""
    else:
        program_args = f"""\
    <array>
        <string>{smolclaw_bin}</string>
        <string>--home</string>
        <string>{base}</string>
        <string>up</string>
    </array>"""

    # Build PATH from current environment
    env_path = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")

    log_dir = base / "logs"
    stdout_log = log_dir / "gateway.stdout.log"
    stderr_log = log_dir / "gateway.stderr.log"

    return f"""\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" \
"http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LAUNCHAGENT_LABEL}</string>

    <key>ProgramArguments</key>
    {program_args}

    <key>WorkingDirectory</key>
    <string>{Path.home()}</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>{env_path}</string>
        <key>HOME</key>
        <string>{Path.home()}</string>
        <key>LANG</key>
        <string>en_US.UTF-8</string>
    </dict>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>

    <key>StandardOutPath</key>
    <string>{stdout_log}</string>

    <key>StandardErrorPath</key>
    <string>{stderr_log}</string>

    <key>ThrottleInterval</key>
    <integer>10</integer>
</dict>
</plist>
"""


def _generate_systemd_unit(base: Path) -> str:
    """Generate a systemd user service unit for auto-starting the gateway.

    Creates a user-level service (no root required) that auto-starts on login
    and restarts on failure with exponential backoff.
    """
    smolclaw_bin = shutil.which("smolclaw")
    if smolclaw_bin:
        exec_start = f"{smolclaw_bin} --home {base} up"
    else:
        exec_start = f"{sys.executable} -m smolclaw --home {base} up"

    env_path = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")

    return f"""\
[Unit]
Description=smolclaw multi-agent gateway
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart={exec_start}
WorkingDirectory={Path.home()}
Environment=PATH={env_path}
Environment=HOME={Path.home()}
Environment=LANG=en_US.UTF-8
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
"""


def _install_macos(base: Path) -> None:
    """Install smolclaw as a macOS LaunchAgent."""
    plist = _plist_path()

    if plist.exists():
        click.echo(f"LaunchAgent already installed at {plist}")
        click.echo("Run 'smolclaw uninstall' first to reinstall.")
        return

    # Ensure logs directory exists
    (base / "logs").mkdir(parents=True, exist_ok=True)

    # Generate and write plist
    plist_content = _generate_plist(base)
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_text(plist_content)
    click.echo(f"  Created {plist}")

    # Load the agent
    result = subprocess.run(
        ["launchctl", "load", str(plist)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        click.echo(f"  Warning: launchctl load failed: {result.stderr.strip()}")
        click.echo("  You can load manually: launchctl load " + str(plist))
    else:
        click.echo("  Loaded — gateway will start now and on every login")

    click.echo(f"\n  Logs: {base / 'logs' / 'gateway.stdout.log'}")
    click.echo("  Stop: smolclaw uninstall")


def _install_linux(base: Path) -> None:
    """Install smolclaw as a systemd user service."""
    unit_path = _systemd_unit_path()

    if unit_path.exists():
        click.echo(f"Systemd service already installed at {unit_path}")
        click.echo("Run 'smolclaw uninstall' first to reinstall.")
        return

    # Ensure logs directory exists
    (base / "logs").mkdir(parents=True, exist_ok=True)

    # Generate and write unit file
    unit_content = _generate_systemd_unit(base)
    unit_path.parent.mkdir(parents=True, exist_ok=True)
    unit_path.write_text(unit_content)
    click.echo(f"  Created {unit_path}")

    # Reload systemd and enable
    result = subprocess.run(
        ["systemctl", "--user", "daemon-reload"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        click.echo(f"  Warning: daemon-reload failed: {result.stderr.strip()}")

    result = subprocess.run(
        ["systemctl", "--user", "enable", "--now", SYSTEMD_SERVICE_NAME],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        click.echo(f"  Warning: enable failed: {result.stderr.strip()}")
        click.echo(
            f"  You can start manually: systemctl --user enable --now {SYSTEMD_SERVICE_NAME}"
        )
    else:
        click.echo("  Enabled — gateway will start now and on every login")

    click.echo(f"\n  Status: systemctl --user status {SYSTEMD_SERVICE_NAME}")
    click.echo(f"  Logs:   journalctl --user -u {SYSTEMD_SERVICE_NAME} -f")
    click.echo("  Stop:   smolclaw uninstall")


def _uninstall_macos() -> None:
    """Uninstall the macOS LaunchAgent."""
    plist = _plist_path()

    if not plist.exists():
        click.echo("No LaunchAgent installed.")
        click.echo(f"  Expected: {plist}")
        return

    # Unload first
    result = subprocess.run(
        ["launchctl", "unload", str(plist)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        click.echo(f"  Warning: launchctl unload failed: {result.stderr.strip()}")

    # Remove plist
    plist.unlink()
    click.echo("  Unloaded and removed LaunchAgent")
    click.echo("  Gateway will no longer auto-start on login")


def _uninstall_linux() -> None:
    """Uninstall the systemd user service."""
    unit_path = _systemd_unit_path()

    if not unit_path.exists():
        click.echo("No systemd service installed.")
        click.echo(f"  Expected: {unit_path}")
        return

    # Stop and disable
    result = subprocess.run(
        ["systemctl", "--user", "disable", "--now", SYSTEMD_SERVICE_NAME],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        click.echo(f"  Warning: disable failed: {result.stderr.strip()}")

    # Remove unit file
    unit_path.unlink()

    # Reload daemon
    subprocess.run(
        ["systemctl", "--user", "daemon-reload"],
        capture_output=True,
        text=True,
    )

    click.echo("  Stopped and removed systemd service")
    click.echo("  Gateway will no longer auto-start on login")


@cli.command()
@click.pass_context
def install(ctx):
    """Install smolclaw as a login service.

    On macOS, generates a LaunchAgent plist. On Linux, generates a systemd
    user service. Both auto-start the gateway on login and restart on crash.
    Use 'smolclaw uninstall' to remove.
    """
    system = platform.system()
    base = ctx.obj["base"]

    if system == "Darwin":
        _install_macos(base)
    elif system == "Linux":
        _install_linux(base)
    else:
        click.echo(f"install does not support {system}.")
        click.echo("Supported: macOS (LaunchAgent), Linux (systemd).")
        sys.exit(1)


@cli.command()
def uninstall():
    """Remove the smolclaw login service.

    Removes the LaunchAgent (macOS) or systemd user service (Linux)
    that was created by 'smolclaw install'.
    """
    system = platform.system()

    if system == "Darwin":
        _uninstall_macos()
    elif system == "Linux":
        _uninstall_linux()
    else:
        click.echo(f"uninstall does not support {system}.")
        sys.exit(1)


def main() -> None:
    """CLI entry point invoked by the ``smolclaw`` console script."""
    cli()


if __name__ == "__main__":
    main()
