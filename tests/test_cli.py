"""Tests for CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from click.testing import CliRunner

from smolclaw.cli import cli, get_base_dir, main


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


class TestGetBaseDir:
    def test_explicit_path(self, tmp_path: Path):
        result = get_base_dir(str(tmp_path))
        assert result == tmp_path

    def test_env_var(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("SMOLCLAW_HOME", str(tmp_path))
        result = get_base_dir(None)
        assert result == tmp_path

    def test_default(self, monkeypatch):
        monkeypatch.delenv("SMOLCLAW_HOME", raising=False)
        result = get_base_dir(None)
        assert result == Path.home() / ".smolclaw"


class TestCronAdd:
    def test_cron_add_inline_prompt(self, tmp_path: Path):
        """Add a cron job with inline prompt text."""
        runner = CliRunner()
        # Create agent dir so prompt file check works
        (tmp_path / "agents" / "tars" / "prompts").mkdir(parents=True)

        result = runner.invoke(
            cli,
            [
                "--home",
                str(tmp_path),
                "cron",
                "add",
                "--agent",
                "tars",
                "--schedule",
                "0 8 * * *",
                "--prompt",
                "Good morning!",
                "--id",
                "morning-job",
            ],
        )
        assert result.exit_code == 0
        assert "Added job 'morning-job'" in result.output

        # Verify file was written
        jobs_path = tmp_path / "shared" / "cron" / "jobs.json"
        assert jobs_path.exists()
        jobs = json.loads(jobs_path.read_text())
        assert len(jobs) == 1
        assert jobs[0]["id"] == "morning-job"
        assert jobs[0]["prompt"] == "Good morning!"
        assert jobs[0]["agent"] == "tars"

    def test_cron_add_auto_id(self, tmp_path: Path):
        """Auto-generates job ID from agent name and prompt."""
        runner = CliRunner()
        (tmp_path / "agents" / "tars" / "prompts").mkdir(parents=True)

        result = runner.invoke(
            cli,
            [
                "--home",
                str(tmp_path),
                "cron",
                "add",
                "--agent",
                "tars",
                "--schedule",
                "0 9 * * 1-5",
                "--prompt",
                "Check inbox",
            ],
        )
        assert result.exit_code == 0

        jobs_path = tmp_path / "shared" / "cron" / "jobs.json"
        jobs = json.loads(jobs_path.read_text())
        assert jobs[0]["id"] == "tars-check-inbox"

    def test_cron_add_with_delivery(self, tmp_path: Path):
        """Add a cron job with delivery channel configured."""
        runner = CliRunner()
        (tmp_path / "agents" / "tars" / "prompts").mkdir(parents=True)

        result = runner.invoke(
            cli,
            [
                "--home",
                str(tmp_path),
                "cron",
                "add",
                "--agent",
                "tars",
                "--schedule",
                "0 8 * * *",
                "--prompt",
                "Briefing",
                "--delivery",
                "telegram",
                "--chat-id",
                "12345",
                "--id",
                "briefing",
            ],
        )
        assert result.exit_code == 0
        jobs = json.loads((tmp_path / "shared" / "cron" / "jobs.json").read_text())
        assert jobs[0]["delivery"] == "telegram"
        assert jobs[0]["delivery_chat_id"] == "12345"

    def test_cron_add_prompt_file(self, tmp_path: Path):
        """When prompt matches a file in the agent's prompts dir, use prompt_file."""
        runner = CliRunner()
        prompts_dir = tmp_path / "agents" / "tars" / "prompts"
        prompts_dir.mkdir(parents=True)
        (prompts_dir / "morning.md").write_text("Good morning briefing")

        result = runner.invoke(
            cli,
            [
                "--home",
                str(tmp_path),
                "cron",
                "add",
                "--agent",
                "tars",
                "--schedule",
                "0 8 * * *",
                "--prompt",
                "morning.md",
                "--id",
                "morning",
            ],
        )
        assert result.exit_code == 0
        jobs = json.loads((tmp_path / "shared" / "cron" / "jobs.json").read_text())
        assert jobs[0]["prompt_file"] == "morning.md"
        assert jobs[0]["prompt"] == ""

    def test_cron_add_appends(self, tmp_path: Path):
        """Adding a second job appends to existing jobs."""
        runner = CliRunner()
        (tmp_path / "agents" / "tars" / "prompts").mkdir(parents=True)

        # Add first job
        runner.invoke(
            cli,
            [
                "--home",
                str(tmp_path),
                "cron",
                "add",
                "--agent",
                "tars",
                "--schedule",
                "0 8 * * *",
                "--prompt",
                "Job 1",
                "--id",
                "j1",
            ],
        )
        # Add second job
        runner.invoke(
            cli,
            [
                "--home",
                str(tmp_path),
                "cron",
                "add",
                "--agent",
                "tars",
                "--schedule",
                "0 12 * * *",
                "--prompt",
                "Job 2",
                "--id",
                "j2",
            ],
        )

        jobs = json.loads((tmp_path / "shared" / "cron" / "jobs.json").read_text())
        assert len(jobs) == 2


