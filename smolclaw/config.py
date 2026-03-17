"""Configuration loading and agent discovery from filesystem."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator

log = logging.getLogger("smolclaw")

__all__ = [
    "AgentConfig",
    "AgentInfo",
    "ChannelConfig",
    "GatewayConfig",
    "MemoryConfig",
    "discover_agent",
    "discover_all_agents",
    "load_gateway_config",
]

# --- Agent Config (agent.yaml) ---


class ChannelConfig(BaseModel):
    """Configuration for a single channel (e.g. Telegram, webhook, Slack, Discord)."""

    token_env: str = ""
    app_token_env: str = Field(
        "",
        description="Secondary token env var (e.g. Slack app-level token for Socket Mode)",
    )
    authorized_users: list[int | str] = Field(default_factory=list)
    url: str = Field("", description="Webhook URL for outgoing messages")
    headers: dict[str, str] = Field(
        default_factory=dict, description="Extra HTTP headers for webhook requests"
    )


class MemoryConfig(BaseModel):
    """Memory settings for an agent."""

    enabled: bool = True
    cross_agent: bool = False


class AgentConfig(BaseModel):
    """Parsed agent.yaml — the structured part of an agent definition."""

    name: str
    model: str = "claude-sonnet-4-6"
    max_turns: int | None = Field(None, description="Max agent turns per query (prevents runaway)")
    max_budget_usd: float | None = Field(None, description="Per-run spending limit in USD")
    fallback_model: str | None = Field(None, description="Fallback model if primary is unavailable")
    output_format: dict[str, Any] | None = Field(
        None,
        description="Structured output schema — validated JSON output matching a schema",
    )
    enable_file_checkpointing: bool = Field(
        False, description="Enable file checkpointing for crash recovery"
    )
    mcp_servers: dict[str, dict[str, Any]] | str | None = Field(
        None,
        description="MCP server configs (dict of server defs) or path to mcp.json file",
    )
    thinking: dict[str, Any] | None = Field(
        None,
        description="Thinking config: {type: adaptive|enabled|disabled, budget_tokens: int}",
    )
    effort: Literal["low", "medium", "high", "max"] | None = Field(
        None, description="Reasoning effort level"
    )
    betas: list[str] = Field(
        default_factory=list, description="Beta features to enable (e.g. context-1m-2025-08-07)"
    )
    add_dirs: list[str] = Field(
        default_factory=list, description="Additional directories the agent can access"
    )
    channels: dict[str, ChannelConfig] = Field(default_factory=dict)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)


# --- Runtime Agent Info (discovered from filesystem) ---


class AgentInfo(BaseModel):
    """Complete agent information discovered from the filesystem."""

    config: AgentConfig
    path: Path
    soul: str = ""
    agents_md: str = ""
    skills: list[str] = Field(default_factory=list)
    context_files: dict[str, str] = Field(default_factory=dict)

    model_config = {"arbitrary_types_allowed": True}


# --- Gateway Config (config.yaml) ---


class GatewayConfig(BaseModel):
    """Top-level gateway configuration."""

    host: str = "127.0.0.1"
    port: int = 7890
    agents_dir: str = "agents"
    shared_dir: str = "shared"
    log_level: str = "INFO"
    api_key: str | None = Field(
        None,
        description="Optional API key for authenticating REST API requests. "
        "When set, clients must send 'Authorization: Bearer <key>' header.",
    )
    tracing: bool = Field(False, description="Enable OpenTelemetry tracing")
    tracing_exporter: str = Field("console", description="Tracing exporter: 'console' or 'otlp'")
    tracing_endpoint: str = Field("", description="OTLP endpoint URL (when exporter is 'otlp')")

    @field_validator("port")
    @classmethod
    def port_in_range(cls, v: int) -> int:
        """Validate that the port number is within the valid TCP range (1–65535)."""
        if not 1 <= v <= 65535:
            raise ValueError(f"port must be 1–65535, got {v}")
        return v


# --- Loader Functions ---


def load_agent_yaml(agent_dir: Path) -> AgentConfig:
    """Load and validate agent.yaml from an agent directory.

    Raises:
        FileNotFoundError: If agent.yaml doesn't exist.
        ValueError: If YAML is malformed or config fields are invalid.
    """
    yaml_path = agent_dir / "agent.yaml"
    if not yaml_path.exists():
        raise FileNotFoundError(f"No agent.yaml in {agent_dir}")

    try:
        with yaml_path.open() as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in {yaml_path}: {e}") from e

    if not isinstance(data, dict):
        raise ValueError(
            f"agent.yaml in {agent_dir} must be a YAML mapping, got {type(data).__name__}"
        )

    try:
        return AgentConfig(**data)
    except Exception as e:
        raise ValueError(f"Invalid config in {yaml_path}: {e}") from e


def load_text_file(path: Path) -> str:
    """Load a text file, return empty string if missing."""
    if path.exists():
        return path.read_text().strip()
    return ""


def discover_skills(agent_dir: Path) -> list[str]:
    """Scan skills/ folder and load all SKILL.md files.

    Gracefully skips skills that can't be read (e.g. permission errors,
    broken symlinks) and logs a warning instead of crashing.
    """
    skills_dir = agent_dir / "skills"
    if not skills_dir.exists():
        return []

    skills = []
    for skill_dir in sorted(skills_dir.iterdir()):
        skill_file = skill_dir / "SKILL.md"
        if skill_file.exists():
            try:
                skills.append(skill_file.read_text().strip())
            except OSError as e:
                log.warning(f"Failed to read skill {skill_dir.name}: {e}")
    return skills


def load_context_files(agent_dir: Path) -> dict[str, str]:
    """Load all .md files from context/ folder.

    Gracefully skips files that can't be read and logs a warning.
    """
    context_dir = agent_dir / "context"
    if not context_dir.exists():
        return {}

    files = {}
    for md_file in sorted(context_dir.glob("*.md")):
        try:
            files[md_file.stem] = md_file.read_text().strip()
        except OSError as e:
            log.warning(f"Failed to read context file {md_file.name}: {e}")
    return files


def discover_agent(agent_dir: Path) -> AgentInfo:
    """Discover a complete agent from its directory."""
    config = load_agent_yaml(agent_dir)
    return AgentInfo(
        config=config,
        path=agent_dir,
        soul=load_text_file(agent_dir / "soul.md"),
        agents_md=load_text_file(agent_dir / "agents.md"),
        skills=discover_skills(agent_dir),
        context_files=load_context_files(agent_dir),
    )


def discover_all_agents(base_dir: Path) -> dict[str, AgentInfo]:
    """Discover all agents in a base directory."""
    agents_dir = base_dir / "agents"
    if not agents_dir.exists():
        return {}

    agents = {}
    for agent_dir in sorted(agents_dir.iterdir()):
        if not agent_dir.is_dir():
            continue
        yaml_path = agent_dir / "agent.yaml"
        if not yaml_path.exists():
            continue
        try:
            agents[agent_dir.name] = discover_agent(agent_dir)
        except Exception as e:
            log.warning(f"Failed to load agent {agent_dir.name}: {e}")

    return agents


def load_gateway_config(base_dir: Path) -> GatewayConfig:
    """Load gateway config.yaml, or return defaults.

    Returns default config if the file doesn't exist.
    Raises ValueError with a helpful message if the file is malformed.
    """
    config_path = base_dir / "config.yaml"
    if not config_path.exists():
        return GatewayConfig()

    try:
        with config_path.open() as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        log.error(f"Invalid YAML in {config_path}: {e}")
        log.warning("Using default gateway configuration")
        return GatewayConfig()

    if not isinstance(data, dict):
        log.error(f"config.yaml must be a YAML mapping, got {type(data).__name__}")
        log.warning("Using default gateway configuration")
        return GatewayConfig()

    try:
        return GatewayConfig(**data)
    except Exception as e:
        log.error(f"Invalid gateway config in {config_path}: {e}")
        log.warning("Using default gateway configuration")
        return GatewayConfig()


def load_shared_user_md(base_dir: Path) -> str:
    """Load the shared USER.md file."""
    return load_text_file(base_dir / "shared" / "USER.md")
