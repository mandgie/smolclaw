"""Tests for CLI commands."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from smolclaw.cli import cli


class TestCli:
    def test_list_no_agents(self, tmp_path: Path):
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_path), "list"])
        assert result.exit_code == 0
        assert "No agents found" in result.output

    def test_add_agent(self, tmp_path: Path):
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_path), "add", "mybot"])
        assert result.exit_code == 0
        assert "Created agent 'mybot'" in result.output

        agent_dir = tmp_path / "agents" / "mybot"
        assert agent_dir.exists()
        assert (agent_dir / "agent.yaml").exists()
        assert (agent_dir / "soul.md").exists()
        assert (agent_dir / "agents.md").exists()

    def test_add_agent_duplicate(self, tmp_path: Path):
        runner = CliRunner()
        runner.invoke(cli, ["--home", str(tmp_path), "add", "mybot"])
        result = runner.invoke(cli, ["--home", str(tmp_path), "add", "mybot"])
        assert result.exit_code != 0
        assert "already exists" in result.output

    def test_list_agents(self, tmp_path: Path):
        runner = CliRunner()
        runner.invoke(cli, ["--home", str(tmp_path), "add", "alpha"])
        result = runner.invoke(cli, ["--home", str(tmp_path), "list"])
        assert result.exit_code == 0
        assert "alpha" in result.output

    def test_cron_list_no_jobs(self, tmp_path: Path):
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_path), "cron", "list"])
        assert result.exit_code == 0
        assert "No jobs" in result.output

    def test_add_skill_missing_shared(self, tmp_path: Path):
        runner = CliRunner()
        runner.invoke(cli, ["--home", str(tmp_path), "add", "mybot"])
        result = runner.invoke(cli, ["--home", str(tmp_path), "add-skill", "mybot", "nope"])
        assert result.exit_code != 0

    def test_scaffold_on_first_up(self, tmp_path: Path):
        """Verify _scaffold creates expected structure (without starting gateway)."""
        from smolclaw.cli import _scaffold

        _scaffold(tmp_path, agent_name="firstbot", model="claude-sonnet-4-6")

        assert (tmp_path / "shared" / "USER.md").exists()
        assert (tmp_path / "agents" / "firstbot" / "agent.yaml").exists()
        assert (tmp_path / "agents" / "firstbot" / "soul.md").exists()
        assert (tmp_path / "agents" / "firstbot" / "agents.md").exists()
        assert (tmp_path / "config.yaml").exists()

    def test_scaffold_idempotent(self, tmp_path: Path):
        """Running _scaffold twice doesn't overwrite existing files."""
        from smolclaw.cli import _scaffold

        _scaffold(tmp_path)
        # Modify a file
        user_md = tmp_path / "shared" / "USER.md"
        user_md.write_text("Custom content")

        # Run again
        _scaffold(tmp_path)
        assert user_md.read_text() == "Custom content"
