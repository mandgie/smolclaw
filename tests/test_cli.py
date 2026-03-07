"""Tests for CLI commands."""

from __future__ import annotations

import json
import sys
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


class TestVersion:
    def test_version_output(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["version"])
        assert result.exit_code == 0
        assert "smolclaw 0.1.0" in result.output


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

    def test_cron_add_invalid_schedule(self, tmp_path: Path):
        """Invalid cron expression should fail with a clear error."""
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
                "not-a-cron",
                "--prompt",
                "Hello",
            ],
        )
        assert result.exit_code != 0
        # jobs.json should not have been created
        jobs_path = tmp_path / "shared" / "cron" / "jobs.json"
        assert not jobs_path.exists()


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


class TestInitCommand:
    def test_init_creates_structure(self, tmp_path: Path):
        """init should create full smolclaw directory structure."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_path), "init"])
        assert result.exit_code == 0
        assert "First run" in result.output
        assert "Next steps" in result.output

        # Verify structure
        assert (tmp_path / "agents" / "myagent" / "agent.yaml").exists()
        assert (tmp_path / "agents" / "myagent" / "soul.md").exists()
        assert (tmp_path / "agents" / "myagent" / "agents.md").exists()
        assert (tmp_path / "shared" / "USER.md").exists()
        assert (tmp_path / "config.yaml").exists()

    def test_init_custom_agent_name(self, tmp_path: Path):
        """init --agent sets the agent name."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_path), "init", "--agent", "tars"])
        assert result.exit_code == 0
        assert (tmp_path / "agents" / "tars" / "agent.yaml").exists()
        assert "tars" in result.output

    def test_init_custom_model(self, tmp_path: Path):
        """init --model sets the model in agent.yaml."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_path), "init", "--model", "claude-opus-4-6"])
        assert result.exit_code == 0
        yaml_content = (tmp_path / "agents" / "myagent" / "agent.yaml").read_text()
        assert "claude-opus-4-6" in yaml_content

    def test_init_already_initialized(self, tmp_base: Path, agent_dir: Path):
        """init on an existing project should warn and not overwrite."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_base), "init"])
        assert result.exit_code == 0
        assert "already initialized" in result.output


