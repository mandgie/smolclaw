"""Tests for config loading and agent discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

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
        assert cfg.max_turns is None

    def test_agent_config_max_turns(self):
        cfg = AgentConfig(name="test", max_turns=25)
        assert cfg.max_turns == 25

    def test_agent_config_max_budget_usd(self):
        cfg = AgentConfig(name="test", max_budget_usd=5.0)
        assert cfg.max_budget_usd == 5.0

    def test_agent_config_max_budget_usd_default_none(self):
        cfg = AgentConfig(name="test")
        assert cfg.max_budget_usd is None

    def test_agent_config_fallback_model(self):
        cfg = AgentConfig(name="test", fallback_model="claude-haiku-4-5")
        assert cfg.fallback_model == "claude-haiku-4-5"

    def test_agent_config_fallback_model_default_none(self):
        cfg = AgentConfig(name="test")
        assert cfg.fallback_model is None

    def test_agent_config_output_format(self):
        schema = {"type": "json", "schema": {"type": "object"}}
        cfg = AgentConfig(name="test", output_format=schema)
        assert cfg.output_format == schema

    def test_agent_config_output_format_default_none(self):
        cfg = AgentConfig(name="test")
        assert cfg.output_format is None

    def test_agent_config_enable_file_checkpointing(self):
        cfg = AgentConfig(name="test", enable_file_checkpointing=True)
        assert cfg.enable_file_checkpointing is True

    def test_agent_config_enable_file_checkpointing_default_false(self):
        cfg = AgentConfig(name="test")
        assert cfg.enable_file_checkpointing is False

    def test_agent_config_mcp_servers_dict(self):
        servers = {"sqlite": {"type": "stdio", "command": "mcp-sqlite"}}
        cfg = AgentConfig(name="test", mcp_servers=servers)
        assert cfg.mcp_servers == servers

    def test_agent_config_mcp_servers_path(self):
        cfg = AgentConfig(name="test", mcp_servers="mcp.json")
        assert cfg.mcp_servers == "mcp.json"

    def test_agent_config_mcp_servers_default_none(self):
        cfg = AgentConfig(name="test")
        assert cfg.mcp_servers is None

    def test_agent_config_thinking_adaptive(self):
        cfg = AgentConfig(name="test", thinking={"type": "adaptive"})
        assert cfg.thinking == {"type": "adaptive"}

    def test_agent_config_thinking_enabled(self):
        cfg = AgentConfig(name="test", thinking={"type": "enabled", "budget_tokens": 32000})
        assert cfg.thinking["budget_tokens"] == 32000

    def test_agent_config_thinking_disabled(self):
        cfg = AgentConfig(name="test", thinking={"type": "disabled"})
        assert cfg.thinking["type"] == "disabled"

    def test_agent_config_thinking_default_none(self):
        cfg = AgentConfig(name="test")
        assert cfg.thinking is None

    def test_agent_config_effort(self):
        cfg = AgentConfig(name="test", effort="high")
        assert cfg.effort == "high"

    def test_agent_config_effort_default_none(self):
        cfg = AgentConfig(name="test")
        assert cfg.effort is None

    def test_agent_config_effort_invalid(self):
        with pytest.raises(ValueError):
            AgentConfig(name="test", effort="ultra")

    def test_agent_config_betas(self):
        cfg = AgentConfig(name="test", betas=["context-1m-2025-08-07"])
        assert cfg.betas == ["context-1m-2025-08-07"]

    def test_agent_config_betas_default_empty(self):
        cfg = AgentConfig(name="test")
        assert cfg.betas == []

    def test_agent_config_add_dirs(self):
        cfg = AgentConfig(name="test", add_dirs=["../shared", "/tmp/data"])
        assert cfg.add_dirs == ["../shared", "/tmp/data"]

    def test_agent_config_add_dirs_default_empty(self):
        cfg = AgentConfig(name="test")
        assert cfg.add_dirs == []

    def test_gateway_config_defaults(self):
        cfg = GatewayConfig()
        assert cfg.host == "127.0.0.1"
        assert cfg.port == 7890
        assert cfg.log_level == "INFO"

    def test_gateway_config_valid_port(self):
        cfg = GatewayConfig(port=8080)
        assert cfg.port == 8080

    def test_gateway_config_port_too_high(self):
        with pytest.raises(ValueError, match="port must be 1–65535"):
            GatewayConfig(port=99999)

    def test_gateway_config_port_zero(self):
        with pytest.raises(ValueError, match="port must be 1–65535"):
            GatewayConfig(port=0)

    def test_gateway_config_port_negative(self):
        with pytest.raises(ValueError, match="port must be 1–65535"):
            GatewayConfig(port=-1)


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
        with pytest.raises(FileNotFoundError):
            load_agent_yaml(tmp_path)

    def test_load_agent_yaml_malformed_yaml(self, tmp_path: Path):
        (tmp_path / "agent.yaml").write_text("name: test\n  bad_indent: oops")
        with pytest.raises(ValueError, match="Invalid YAML"):
            load_agent_yaml(tmp_path)

    def test_load_agent_yaml_not_a_mapping(self, tmp_path: Path):
        (tmp_path / "agent.yaml").write_text("- item1\n- item2\n")
        with pytest.raises(ValueError, match="must be a YAML mapping"):
            load_agent_yaml(tmp_path)

    def test_load_agent_yaml_invalid_field(self, tmp_path: Path):
        (tmp_path / "agent.yaml").write_text("name: test\nport: not_valid_field\n")
        # Unknown fields are silently ignored by Pydantic, but type errors are caught
        cfg = load_agent_yaml(tmp_path)
        assert cfg.name == "test"

    def test_load_agent_yaml_invalid_effort(self, tmp_path: Path):
        (tmp_path / "agent.yaml").write_text("name: test\neffort: ultra\n")
        with pytest.raises(ValueError, match="Invalid config"):
            load_agent_yaml(tmp_path)

    def test_load_agent_yaml_none_content(self, tmp_path: Path):
        (tmp_path / "agent.yaml").write_text("")
        with pytest.raises(ValueError, match="must be a YAML mapping"):
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

    def test_discover_skills_unreadable_file(self, agent_dir: Path):
        """A skill with an unreadable SKILL.md should be skipped, not crash."""
        from unittest.mock import patch

        skill_dir = agent_dir / "skills" / "broken"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# Broken Skill")

        with patch.object(Path, "read_text", side_effect=OSError("Permission denied")):
            skills = discover_skills(agent_dir)
        # Should return empty list — the broken skill was skipped
        assert skills == []

    def test_load_context_files_unreadable_file(self, agent_dir: Path):
        """A context file that can't be read should be skipped, not crash."""
        from unittest.mock import patch

        (agent_dir / "context" / "good.md").write_text("Good content")

        original_read = Path.read_text

        def selective_fail(self, *args, **kwargs):
            if "good" in str(self):
                raise OSError("Permission denied")
            return original_read(self, *args, **kwargs)

        with patch.object(Path, "read_text", selective_fail):
            files = load_context_files(agent_dir)
        assert "good" not in files

    def test_discover_skills_no_skills_dir(self, tmp_path: Path):
        """Agent with no skills/ directory returns empty list."""
        assert discover_skills(tmp_path) == []

    def test_load_context_files_no_context_dir(self, tmp_path: Path):
        """Agent with no context/ directory returns empty dict."""
        assert load_context_files(tmp_path) == {}


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

    def test_load_gateway_config_malformed_yaml(self, tmp_path: Path):
        """Malformed YAML in config.yaml should return defaults, not crash."""
        (tmp_path / "config.yaml").write_text("host: 127.0.0.1\n  bad: indent")
        cfg = load_gateway_config(tmp_path)
        assert cfg == GatewayConfig()

    def test_load_gateway_config_not_a_mapping(self, tmp_path: Path):
        """config.yaml with a list should return defaults, not crash."""
        (tmp_path / "config.yaml").write_text("- item1\n- item2\n")
        cfg = load_gateway_config(tmp_path)
        assert cfg == GatewayConfig()

    def test_load_gateway_config_invalid_port(self, tmp_path: Path):
        """config.yaml with an invalid port should return defaults, not crash."""
        (tmp_path / "config.yaml").write_text("port: 99999\n")
        cfg = load_gateway_config(tmp_path)
        assert cfg == GatewayConfig()

    def test_load_gateway_config_empty_file(self, tmp_path: Path):
        """Empty config.yaml should return defaults."""
        (tmp_path / "config.yaml").write_text("")
        cfg = load_gateway_config(tmp_path)
        assert cfg == GatewayConfig()
