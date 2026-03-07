"""CLI entry point — smolclaw up, add, list, send, cron."""

from __future__ import annotations

import asyncio
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


@click.group()
@click.option("--home", envvar="SMOLCLAW_HOME", default=None, help="Base directory")
@click.pass_context
def cli(ctx, home):
    """smolclaw — lightweight multi-agent framework."""
    ctx.ensure_object(dict)
    ctx.obj["base"] = get_base_dir(home)


def _scaffold(base: Path, agent_name: str = "myagent", model: str = "claude-sonnet-4-6"):
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
@click.option("--agent", default="myagent", help="Name of the first agent to create")
@click.option("--model", default="claude-sonnet-4-6", help="Default model for the agent")
@click.pass_context
def init(ctx, agent, model):
    """Initialize a new smolclaw project directory."""
    base = ctx.obj["base"]

    if (base / "agents").exists() and any(
        d.is_dir() and (d / "agent.yaml").exists() for d in (base / "agents").iterdir()
    ):
        click.echo(f"smolclaw is already initialized at {base}")
        click.echo("Use 'smolclaw add <name>' to create additional agents.")
        return

    _scaffold(base, agent_name=agent, model=model)

    click.echo("Next steps:")
    click.echo(f"  1. Edit {base / 'agents' / agent / 'soul.md'} — define personality")
    click.echo(f"  2. Edit {base / 'shared' / 'USER.md'} — describe yourself")
    click.echo("  3. Run: smolclaw up")


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
        if size_kb > 1024:
            size_str = f"{size_kb / 1024:.1f} MB"
        else:
            size_str = f"{size_kb:.0f} KB"
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

    with open(config_path) as f:
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
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}

    # Coerce value to int if possible (for port)
    try:
        value = int(value)
    except ValueError:
        pass

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
@click.pass_context
def add(ctx, name, model):
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


@cli.command()
@click.argument("agent_name")
@click.argument("message")
@click.pass_context
def send(ctx, agent_name, message):
    """Send a one-shot message to an agent."""
    from .gateway import Gateway

    base = ctx.obj["base"]

    async def _send():
        gw = Gateway(base)
        await gw.start()
        try:
            response = await gw.send(agent_name, message)
            click.echo(response)
        finally:
            await gw.stop()

    asyncio.run(_send())


@cli.command()
@click.argument("agent_name")
@click.option("--no-api", is_flag=True, default=True, help="Start API server alongside chat")
@click.pass_context
def chat(ctx, agent_name, no_api):
    """Interactive chat session with an agent.

    Start a REPL-style conversation. Type messages and get responses.
    Commands: /new (reset session), /cost (show last cost), /quit (exit).
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

    async def _chat():
        setup_logging(base, level="WARNING")
        gw = Gateway(base)
        await gw.start()

        agent = gw.agents.get(agent_name)
        if not agent:
            click.echo(f"Agent '{agent_name}' failed to load.")
            await gw.stop()
            return

        click.echo(f"\nsmolclaw chat — {agent_name} ({agent_info.config.model})")
        click.echo("Type a message, or /new /cost /quit\n")

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
                if text.lower() == "/new":
                    await agent.new_session()
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
@click.pass_context
def cron_list(ctx):
    """List all scheduled jobs."""
    base = ctx.obj["base"]
    jobs_path = base / "shared" / "cron" / "jobs.json"

    if not jobs_path.exists():
        click.echo("No jobs configured.")
        return

    jobs = json.loads(jobs_path.read_text())
    click.echo(f"{'ID':<25} {'AGENT':<12} {'SCHEDULE':<20} {'STATUS':<8} {'NEXT RUN'}")
    click.echo("─" * 85)
    for job in jobs:
        click.echo(
            f"{job['id']:<25} {job['agent']:<12} {job['schedule']:<20} "
            f"{job.get('status', 'pending'):<8} {job.get('next_run', 'N/A')}"
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
                with open(log_path, encoding="utf-8") as f:
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
    if sys.version_info >= (3, 11):
        click.echo(f"  [ok] Python {py_ver}")
        ok_count += 1
    else:
        click.echo(f"  [!!] Python {py_ver} — requires 3.11+")
        issues.append("Python 3.11+ required")

    # 2. Claude CLI
    claude_path = shutil.which("claude")
    if claude_path:
        click.echo(f"  [ok] Claude CLI found: {claude_path}")
        ok_count += 1
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
    for pkg_name, import_name in [("fastapi", "fastapi"), ("uvicorn", "uvicorn")]:
        try:
            __import__(import_name)
            click.echo(f"  [ok] {pkg_name} (optional)")
            ok_count += 1
        except ImportError:
            click.echo(f"  [--] {pkg_name} not installed (optional — needed for API server)")

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

    # 7. Memory DB
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

    # 8. Port availability
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
                click.echo(f"  [!!] Port {config.port} already in use")
                issues.append(
                    f"Port {config.port} in use — change in config.yaml or stop the process"
                )
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


def _plist_path() -> Path:
    """Return the LaunchAgent plist path for smolclaw."""
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHAGENT_LABEL}.plist"


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


@cli.command()
@click.pass_context
def install(ctx):
    """Install smolclaw as a login service (macOS LaunchAgent).

    Generates a LaunchAgent plist so the gateway auto-starts on login
    and restarts if it crashes. Use 'smolclaw uninstall' to remove.
    """
    if platform.system() != "Darwin":
        click.echo("install currently supports macOS only.")
        click.echo("For Linux, create a systemd service manually.")
        sys.exit(1)

    base = ctx.obj["base"]
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


@cli.command()
def uninstall():
    """Remove the smolclaw login service (macOS LaunchAgent)."""
    if platform.system() != "Darwin":
        click.echo("uninstall currently supports macOS only.")
        sys.exit(1)

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


def main() -> None:
    """CLI entry point invoked by the ``smolclaw`` console script."""
    cli()


if __name__ == "__main__":
    main()
