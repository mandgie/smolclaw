"""Tests for config loading and agent discovery."""

from __future__ import annotations

from pathlib import Path

from smolclaw.config import (
    AgentConfig,
    AgentInfo,
    ChannelConfig,
    GatewayConfig,
    MemoryConfig,
    discover_agent,
    discover_all_agents,
    discover_skills,
    load_agent_yaml,
    load_context_files,
    load_gateway_config,
    load_shared_user_md,
    load_text_file,
)


class TestModels:
    def test_channel_config_defaults(self):
        cfg = ChannelConfig(token_env="MY_TOKEN")
        assert cfg.token_env == "MY_TOKEN"
        assert cfg.authorized_users == []

    def test_memory_config_defaults(self):
        cfg = MemoryConfig()
        assert cfg.enabled is True
        assert cfg.cross_agent is False

    def test_agent_config_defaults(self):
        cfg = AgentConfig(name="test")
        assert cfg.model == "claude-sonnet-4-6"
        assert cfg.channels == {}
        assert cfg.memory.enabled is True

    def test_gateway_config_defaults(self):
        cfg = GatewayConfig()
        assert cfg.host == "127.0.0.1"
        assert cfg.port == 7890
        assert cfg.log_level == "INFO"


class TestLoaders:
    def test_load_text_file_exists(self, tmp_path: Path):
        f = tmp_path / "test.md"
        f.write_text("  Hello world  ")
        assert load_text_file(f) == "Hello world"

    def test_load_text_file_missing(self, tmp_path: Path):
        assert load_text_file(tmp_path / "nope.md") == ""

    def test_load_agent_yaml(self, agent_dir: Path):
        cfg = load_agent_yaml(agent_dir)
        assert cfg.name == "testagent"
        assert cfg.model == "claude-sonnet-4-6"

    def test_load_agent_yaml_missing(self, tmp_path: Path):
        import pytest

        with pytest.raises(FileNotFoundError):
            load_agent_yaml(tmp_path)

    def test_discover_skills_empty(self, agent_dir: Path):
        assert discover_skills(agent_dir) == []

    def test_discover_skills_with_skill(self, agent_dir: Path):
        skill_dir = agent_dir / "skills" / "myskill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# My Skill\nDo stuff.")
        skills = discover_skills(agent_dir)
        assert len(skills) == 1
        assert "My Skill" in skills[0]

    def test_load_context_files_empty(self, agent_dir: Path):
        assert load_context_files(agent_dir) == {}

    def test_load_context_files_with_files(self, agent_dir: Path):
        (agent_dir / "context" / "extra.md").write_text("Extra context here.")
        files = load_context_files(agent_dir)
        assert "extra" in files
        assert files["extra"] == "Extra context here."


class TestDiscovery:
    def test_discover_agent(self, agent_dir: Path):
        info = discover_agent(agent_dir)
        assert isinstance(info, AgentInfo)
        assert info.config.name == "testagent"
        assert "test agent" in info.soul.lower()
        assert info.agents_md != ""

    def test_discover_all_agents(self, tmp_base: Path, agent_dir: Path):
        agents = discover_all_agents(tmp_base)
        assert "testagent" in agents
        assert agents["testagent"].config.name == "testagent"

    def test_discover_all_agents_empty(self, tmp_path: Path):
        agents = discover_all_agents(tmp_path)
        assert agents == {}

    def test_discover_all_agents_skips_non_dirs(self, tmp_base: Path, agent_dir: Path):
        (tmp_base / "agents" / "not-a-dir.txt").write_text("nope")
        agents = discover_all_agents(tmp_base)
        assert "not-a-dir.txt" not in agents

    def test_discover_all_agents_skips_missing_yaml(self, tmp_base: Path, agent_dir: Path):
        (tmp_base / "agents" / "broken").mkdir()
        agents = discover_all_agents(tmp_base)
        assert "broken" not in agents


class TestGatewayConfig:
    def test_load_gateway_config(self, tmp_base: Path):
        cfg = load_gateway_config(tmp_base)
        assert cfg.port == 7890

    def test_load_gateway_config_missing(self, tmp_path: Path):
        cfg = load_gateway_config(tmp_path)
        assert cfg.port == 7890  # defaults

    def test_load_shared_user_md(self, tmp_base: Path):
        md = load_shared_user_md(tmp_base)
        assert "Test User" in md

    def test_load_shared_user_md_missing(self, tmp_path: Path):
        assert load_shared_user_md(tmp_path) == ""