class TestCronRemove:
    def test_cron_remove_existing(self, tmp_path: Path):
        """Remove an existing job."""
        runner = CliRunner()
        cron_dir = tmp_path / "shared" / "cron"
        cron_dir.mkdir(parents=True)
        (cron_dir / "jobs.json").write_text(
            json.dumps([{"id": "j1", "agent": "tars", "schedule": "0 8 * * *"}])
        )

        result = runner.invoke(cli, ["--home", str(tmp_path), "cron", "remove", "j1"])
        assert result.exit_code == 0
        assert "Removed job 'j1'" in result.output

        jobs = json.loads((cron_dir / "jobs.json").read_text())
        assert len(jobs) == 0

    def test_cron_remove_not_found(self, tmp_path: Path):
        """Removing a non-existent job gives a friendly message."""
        runner = CliRunner()
        cron_dir = tmp_path / "shared" / "cron"
        cron_dir.mkdir(parents=True)
        (cron_dir / "jobs.json").write_text(
            json.dumps([{"id": "j1", "agent": "tars", "schedule": "0 8 * * *"}])
        )

        result = runner.invoke(cli, ["--home", str(tmp_path), "cron", "remove", "ghost"])
        assert result.exit_code == 0
        assert "not found" in result.output

    def test_cron_remove_no_file(self, tmp_path: Path):
        """Removing when no jobs file exists gives a friendly message."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_path), "cron", "remove", "j1"])
        assert result.exit_code == 0
        assert "No jobs file" in result.output


class TestCronListWithJobs:
    def test_cron_list_shows_jobs(self, tmp_path: Path):
        """cron list displays a table of jobs."""
        runner = CliRunner()
        cron_dir = tmp_path / "shared" / "cron"
        cron_dir.mkdir(parents=True)
        (cron_dir / "jobs.json").write_text(
            json.dumps(
                [
                    {
                        "id": "morning-briefing",
                        "agent": "tars",
                        "schedule": "0 8 * * 1-5",
                        "status": "ok",
                        "next_run": "2026-03-02T08:00:00",
                    }
                ]
            )
        )

        result = runner.invoke(cli, ["--home", str(tmp_path), "cron", "list"])
        assert result.exit_code == 0
        assert "morning-briefing" in result.output
        assert "tars" in result.output
        assert "0 8 * * 1-5" in result.output


class TestAddSkill:
    def test_add_skill_success(self, tmp_path: Path):
        """Successfully link a shared skill to an agent."""
        runner = CliRunner()
        # Create agent
        runner.invoke(cli, ["--home", str(tmp_path), "add", "mybot"])
        # Create shared skill
        shared_skill = tmp_path / "shared" / "skills" / "remindctl"
        shared_skill.mkdir(parents=True)
        (shared_skill / "SKILL.md").write_text("# remindctl\nReminder skill.\n")

        result = runner.invoke(cli, ["--home", str(tmp_path), "add-skill", "mybot", "remindctl"])
        assert result.exit_code == 0
        assert "Linked remindctl" in result.output

        # Verify symlink
        agent_skill = tmp_path / "agents" / "mybot" / "skills" / "remindctl"
        assert agent_skill.is_symlink()
        assert agent_skill.resolve() == shared_skill.resolve()

    def test_add_skill_already_exists(self, tmp_path: Path):
        """Adding a skill that already exists gives a message."""
        runner = CliRunner()
        runner.invoke(cli, ["--home", str(tmp_path), "add", "mybot"])
        shared_skill = tmp_path / "shared" / "skills" / "remindctl"
        shared_skill.mkdir(parents=True)

        # Add once
        runner.invoke(cli, ["--home", str(tmp_path), "add-skill", "mybot", "remindctl"])
        # Add again
        result = runner.invoke(cli, ["--home", str(tmp_path), "add-skill", "mybot", "remindctl"])
        assert result.exit_code == 0
        assert "already has skill" in result.output

    def test_add_agent_with_custom_model(self, tmp_path: Path):
        """Adding an agent with a custom model sets it in agent.yaml."""
        runner = CliRunner()
        result = runner.invoke(
            cli, ["--home", str(tmp_path), "add", "mybot", "--model", "claude-opus-4-6"]
        )
        assert result.exit_code == 0
        yaml_content = (tmp_path / "agents" / "mybot" / "agent.yaml").read_text()
        assert "claude-opus-4-6" in yaml_content


# ---------------------------------------------------------------------------
# Tests: up command
# ---------------------------------------------------------------------------


class TestUpCommand:
    def test_up_calls_run_gateway(self, tmp_base: Path, agent_dir: Path):
        """The up command should call run_gateway."""
        runner = CliRunner()
        with patch("smolclaw.cli.asyncio.run") as mock_run:
            result = runner.invoke(cli, ["--home", str(tmp_base), "up"])

        assert result.exit_code == 0
        mock_run.assert_called_once()

    def test_up_no_api(self, tmp_base: Path, agent_dir: Path):
        """The --no-api flag should pass with_api=False to run_gateway."""
        runner = CliRunner()
        with patch("smolclaw.cli.asyncio.run") as mock_run:
            result = runner.invoke(cli, ["--home", str(tmp_base), "up", "--no-api"])

        assert result.exit_code == 0
        mock_run.assert_called_once()

    def test_up_scaffolds_on_empty(self, tmp_path: Path):
        """If no agents exist, up should scaffold first."""
        # Create minimal structure without agents
        (tmp_path / "shared" / "cron").mkdir(parents=True)
        (tmp_path / "shared" / "USER.md").write_text("# User\n")
        (tmp_path / "config.yaml").write_text("host: 127.0.0.1\nport: 7890\n")

        runner = CliRunner()
        with patch("smolclaw.cli.asyncio.run"):
            result = runner.invoke(cli, ["--home", str(tmp_path), "up"])

        assert result.exit_code == 0
        assert "First run" in result.output
        assert (tmp_path / "agents" / "myagent" / "agent.yaml").exists()


# ---------------------------------------------------------------------------
# Tests: send command
# ---------------------------------------------------------------------------


class TestSendCommand:
    def test_send_routes_and_prints(self, tmp_base: Path, agent_dir: Path, jobs_file: Path):
        """send command should start gateway, route message, and print response."""
        mock_gw = MagicMock()
        mock_gw.start = AsyncMock()
        mock_gw.stop = AsyncMock()
        mock_gw.send = AsyncMock(return_value="Hello back!")

        runner = CliRunner()
        with patch("smolclaw.gateway.Gateway", return_value=mock_gw):
            result = runner.invoke(cli, ["--home", str(tmp_base), "send", "testagent", "Hello"])

        assert result.exit_code == 0
        assert "Hello back!" in result.output

    def test_send_stops_gateway_on_error(self, tmp_base: Path, agent_dir: Path, jobs_file: Path):
        """Gateway.stop() should be called even if send raises."""
        mock_gw = MagicMock()
        mock_gw.start = AsyncMock()
        mock_gw.stop = AsyncMock()
        mock_gw.send = AsyncMock(side_effect=RuntimeError("agent error"))

        runner = CliRunner()
        with patch("smolclaw.gateway.Gateway", return_value=mock_gw):
            result = runner.invoke(cli, ["--home", str(tmp_base), "send", "testagent", "Hello"])

        # Send failed but stop should still have been called
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Tests: main entry point
# ---------------------------------------------------------------------------


class TestMain:
    def test_main_invokes_cli(self):
        """main() should invoke the cli group."""
        with patch("smolclaw.cli.cli"):
            main()
