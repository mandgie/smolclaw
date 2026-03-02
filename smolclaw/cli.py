"""CLI entry point — smolclaw up, add, list, send, cron."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import click

DEFAULT_BASE = Path.home() / ".smolclaw"


def get_base_dir(base: str | None = None) -> Path:
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


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