class TestStatusCommand:
    def test_status_no_home(self, tmp_path: Path):
        """status with no home directory should suggest init."""
        nonexistent = tmp_path / "nope"
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(nonexistent), "status"])
        assert result.exit_code == 0
        assert "No smolclaw home" in result.output

    def test_status_no_agents(self, tmp_base: Path):
        """status with no agents should suggest creating one."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_base), "status"])
        assert result.exit_code == 0
        assert "Agents: (none)" in result.output

    def test_status_with_agent(self, tmp_base: Path, agent_dir: Path):
        """status shows agent info in a table."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_base), "status"])
        assert result.exit_code == 0
        assert "testagent" in result.output
        assert "claude-sonnet-4-6" in result.output
        assert "on" in result.output  # memory enabled

    def test_status_shows_jobs(self, tmp_base: Path, agent_dir: Path, jobs_file: Path):
        """status shows scheduled jobs."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_base), "status"])
        assert result.exit_code == 0
        assert "1 scheduled" in result.output
        assert "test-job" in result.output

    def test_status_no_channels_issue(self, tmp_base: Path, agent_dir: Path):
        """status flags agents with no channels configured."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_base), "status"])
        assert result.exit_code == 0
        assert "no channels" in result.output

    def test_status_no_soul_issue(self, tmp_base: Path):
        """status flags agents with no soul.md."""
        # Create agent without soul.md
        agent = tmp_base / "agents" / "nosoul"
        for subdir in ["skills", "prompts", "context", "channels", "sessions"]:
            (agent / subdir).mkdir(parents=True)
        (agent / "agent.yaml").write_text(
            "name: nosoul\nmodel: claude-sonnet-4-6\nchannels: {}\nmemory:\n  enabled: true\n"
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_base), "status"])
        assert result.exit_code == 0
        assert "no soul.md" in result.output

    def test_status_memory_db(self, tmp_base: Path, agent_dir: Path):
        """status shows memory database info when it exists."""
        # Create a memory.db file
        db_path = tmp_base / "shared" / "memory.db"
        db_path.write_bytes(b"x" * 2048)

        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_base), "status"])
        assert result.exit_code == 0
        assert "Memory:" in result.output
        assert "KB" in result.output

    def test_status_no_memory_db(self, tmp_base: Path, agent_dir: Path):
        """status shows message when no memory.db exists."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_base), "status"])
        assert result.exit_code == 0
        assert "no database yet" in result.output

    def test_status_shows_api(self, tmp_base: Path, agent_dir: Path):
        """status shows the API endpoint."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_base), "status"])
        assert result.exit_code == 0
        assert "http://127.0.0.1:7890" in result.output

    def test_status_shows_sdk_extras(self, tmp_base: Path):
        """status shows extra SDK config (budget, fallback, etc.) when set."""
        agent = tmp_base / "agents" / "fancy"
        for subdir in ["skills", "prompts", "context", "channels", "sessions"]:
            (agent / subdir).mkdir(parents=True)
        (agent / "agent.yaml").write_text(
            "name: fancy\nmodel: claude-opus-4-6\n"
            "max_budget_usd: 5.0\nfallback_model: claude-sonnet-4-6\n"
            "enable_file_checkpointing: true\n"
        )
        (agent / "soul.md").write_text("Fancy agent")

        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_base), "status"])
        assert result.exit_code == 0
        assert "budget=$5.0" in result.output
        assert "fallback=claude-sonnet-4-6" in result.output
        assert "checkpointing" in result.output

    def test_status_shows_mcp_thinking_effort(self, tmp_base: Path):
        """status shows MCP, thinking, effort config when set."""
        agent = tmp_base / "agents" / "smart"
        for subdir in ["skills", "prompts", "context", "channels", "sessions"]:
            (agent / subdir).mkdir(parents=True)
        (agent / "agent.yaml").write_text(
            "name: smart\nmodel: claude-opus-4-6\n"
            "effort: high\n"
            "mcp_servers:\n  sqlite:\n    type: stdio\n    command: mcp-sqlite\n"
            "thinking:\n  type: enabled\n  budget_tokens: 16000\n"
            "betas:\n  - context-1m-2025-08-07\n"
            "add_dirs:\n  - ../shared\n"
        )
        (agent / "soul.md").write_text("Smart agent")

        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_base), "status"])
        assert result.exit_code == 0
        assert "mcp=[sqlite]" in result.output
        assert "thinking=enabled" in result.output
        assert "effort=high" in result.output
        assert "betas=" in result.output
        assert "add_dirs=1" in result.output


