"""Configuration loading and agent discovery from filesystem."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

log = logging.getLogger("smolclaw")

# --- Agent Config (agent.yaml) ---


class ChannelConfig(BaseModel):
    """Configuration for a single channel (e.g. Telegram)."""

    token_env: str
    authorized_users: list[int] = Field(default_factory=list)


class MemoryConfig(BaseModel):
    """Memory settings for an agent."""

    enabled: bool = True
    cross_agent: bool = False


class AgentConfig(BaseModel):
    """Parsed agent.yaml — the structured part of an agent definition."""

    name: str
    model: str = "claude-sonnet-4-6"
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


# --- Loader Functions ---


def load_agent_yaml(agent_dir: Path) -> AgentConfig:
    """Load and validate agent.yaml from an agent directory."""
    yaml_path = agent_dir / "agent.yaml"
    if not yaml_path.exists():
        raise FileNotFoundError(f"No agent.yaml in {agent_dir}")

    with open(yaml_path) as f:
        data = yaml.safe_load(f)

    return AgentConfig(**data)


def load_text_file(path: Path) -> str:
    """Load a text file, return empty string if missing."""
    if path.exists():
        return path.read_text().strip()
    return ""


def discover_skills(agent_dir: Path) -> list[str]:
    """Scan skills/ folder and load all SKILL.md files."""
    skills_dir = agent_dir / "skills"
    if not skills_dir.exists():
        return []

    skills = []
    for skill_dir in sorted(skills_dir.iterdir()):
        skill_file = skill_dir / "SKILL.md"
        if skill_file.exists():
            skills.append(skill_file.read_text().strip())
    return skills


def load_context_files(agent_dir: Path) -> dict[str, str]:
    """Load all .md files from context/ folder."""
    context_dir = agent_dir / "context"
    if not context_dir.exists():
        return {}

    files = {}
    for md_file in sorted(context_dir.glob("*.md")):
        files[md_file.stem] = md_file.read_text().strip()
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
    """Load gateway config.yaml, or return defaults."""
    config_path = base_dir / "config.yaml"
    if config_path.exists():
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
        return GatewayConfig(**data)
    return GatewayConfig()


def load_shared_user_md(base_dir: Path) -> str:
    """Load the shared USER.md file."""
    return load_text_file(base_dir / "shared" / "USER.md")