class TestRemoveCommand:
    def test_remove_agent(self, tmp_base: Path, agent_dir: Path):
        """remove should delete the agent directory."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_base), "remove", "testagent", "-y"])
        assert result.exit_code == 0
        assert "Removed agent 'testagent'" in result.output
        assert not agent_dir.exists()

    def test_remove_agent_not_found(self, tmp_base: Path):
        """remove a non-existent agent gives an error."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_base), "remove", "ghost", "-y"])
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_remove_agent_confirms(self, tmp_base: Path, agent_dir: Path):
        """remove without -y should prompt for confirmation."""
        runner = CliRunner()
        # Abort confirmation
        runner.invoke(cli, ["--home", str(tmp_base), "remove", "testagent"], input="n\n")
        assert agent_dir.exists()  # Should not be deleted

    def test_remove_agent_confirm_yes(self, tmp_base: Path, agent_dir: Path):
        """remove with confirmation 'y' should delete."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_base), "remove", "testagent"], input="y\n")
        assert result.exit_code == 0
        assert not agent_dir.exists()


class TestDoctorCommand:
    def test_doctor_basic(self, tmp_base: Path, agent_dir: Path):
        """doctor should run checks and report results."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_base), "doctor"])
        assert result.exit_code == 0
        assert "smolclaw doctor" in result.output
        assert "[ok] Python" in result.output
        assert "checks passed" in result.output

    def test_doctor_no_home(self, tmp_path: Path):
        """doctor with missing home shows an issue."""
        nonexistent = tmp_path / "nope"
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(nonexistent), "doctor"])
        assert result.exit_code == 0
        assert "[!!] Home directory not found" in result.output

    def test_doctor_checks_deps(self, tmp_base: Path, agent_dir: Path):
        """doctor should check key dependencies."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_base), "doctor"])
        assert result.exit_code == 0
        assert "pyyaml" in result.output
        assert "croniter" in result.output
        assert "pydantic" in result.output

    def test_doctor_no_agents(self, tmp_base: Path):
        """doctor flags when no agents are configured."""
        # Create agents dir but with no agent subdirs
        (tmp_base / "agents").mkdir(parents=True, exist_ok=True)
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_base), "doctor"])
        assert result.exit_code == 0
        assert "No agents configured" in result.output

    def test_doctor_memory_db(self, tmp_base: Path, agent_dir: Path):
        """doctor checks memory DB when it exists."""
        from smolclaw.memory import Memory

        db_path = tmp_base / "shared" / "memory.db"
        Memory(db_path, agent="test")  # Creates the DB with schema

        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_base), "doctor"])
        assert result.exit_code == 0
        assert "[ok] Memory DB" in result.output

    def test_doctor_port_available(self, tmp_base: Path, agent_dir: Path):
        """doctor checks port availability."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_base), "doctor"])
        assert result.exit_code == 0
        assert "Port" in result.output

    def test_doctor_missing_soul(self, tmp_base: Path):
        """doctor flags agents missing soul.md."""
        # Create agent without soul.md
        agent = tmp_base / "agents" / "nosoul"
        for subdir in ["skills", "prompts", "context", "channels", "sessions"]:
            (agent / subdir).mkdir(parents=True)
        (agent / "agent.yaml").write_text(
            "name: nosoul\nmodel: claude-sonnet-4-6\nchannels: {}\nmemory:\n  enabled: true\n"
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_base), "doctor"])
        assert result.exit_code == 0
        assert "missing soul.md" in result.output


class TestLogsCommand:
    def test_logs_no_file(self, tmp_path: Path):
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_path), "logs"])
        assert result.exit_code == 0
        assert "No log file found" in result.output
        assert "smolclaw up" in result.output

    def test_logs_shows_last_lines(self, tmp_path: Path):
        log_file = tmp_path / "smolclaw.log"
        lines = [f"line {i}" for i in range(100)]
        log_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_path), "logs", "-n", "5"])
        assert result.exit_code == 0
        assert "line 95" in result.output
        assert "line 99" in result.output
        assert "line 50" not in result.output

    def test_logs_default_50_lines(self, tmp_path: Path):
        log_file = tmp_path / "smolclaw.log"
        lines = [f"line {i}" for i in range(100)]
        log_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_path), "logs"])
        assert result.exit_code == 0
        assert "line 50" in result.output
        assert "line 99" in result.output
        assert "line 49" not in result.output

    def test_logs_small_file(self, tmp_path: Path):
        log_file = tmp_path / "smolclaw.log"
        log_file.write_text("only one line\n", encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_path), "logs"])
        assert result.exit_code == 0
        assert "only one line" in result.output

    def test_logs_empty_file(self, tmp_path: Path):
        log_file = tmp_path / "smolclaw.log"
        log_file.write_text("", encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_path), "logs"])
        assert result.exit_code == 0


class TestConfigCommand:
    def test_config_show(self, tmp_base: Path):
        """config without subcommand shows config.yaml contents."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_base), "config"])
        assert result.exit_code == 0
        assert "host:" in result.output
        assert "127.0.0.1" in result.output
        assert "port:" in result.output
        assert "7890" in result.output

    def test_config_show_no_file(self, tmp_path: Path):
        """config with no config.yaml shows helpful message."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_path), "config"])
        assert result.exit_code == 0
        assert "No config.yaml" in result.output
        assert "smolclaw init" in result.output

    def test_config_get(self, tmp_base: Path):
        """config get retrieves a specific value."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_base), "config", "get", "port"])
        assert result.exit_code == 0
        assert "7890" in result.output

    def test_config_get_string(self, tmp_base: Path):
        """config get retrieves a string value."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_base), "config", "get", "host"])
        assert result.exit_code == 0
        assert "127.0.0.1" in result.output

    def test_config_get_missing_key(self, tmp_base: Path):
        """config get with unknown key shows available keys."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_base), "config", "get", "nonexistent"])
        assert result.exit_code != 0
        assert "not found" in result.output
        assert "Available keys" in result.output

    def test_config_get_no_file(self, tmp_path: Path):
        """config get with no config.yaml fails."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_path), "config", "get", "port"])
        assert result.exit_code != 0
        assert "No config.yaml" in result.output

    def test_config_set(self, tmp_base: Path):
        """config set writes a value to config.yaml."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_base), "config", "set", "port", "8080"])
        assert result.exit_code == 0
        assert "Set port = 8080" in result.output

        # Verify it was written
        import yaml

        with open(tmp_base / "config.yaml") as f:
            data = yaml.safe_load(f)
        assert data["port"] == 8080

    def test_config_set_string(self, tmp_base: Path):
        """config set writes a string value."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_base), "config", "set", "host", "0.0.0.0"])
        assert result.exit_code == 0
        assert "Set host = 0.0.0.0" in result.output

    def test_config_set_invalid_port(self, tmp_base: Path):
        """config set rejects invalid port values."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_base), "config", "set", "port", "99999"])
        assert result.exit_code != 0
        assert "Invalid config" in result.output

    def test_config_set_creates_file(self, tmp_path: Path):
        """config set creates config.yaml if it doesn't exist."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_path), "config", "set", "port", "9000"])
        assert result.exit_code == 0
        assert (tmp_path / "config.yaml").exists()

    def test_config_set_log_level(self, tmp_base: Path):
        """config set works for log_level."""
        runner = CliRunner()
        result = runner.invoke(
            cli, ["--home", str(tmp_base), "config", "set", "log_level", "DEBUG"]
        )
        assert result.exit_code == 0
        assert "Set log_level = DEBUG" in result.output


class TestStatusEdgeCases:
    def test_status_jobs_json_error(self, tmp_base: Path, agent_dir: Path):
        """status handles corrupt jobs.json gracefully."""
        jobs_path = tmp_base / "shared" / "cron" / "jobs.json"
        jobs_path.write_text("not valid json{{{")

        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_base), "status"])
        assert result.exit_code == 0
        assert "error reading jobs.json" in result.output

    def test_status_many_jobs(self, tmp_base: Path, agent_dir: Path):
        """status truncates job list when more than 5 jobs."""
        jobs = [
            {"id": f"job-{i}", "agent": "testagent", "schedule": f"0 {i} * * *", "status": "ok"}
            for i in range(8)
        ]
        jobs_path = tmp_base / "shared" / "cron" / "jobs.json"
        jobs_path.write_text(json.dumps(jobs))

        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_base), "status"])
        assert result.exit_code == 0
        assert "and 3 more" in result.output

    def test_status_large_memory_db(self, tmp_base: Path, agent_dir: Path):
        """status shows MB for large memory databases."""
        db_path = tmp_base / "shared" / "memory.db"
        db_path.write_bytes(b"x" * (2 * 1024 * 1024))  # 2 MB

        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_base), "status"])
        assert result.exit_code == 0
        assert "MB" in result.output


class TestInstallCommand:
    def test_install_creates_plist(self, tmp_base: Path):
        """install creates a LaunchAgent plist and calls launchctl load."""
        runner = CliRunner()
        with (
            patch("smolclaw.cli._plist_path") as mock_plist_path,
            patch("smolclaw.cli.platform.system", return_value="Darwin"),
            patch("smolclaw.cli.subprocess.run") as mock_run,
        ):
            plist_file = tmp_base / "test.plist"
            mock_plist_path.return_value = plist_file
            mock_run.return_value = MagicMock(returncode=0)

            result = runner.invoke(cli, ["--home", str(tmp_base), "install"])

        assert result.exit_code == 0
        assert plist_file.exists()
        content = plist_file.read_text()
        assert "com.smolclaw.gateway" in content
        assert "RunAtLoad" in content
        assert "KeepAlive" in content
        assert str(tmp_base) in content
        mock_run.assert_called_once()

    def test_install_already_exists(self, tmp_base: Path):
        """install refuses if plist already exists."""
        runner = CliRunner()
        with (
            patch("smolclaw.cli._plist_path") as mock_plist_path,
            patch("smolclaw.cli.platform.system", return_value="Darwin"),
        ):
            plist_file = tmp_base / "test.plist"
            plist_file.write_text("existing")
            mock_plist_path.return_value = plist_file

            result = runner.invoke(cli, ["--home", str(tmp_base), "install"])

        assert result.exit_code == 0
        assert "already installed" in result.output

    def test_install_not_macos(self, tmp_base: Path):
        """install fails on non-macOS platforms."""
        runner = CliRunner()
        with patch("smolclaw.cli.platform.system", return_value="Linux"):
            result = runner.invoke(cli, ["--home", str(tmp_base), "install"])

        assert result.exit_code != 0
        assert "macOS only" in result.output

    def test_install_launchctl_failure(self, tmp_base: Path):
        """install warns if launchctl load fails."""
        runner = CliRunner()
        with (
            patch("smolclaw.cli._plist_path") as mock_plist_path,
            patch("smolclaw.cli.platform.system", return_value="Darwin"),
            patch("smolclaw.cli.subprocess.run") as mock_run,
        ):
            plist_file = tmp_base / "test.plist"
            mock_plist_path.return_value = plist_file
            mock_run.return_value = MagicMock(returncode=1, stderr="some error")

            result = runner.invoke(cli, ["--home", str(tmp_base), "install"])

        assert result.exit_code == 0
        assert "Warning" in result.output
        assert plist_file.exists()  # plist still created

    def test_install_creates_logs_dir(self, tmp_base: Path):
        """install creates the logs directory."""
        runner = CliRunner()
        with (
            patch("smolclaw.cli._plist_path") as mock_plist_path,
            patch("smolclaw.cli.platform.system", return_value="Darwin"),
            patch("smolclaw.cli.subprocess.run") as mock_run,
        ):
            plist_file = tmp_base / "test.plist"
            mock_plist_path.return_value = plist_file
            mock_run.return_value = MagicMock(returncode=0)

            result = runner.invoke(cli, ["--home", str(tmp_base), "install"])

        assert result.exit_code == 0
        assert (tmp_base / "logs").is_dir()


class TestUninstallCommand:
    def test_uninstall_removes_plist(self, tmp_base: Path):
        """uninstall unloads and removes the plist."""
        runner = CliRunner()
        with (
            patch("smolclaw.cli._plist_path") as mock_plist_path,
            patch("smolclaw.cli.platform.system", return_value="Darwin"),
            patch("smolclaw.cli.subprocess.run") as mock_run,
        ):
            plist_file = tmp_base / "test.plist"
            plist_file.write_text("plist content")
            mock_plist_path.return_value = plist_file
            mock_run.return_value = MagicMock(returncode=0)

            result = runner.invoke(cli, ["uninstall"])

        assert result.exit_code == 0
        assert not plist_file.exists()
        assert "Unloaded and removed" in result.output

    def test_uninstall_not_installed(self, tmp_base: Path):
        """uninstall with no plist gives a friendly message."""
        runner = CliRunner()
        with (
            patch("smolclaw.cli._plist_path") as mock_plist_path,
            patch("smolclaw.cli.platform.system", return_value="Darwin"),
        ):
            plist_file = tmp_base / "nonexistent.plist"
            mock_plist_path.return_value = plist_file

            result = runner.invoke(cli, ["uninstall"])

        assert result.exit_code == 0
        assert "No LaunchAgent installed" in result.output

    def test_uninstall_not_macos(self):
        """uninstall fails on non-macOS platforms."""
        runner = CliRunner()
        with patch("smolclaw.cli.platform.system", return_value="Linux"):
            result = runner.invoke(cli, ["uninstall"])

        assert result.exit_code != 0
        assert "macOS only" in result.output

    def test_uninstall_launchctl_failure(self, tmp_base: Path):
        """uninstall still removes plist even if launchctl unload fails."""
        runner = CliRunner()
        with (
            patch("smolclaw.cli._plist_path") as mock_plist_path,
            patch("smolclaw.cli.platform.system", return_value="Darwin"),
            patch("smolclaw.cli.subprocess.run") as mock_run,
        ):
            plist_file = tmp_base / "test.plist"
            plist_file.write_text("plist content")
            mock_plist_path.return_value = plist_file
            mock_run.return_value = MagicMock(returncode=1, stderr="error")

            result = runner.invoke(cli, ["uninstall"])

        assert result.exit_code == 0
        assert not plist_file.exists()


class TestGeneratePlist:
    def test_plist_contains_required_keys(self, tmp_base: Path):
        """Generated plist has all required LaunchAgent keys."""
        from smolclaw.cli import _generate_plist

        plist = _generate_plist(tmp_base)

        assert "com.smolclaw.gateway" in plist
        assert "<key>ProgramArguments</key>" in plist
        assert "<key>RunAtLoad</key>" in plist
        assert "<key>KeepAlive</key>" in plist
        assert "<key>WorkingDirectory</key>" in plist
        assert "<key>EnvironmentVariables</key>" in plist
        assert "<key>StandardOutPath</key>" in plist
        assert "<key>StandardErrorPath</key>" in plist
        assert "<key>ThrottleInterval</key>" in plist
        assert str(tmp_base) in plist

    def test_plist_uses_smolclaw_binary(self, tmp_base: Path):
        """When smolclaw is on PATH, plist uses the binary directly."""
        from smolclaw.cli import _generate_plist

        with patch("smolclaw.cli.shutil.which", return_value="/usr/local/bin/smolclaw"):
            plist = _generate_plist(tmp_base)

        assert "/usr/local/bin/smolclaw" in plist
        assert "<string>-m</string>" not in plist

    def test_plist_falls_back_to_python_m(self, tmp_base: Path):
        """When smolclaw binary not found, falls back to python -m smolclaw."""
        from smolclaw.cli import _generate_plist

        with patch("smolclaw.cli.shutil.which", return_value=None):
            plist = _generate_plist(tmp_base)

        assert sys.executable in plist
        assert "<string>-m</string>" in plist
        assert "<string>smolclaw</string>" in plist

    def test_plist_log_paths(self, tmp_base: Path):
        """Plist log paths point to the base/logs directory."""
        from smolclaw.cli import _generate_plist

        plist = _generate_plist(tmp_base)

        assert str(tmp_base / "logs" / "gateway.stdout.log") in plist
        assert str(tmp_base / "logs" / "gateway.stderr.log") in plist


class TestPlistPath:
    def test_plist_path_location(self):
        """Plist path is in ~/Library/LaunchAgents/."""
        from smolclaw.cli import _plist_path

        path = _plist_path()
        assert path.parent == Path.home() / "Library" / "LaunchAgents"
        assert path.name == "com.smolclaw.gateway.plist"


class TestChatCommand:
    def test_chat_agent_not_found(self, tmp_base: Path, agent_dir: Path, jobs_file: Path):
        """chat with nonexistent agent should error."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_base), "chat", "nosuchagent"])
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_chat_agent_not_found_shows_available(
        self, tmp_base: Path, agent_dir: Path, jobs_file: Path
    ):
        """chat with nonexistent agent shows available agents."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_base), "chat", "nosuchagent"])
        assert "testagent" in result.output

    def test_chat_quit_command(self, tmp_base: Path, agent_dir: Path, jobs_file: Path):
        """chat session exits on /quit."""
        mock_gw = MagicMock()
        mock_gw.start = AsyncMock()
        mock_gw.stop = AsyncMock()
        mock_agent = MagicMock()
        mock_agent.last_cost_usd = None
        mock_gw.agents = {"testagent": mock_agent}

        runner = CliRunner()
        with (
            patch("smolclaw.gateway.Gateway", return_value=mock_gw),
            patch("smolclaw.gateway.setup_logging"),
        ):
            result = runner.invoke(
                cli, ["--home", str(tmp_base), "chat", "testagent"], input="/quit\n"
            )

        assert result.exit_code == 0
        assert "Bye" in result.output

    def test_chat_exit_command(self, tmp_base: Path, agent_dir: Path, jobs_file: Path):
        """chat session exits on /exit."""
        mock_gw = MagicMock()
        mock_gw.start = AsyncMock()
        mock_gw.stop = AsyncMock()
        mock_gw.agents = {"testagent": MagicMock(last_cost_usd=None)}

        runner = CliRunner()
        with (
            patch("smolclaw.gateway.Gateway", return_value=mock_gw),
            patch("smolclaw.gateway.setup_logging"),
        ):
            result = runner.invoke(
                cli, ["--home", str(tmp_base), "chat", "testagent"], input="/exit\n"
            )

        assert result.exit_code == 0
        assert "Bye" in result.output

    def test_chat_new_session_command(self, tmp_base: Path, agent_dir: Path, jobs_file: Path):
        """chat /new resets the session."""
        mock_agent = MagicMock()
        mock_agent.new_session = AsyncMock()
        mock_agent.last_cost_usd = None
        mock_gw = MagicMock()
        mock_gw.start = AsyncMock()
        mock_gw.stop = AsyncMock()
        mock_gw.agents = {"testagent": mock_agent}

        runner = CliRunner()
        with (
            patch("smolclaw.gateway.Gateway", return_value=mock_gw),
            patch("smolclaw.gateway.setup_logging"),
        ):
            result = runner.invoke(
                cli, ["--home", str(tmp_base), "chat", "testagent"], input="/new\n/quit\n"
            )

        assert result.exit_code == 0
        assert "Session reset" in result.output
        mock_agent.new_session.assert_called_once()

    def test_chat_cost_command_no_data(self, tmp_base: Path, agent_dir: Path, jobs_file: Path):
        """chat /cost shows 'no data' when nothing sent yet."""
        mock_gw = MagicMock()
        mock_gw.start = AsyncMock()
        mock_gw.stop = AsyncMock()
        mock_gw.agents = {"testagent": MagicMock(last_cost_usd=None)}

        runner = CliRunner()
        with (
            patch("smolclaw.gateway.Gateway", return_value=mock_gw),
            patch("smolclaw.gateway.setup_logging"),
        ):
            result = runner.invoke(
                cli, ["--home", str(tmp_base), "chat", "testagent"], input="/cost\n/quit\n"
            )

        assert "No cost data yet" in result.output

    def test_chat_cost_command_with_data(self, tmp_base: Path, agent_dir: Path, jobs_file: Path):
        """chat /cost shows cost info after a message."""
        mock_agent = MagicMock()
        mock_agent.last_cost_usd = 0.0042
        mock_agent.last_usage = {"total_tokens": 1500}
        mock_agent.last_duration_ms = 3200
        mock_gw = MagicMock()
        mock_gw.start = AsyncMock()
        mock_gw.stop = AsyncMock()
        mock_gw.agents = {"testagent": mock_agent}

        runner = CliRunner()
        with (
            patch("smolclaw.gateway.Gateway", return_value=mock_gw),
            patch("smolclaw.gateway.setup_logging"),
        ):
            result = runner.invoke(
                cli, ["--home", str(tmp_base), "chat", "testagent"], input="/cost\n/quit\n"
            )

        assert "$0.0042" in result.output
        assert "1500" in result.output

    def test_chat_sends_message_and_shows_response(
        self, tmp_base: Path, agent_dir: Path, jobs_file: Path
    ):
        """chat sends user input to agent and prints response."""
        mock_agent = MagicMock()
        mock_agent.last_cost_usd = 0.001
        mock_agent.last_duration_ms = 500
        mock_gw = MagicMock()
        mock_gw.start = AsyncMock()
        mock_gw.stop = AsyncMock()
        mock_gw.send = AsyncMock(return_value="I am the test agent.")
        mock_gw.agents = {"testagent": mock_agent}

        runner = CliRunner()
        with (
            patch("smolclaw.gateway.Gateway", return_value=mock_gw),
            patch("smolclaw.gateway.setup_logging"),
        ):
            result = runner.invoke(
                cli,
                ["--home", str(tmp_base), "chat", "testagent"],
                input="Hello there\n/quit\n",
            )

        assert "I am the test agent." in result.output
        mock_gw.send.assert_called_once_with("testagent", "Hello there")

    def test_chat_handles_send_error(self, tmp_base: Path, agent_dir: Path, jobs_file: Path):
        """chat gracefully handles agent errors and continues."""
        mock_gw = MagicMock()
        mock_gw.start = AsyncMock()
        mock_gw.stop = AsyncMock()
        mock_gw.send = AsyncMock(side_effect=RuntimeError("connection lost"))
        mock_gw.agents = {"testagent": MagicMock(last_cost_usd=None)}

        runner = CliRunner()
        with (
            patch("smolclaw.gateway.Gateway", return_value=mock_gw),
            patch("smolclaw.gateway.setup_logging"),
        ):
            result = runner.invoke(
                cli,
                ["--home", str(tmp_base), "chat", "testagent"],
                input="Hello\n/quit\n",
            )

        assert "Error: connection lost" in result.output
        assert "Bye" in result.output

    def test_chat_header_shows_agent_info(self, tmp_base: Path, agent_dir: Path, jobs_file: Path):
        """chat header shows agent name and model."""
        mock_gw = MagicMock()
        mock_gw.start = AsyncMock()
        mock_gw.stop = AsyncMock()
        mock_gw.agents = {"testagent": MagicMock(last_cost_usd=None)}

        runner = CliRunner()
        with (
            patch("smolclaw.gateway.Gateway", return_value=mock_gw),
            patch("smolclaw.gateway.setup_logging"),
        ):
            result = runner.invoke(
                cli, ["--home", str(tmp_base), "chat", "testagent"], input="/quit\n"
            )

        assert "testagent" in result.output
        assert "claude-sonnet-4-6" in result.output

    def test_chat_empty_input_skipped(self, tmp_base: Path, agent_dir: Path, jobs_file: Path):
        """chat skips empty lines without sending."""
        mock_gw = MagicMock()
        mock_gw.start = AsyncMock()
        mock_gw.stop = AsyncMock()
        mock_gw.send = AsyncMock(return_value="response")
        mock_gw.agents = {"testagent": MagicMock(last_cost_usd=None)}

        runner = CliRunner()
        with (
            patch("smolclaw.gateway.Gateway", return_value=mock_gw),
            patch("smolclaw.gateway.setup_logging"),
        ):
            runner.invoke(
                cli,
                ["--home", str(tmp_base), "chat", "testagent"],
                input="  \n/quit\n",
            )

        mock_gw.send.assert_not_called()

    def test_chat_gateway_stopped_on_exit(self, tmp_base: Path, agent_dir: Path, jobs_file: Path):
        """Gateway.stop() is always called on exit."""
        mock_gw = MagicMock()
        mock_gw.start = AsyncMock()
        mock_gw.stop = AsyncMock()
        mock_gw.agents = {"testagent": MagicMock(last_cost_usd=None)}

        runner = CliRunner()
        with (
            patch("smolclaw.gateway.Gateway", return_value=mock_gw),
            patch("smolclaw.gateway.setup_logging"),
        ):
            runner.invoke(cli, ["--home", str(tmp_base), "chat", "testagent"], input="/quit\n")

        mock_gw.stop.assert_called_once()


class TestMain:
    def test_main_invokes_cli(self):
        """main() should invoke the cli group."""
        with patch("smolclaw.cli.cli"):
            main()
