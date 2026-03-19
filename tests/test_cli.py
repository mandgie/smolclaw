"""Tests for CLI commands."""

from __future__ import annotations

import builtins
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from click.testing import CliRunner

from smolclaw.cli import (
    _clear_session_file,
    _get_latest_version,
    _is_editable_install,
    _is_gateway_running,
    _load_session_id,
    _parse_version_tuple,
    _restart_gateway,
    _save_session_id,
    _session_file_path,
    _try_api_send,
    cli,
    get_base_dir,
    main,
)


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


class TestCronEnableDisable:
    def _make_jobs(self, tmp_path: Path, enabled: bool = True) -> Path:
        cron_dir = tmp_path / "shared" / "cron"
        cron_dir.mkdir(parents=True)
        jobs_path = cron_dir / "jobs.json"
        jobs_path.write_text(
            json.dumps(
                [
                    {
                        "id": "heartbeat",
                        "agent": "tars",
                        "schedule": "0 * * * *",
                        "enabled": enabled,
                        "status": "ok",
                    }
                ]
            )
        )
        return jobs_path

    def test_disable_job(self, tmp_path: Path):
        """Disabling a job sets enabled=false."""
        jobs_path = self._make_jobs(tmp_path, enabled=True)
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_path), "cron", "disable", "heartbeat"])
        assert result.exit_code == 0
        assert "disabled" in result.output
        jobs = json.loads(jobs_path.read_text())
        assert jobs[0]["enabled"] is False

    def test_enable_job(self, tmp_path: Path):
        """Enabling a disabled job sets enabled=true."""
        jobs_path = self._make_jobs(tmp_path, enabled=False)
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_path), "cron", "enable", "heartbeat"])
        assert result.exit_code == 0
        assert "enabled" in result.output
        jobs = json.loads(jobs_path.read_text())
        assert jobs[0]["enabled"] is True

    def test_disable_not_found(self, tmp_path: Path):
        """Disabling a non-existent job gives a friendly message."""
        self._make_jobs(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_path), "cron", "disable", "nonexistent"])
        assert result.exit_code == 0
        assert "not found" in result.output

    def test_enable_no_file(self, tmp_path: Path):
        """Enabling when no jobs file exists gives a friendly message."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_path), "cron", "enable", "j1"])
        assert result.exit_code == 0
        assert "No jobs file" in result.output

    def test_list_hides_disabled_by_default(self, tmp_path: Path):
        """cron list hides disabled jobs unless --all is passed."""
        cron_dir = tmp_path / "shared" / "cron"
        cron_dir.mkdir(parents=True)
        (cron_dir / "jobs.json").write_text(
            json.dumps(
                [
                    {
                        "id": "active-job",
                        "agent": "tars",
                        "schedule": "0 8 * * *",
                        "enabled": True,
                        "status": "ok",
                    },
                    {
                        "id": "disabled-job",
                        "agent": "tars",
                        "schedule": "0 12 * * *",
                        "enabled": False,
                        "status": "ok",
                    },
                ]
            )
        )
        runner = CliRunner()
        # Default: hide disabled
        result = runner.invoke(cli, ["--home", str(tmp_path), "cron", "list"])
        assert "active-job" in result.output
        assert "disabled-job" not in result.output

        # --all: show everything
        result = runner.invoke(cli, ["--home", str(tmp_path), "cron", "list", "--all"])
        assert "active-job" in result.output
        assert "disabled-job" in result.output


class TestCronRun:
    def test_cron_run_success(self, tmp_path: Path):
        """cron run triggers the job via the API and shows the response."""
        runner = CliRunner()
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {"status": "triggered", "job_id": "test-job", "response": "Job output!"}
        ).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = runner.invoke(cli, ["--home", str(tmp_path), "cron", "run", "test-job"])

        assert result.exit_code == 0
        assert "Triggered job" in result.output
        assert "Job output!" in result.output

    def test_cron_run_gateway_not_running(self, tmp_path: Path):
        """cron run shows error when gateway is not running."""
        import urllib.error

        runner = CliRunner()
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("Connection refused"),
        ):
            result = runner.invoke(cli, ["--home", str(tmp_path), "cron", "run", "test-job"])

        assert result.exit_code == 1
        assert "Gateway not running" in result.output

    def test_cron_run_job_not_found(self, tmp_path: Path):
        """cron run shows error when job ID doesn't exist."""
        import urllib.error

        runner = CliRunner()
        error = urllib.error.HTTPError("http://localhost", 404, "Not Found", {}, None)
        with patch("urllib.request.urlopen", side_effect=error):
            result = runner.invoke(cli, ["--home", str(tmp_path), "cron", "run", "nonexistent"])

        assert result.exit_code == 1
        assert "Error (404)" in result.output


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
        # Close the unawaited coroutine to suppress RuntimeWarning
        mock_run.call_args[0][0].close()

    def test_up_no_api(self, tmp_base: Path, agent_dir: Path):
        """The --no-api flag should pass with_api=False to run_gateway."""
        runner = CliRunner()
        with patch("smolclaw.cli.asyncio.run") as mock_run:
            result = runner.invoke(cli, ["--home", str(tmp_base), "up", "--no-api"])

        assert result.exit_code == 0
        mock_run.assert_called_once()
        # Close the unawaited coroutine to suppress RuntimeWarning
        mock_run.call_args[0][0].close()

    def test_up_scaffolds_on_empty(self, tmp_path: Path):
        """If no agents exist, up should scaffold first."""
        # Create minimal structure without agents
        (tmp_path / "shared" / "cron").mkdir(parents=True)
        (tmp_path / "shared" / "USER.md").write_text("# User\n")
        (tmp_path / "config.yaml").write_text("host: 127.0.0.1\nport: 7890\n")

        runner = CliRunner()
        with patch("smolclaw.cli.asyncio.run") as mock_run:
            result = runner.invoke(cli, ["--home", str(tmp_path), "up"])

        assert result.exit_code == 0
        assert "First run" in result.output
        assert (tmp_path / "agents" / "myagent" / "agent.yaml").exists()
        # Close the unawaited coroutine to suppress RuntimeWarning
        mock_run.call_args[0][0].close()


# ---------------------------------------------------------------------------
# Tests: send command
# ---------------------------------------------------------------------------


class TestTryApiSend:
    """Tests for _try_api_send — the fast-path API call."""

    def test_api_success(self, tmp_base: Path):
        """When the gateway API is running, _try_api_send returns the response."""

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"response": "API response"}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = _try_api_send(tmp_base, "testagent", "Hello")

        assert result == "API response"

    def test_api_not_running(self, tmp_base: Path):
        """When the gateway API is not running, _try_api_send returns None."""
        import urllib.error

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("Connection refused"),
        ):
            result = _try_api_send(tmp_base, "testagent", "Hello")

        assert result is None

    def test_api_bad_json(self, tmp_base: Path):
        """If the API returns invalid JSON, _try_api_send returns None."""

        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not json"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = _try_api_send(tmp_base, "testagent", "Hello")

        assert result is None

    def test_api_connection_error(self, tmp_base: Path):
        """OSError from urlopen should return None (not crash)."""

        with patch("urllib.request.urlopen", side_effect=OSError("Connection refused")):
            result = _try_api_send(tmp_base, "testagent", "Hello")

        assert result is None


class TestSendCommand:
    def test_send_uses_api_when_available(self, tmp_base: Path, agent_dir: Path, jobs_file: Path):
        """send should use API fast-path when gateway is running."""
        runner = CliRunner()
        with patch("smolclaw.cli._try_api_send", return_value="Fast response"):
            result = runner.invoke(cli, ["--home", str(tmp_base), "send", "testagent", "Hello"])

        assert result.exit_code == 0
        assert "Fast response" in result.output

    def test_send_falls_back_to_gateway(self, tmp_base: Path, agent_dir: Path, jobs_file: Path):
        """send should fall back to starting a gateway when API is not available."""
        mock_gw = MagicMock()
        mock_gw.start = AsyncMock()
        mock_gw.stop = AsyncMock()
        mock_gw.send = AsyncMock(return_value="Fallback response")

        runner = CliRunner()
        with (
            patch("smolclaw.cli._try_api_send", return_value=None),
            patch("smolclaw.gateway.Gateway", return_value=mock_gw),
        ):
            result = runner.invoke(cli, ["--home", str(tmp_base), "send", "testagent", "Hello"])

        assert result.exit_code == 0
        assert "Fallback response" in result.output

    def test_send_routes_and_prints(self, tmp_base: Path, agent_dir: Path, jobs_file: Path):
        """send command should start gateway, route message, and print response."""
        mock_gw = MagicMock()
        mock_gw.start = AsyncMock()
        mock_gw.stop = AsyncMock()
        mock_gw.send = AsyncMock(return_value="Hello back!")

        runner = CliRunner()
        with (
            patch("smolclaw.cli._try_api_send", return_value=None),
            patch("smolclaw.gateway.Gateway", return_value=mock_gw),
        ):
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
        with (
            patch("smolclaw.cli._try_api_send", return_value=None),
            patch("smolclaw.gateway.Gateway", return_value=mock_gw),
        ):
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

    def test_doctor_old_python(self, tmp_base: Path, agent_dir: Path):
        """doctor flags Python < 3.11."""
        runner = CliRunner()
        fake_version = MagicMock()
        fake_version.major = 3
        fake_version.minor = 10
        fake_version.micro = 0
        fake_version.__ge__ = lambda self, other: other <= (3, 10)
        with patch("smolclaw.cli.sys") as mock_sys:
            mock_sys.version_info = fake_version
            result = runner.invoke(cli, ["--home", str(tmp_base), "doctor"])
        assert result.exit_code == 0
        assert "requires 3.11+" in result.output

    def test_doctor_claude_cli_missing(self, tmp_base: Path, agent_dir: Path):
        """doctor flags when Claude CLI is not found."""
        runner = CliRunner()
        with patch("shutil.which", return_value=None):
            result = runner.invoke(cli, ["--home", str(tmp_base), "doctor"])
        assert result.exit_code == 0
        assert "Claude CLI not found" in result.output

    def test_doctor_missing_package(self, tmp_base: Path, agent_dir: Path):
        """doctor flags when a required package is missing."""
        runner = CliRunner()
        original_import = builtins.__import__

        def fail_croniter(name, *args, **kwargs):
            if name == "croniter":
                raise ImportError("no module named croniter")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fail_croniter):
            result = runner.invoke(cli, ["--home", str(tmp_base), "doctor"])
        assert result.exit_code == 0
        assert "croniter" in result.output
        assert "[!!]" in result.output

    def test_doctor_memory_db_error(self, tmp_base: Path, agent_dir: Path):
        """doctor handles corrupted memory DB gracefully."""
        db_path = tmp_base / "shared" / "memory.db"
        db_path.write_text("this is not a sqlite database")

        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_base), "doctor"])
        assert result.exit_code == 0
        assert "Memory DB error" in result.output

    def test_doctor_port_in_use(self, tmp_base: Path, agent_dir: Path):
        """doctor flags when the configured port is already in use."""
        import socket

        # Bind and listen on a socket to simulate a service occupying a port
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        _, port = sock.getsockname()

        # Write config with this port
        (tmp_base / "config.yaml").write_text(
            f"host: 127.0.0.1\nport: {port}\nshared_dir: shared\nagents_dir: agents\n"
        )

        try:
            runner = CliRunner()
            result = runner.invoke(cli, ["--home", str(tmp_base), "doctor"])
            assert result.exit_code == 0
            assert f"Port {port} already in use" in result.output
        finally:
            sock.close()


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

        with (tmp_base / "config.yaml").open() as f:
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


class TestUpdateCommand:
    """Tests for the smolclaw update command and its helpers."""

    def test_parse_version_tuple(self):
        assert _parse_version_tuple("0.1.0") == (0, 1, 0)
        assert _parse_version_tuple("1.2.3") == (1, 2, 3)
        assert _parse_version_tuple("0.10.0") > _parse_version_tuple("0.9.0")

    def test_check_shows_newer_version(self, tmp_base: Path):
        runner = CliRunner()
        with (
            patch("smolclaw.cli._get_latest_version", return_value=("0.2.0", "release")),
            patch("smolclaw.__version__", "0.1.0"),
        ):
            result = runner.invoke(cli, ["--home", str(tmp_base), "update", "--check"])

        assert result.exit_code == 0
        assert "0.2.0" in result.output
        assert "Update available" in result.output

    def test_check_already_latest(self, tmp_base: Path):
        runner = CliRunner()
        with (
            patch("smolclaw.cli._get_latest_version", return_value=("0.1.0", "release")),
            patch("smolclaw.__version__", "0.1.0"),
        ):
            result = runner.invoke(cli, ["--home", str(tmp_base), "update"])

        assert result.exit_code == 0
        assert "already up to date" in result.output

    def test_check_no_internet(self, tmp_base: Path):
        runner = CliRunner()
        with patch("smolclaw.cli._get_latest_version", return_value=(None, "")):
            result = runner.invoke(cli, ["--home", str(tmp_base), "update"])

        assert result.exit_code != 0
        assert "Could not check" in result.output

    def test_check_flag_does_not_install(self, tmp_base: Path):
        runner = CliRunner()
        with (
            patch("smolclaw.cli._get_latest_version", return_value=("0.2.0", "release")),
            patch("smolclaw.__version__", "0.1.0"),
            patch("smolclaw.cli.subprocess.run") as mock_run,
        ):
            result = runner.invoke(cli, ["--home", str(tmp_base), "update", "--check"])

        assert result.exit_code == 0
        mock_run.assert_not_called()

    def test_editable_install_warns(self, tmp_base: Path):
        runner = CliRunner()
        with (
            patch("smolclaw.cli._get_latest_version", return_value=("0.2.0", "release")),
            patch("smolclaw.__version__", "0.1.0"),
            patch("smolclaw.cli._is_editable_install", return_value=True),
        ):
            result = runner.invoke(cli, ["--home", str(tmp_base), "update"])

        assert result.exit_code == 0
        assert "editable" in result.output or "development" in result.output
        assert "git" in result.output

    def test_editable_install_force_proceeds(self, tmp_base: Path):
        runner = CliRunner()
        with (
            patch("smolclaw.cli._get_latest_version", return_value=("0.2.0", "release")),
            patch("smolclaw.__version__", "0.1.0"),
            patch("smolclaw.cli._is_editable_install", return_value=True),
            patch("smolclaw.cli._is_gateway_running", return_value=False),
            patch("smolclaw.cli.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="smolclaw 0.2.0", stderr="")
            result = runner.invoke(cli, ["--home", str(tmp_base), "update", "--force"])

        assert result.exit_code == 0
        assert mock_run.called

    def test_update_installs_via_pip(self, tmp_base: Path):
        runner = CliRunner()
        with (
            patch("smolclaw.cli._get_latest_version", return_value=("0.2.0", "release")),
            patch("smolclaw.__version__", "0.1.0"),
            patch("smolclaw.cli._is_editable_install", return_value=False),
            patch("smolclaw.cli._is_gateway_running", return_value=False),
            patch("smolclaw.cli.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="0.2.0", stderr="")
            result = runner.invoke(cli, ["--home", str(tmp_base), "update"])

        assert result.exit_code == 0
        # First call should be pip install
        pip_call = mock_run.call_args_list[0]
        assert "pip" in str(pip_call)
        assert "mandgie/smolclaw" in str(pip_call)

    def test_update_pip_failure(self, tmp_base: Path):
        runner = CliRunner()
        with (
            patch("smolclaw.cli._get_latest_version", return_value=("0.2.0", "release")),
            patch("smolclaw.__version__", "0.1.0"),
            patch("smolclaw.cli._is_editable_install", return_value=False),
            patch("smolclaw.cli._is_gateway_running", return_value=False),
            patch("smolclaw.cli.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
            result = runner.invoke(cli, ["--home", str(tmp_base), "update"])

        assert result.exit_code != 0
        assert "failed" in result.output.lower()

    def test_update_restarts_gateway(self, tmp_base: Path):
        runner = CliRunner()
        with (
            patch("smolclaw.cli._get_latest_version", return_value=("0.2.0", "release")),
            patch("smolclaw.__version__", "0.1.0"),
            patch("smolclaw.cli._is_editable_install", return_value=False),
            patch("smolclaw.cli._is_gateway_running", return_value=True),
            patch(
                "smolclaw.cli._restart_gateway",
                return_value="Gateway restarted via LaunchAgent.",
            ) as mock_restart,
            patch("smolclaw.cli.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="0.2.0", stderr="")
            result = runner.invoke(cli, ["--home", str(tmp_base), "update"])

        assert result.exit_code == 0
        mock_restart.assert_called_once()
        assert "restarted" in result.output.lower()

    def test_no_restart_flag(self, tmp_base: Path):
        runner = CliRunner()
        with (
            patch("smolclaw.cli._get_latest_version", return_value=("0.2.0", "release")),
            patch("smolclaw.__version__", "0.1.0"),
            patch("smolclaw.cli._is_editable_install", return_value=False),
            patch("smolclaw.cli._is_gateway_running", return_value=True),
            patch("smolclaw.cli._restart_gateway") as mock_restart,
            patch("smolclaw.cli.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="0.2.0", stderr="")
            result = runner.invoke(cli, ["--home", str(tmp_base), "update", "--no-restart"])

        assert result.exit_code == 0
        mock_restart.assert_not_called()
        assert "still running" in result.output.lower()

    def test_force_when_current(self, tmp_base: Path):
        runner = CliRunner()
        with (
            patch("smolclaw.cli._get_latest_version", return_value=("0.1.0", "release")),
            patch("smolclaw.__version__", "0.1.0"),
            patch("smolclaw.cli._is_editable_install", return_value=False),
            patch("smolclaw.cli._is_gateway_running", return_value=False),
            patch("smolclaw.cli.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="0.1.0", stderr="")
            result = runner.invoke(cli, ["--home", str(tmp_base), "update", "--force"])

        assert result.exit_code == 0
        assert mock_run.called

    def test_is_editable_install_false_by_default(self):
        """Non-editable installs return False."""
        with patch("importlib.metadata.distribution") as mock_dist:
            mock_dist.return_value.read_text.return_value = None
            assert _is_editable_install() is False

    def test_is_editable_install_true(self):
        """Editable install detected from direct_url.json."""
        with patch("importlib.metadata.distribution") as mock_dist:
            mock_dist.return_value.read_text.return_value = json.dumps(
                {"dir_info": {"editable": True}}
            )
            assert _is_editable_install() is True

    def test_is_gateway_running_false_when_down(self, tmp_base: Path):
        """Gateway not running returns False."""
        import urllib.error

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
            assert _is_gateway_running(tmp_base) is False

    def test_restart_gateway_no_launchagent(self, tmp_base: Path):
        """Restart without LaunchAgent returns manual restart message."""
        with patch("smolclaw.cli._plist_path") as mock_plist:
            mock_plist.return_value = tmp_base / "nonexistent.plist"
            msg = _restart_gateway(tmp_base)
        assert "manually" in msg.lower()

    def test_restart_gateway_with_launchagent(self, tmp_base: Path):
        """Restart with LaunchAgent calls launchctl."""
        plist_file = tmp_base / "test.plist"
        plist_file.write_text("plist content")
        with (
            patch("smolclaw.cli._plist_path", return_value=plist_file),
            patch("smolclaw.cli.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            msg = _restart_gateway(tmp_base)
        assert "restarted" in msg.lower()
        assert mock_run.call_count == 2  # unload + load


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

    def test_chat_help_command(self, tmp_base: Path, agent_dir: Path, jobs_file: Path):
        """chat /help shows available commands."""
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
                cli, ["--home", str(tmp_base), "chat", "testagent"], input="/help\n/quit\n"
            )

        assert "Commands:" in result.output
        assert "/new" in result.output
        assert "/cost" in result.output
        assert "/quit" in result.output
        assert "/help" in result.output

    def test_chat_help_aliases(self, tmp_base: Path, agent_dir: Path, jobs_file: Path):
        """chat /h and /? also show help."""
        mock_gw = MagicMock()
        mock_gw.start = AsyncMock()
        mock_gw.stop = AsyncMock()
        mock_gw.agents = {"testagent": MagicMock(last_cost_usd=None)}

        runner = CliRunner()
        for alias in ["/h", "/?"]:
            with (
                patch("smolclaw.gateway.Gateway", return_value=mock_gw),
                patch("smolclaw.gateway.setup_logging"),
            ):
                result = runner.invoke(
                    cli,
                    ["--home", str(tmp_base), "chat", "testagent"],
                    input=f"{alias}\n/quit\n",
                )
            assert "Commands:" in result.output

    def test_chat_session_persisted_after_message(
        self, tmp_base: Path, agent_dir: Path, jobs_file: Path
    ):
        """chat saves session_id to disk after a successful message."""
        mock_agent = MagicMock()
        mock_agent.last_cost_usd = 0.001
        mock_agent.last_duration_ms = 100
        mock_agent._session_id = "sess-abc-123"
        mock_gw = MagicMock()
        mock_gw.start = AsyncMock()
        mock_gw.stop = AsyncMock()
        mock_gw.send = AsyncMock(return_value="Hi there!")
        mock_gw.agents = {"testagent": mock_agent}

        runner = CliRunner()
        with (
            patch("smolclaw.gateway.Gateway", return_value=mock_gw),
            patch("smolclaw.gateway.setup_logging"),
        ):
            runner.invoke(
                cli,
                ["--home", str(tmp_base), "chat", "testagent"],
                input="Hello\n/quit\n",
            )

        session_file = _session_file_path(tmp_base, "testagent")
        assert session_file.exists()
        data = json.loads(session_file.read_text())
        assert data["session_id"] == "sess-abc-123"

    def test_chat_session_resumed_on_start(self, tmp_base: Path, agent_dir: Path, jobs_file: Path):
        """chat loads persisted session_id on start."""
        # Pre-save a session ID
        session_file = _session_file_path(tmp_base, "testagent")
        _save_session_id(session_file, "sess-saved-456")

        mock_agent = MagicMock()
        mock_agent.last_cost_usd = None
        mock_agent._session_id = None
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
                cli, ["--home", str(tmp_base), "chat", "testagent"], input="/quit\n"
            )

        assert "Resuming previous session" in result.output
        assert mock_agent._session_id == "sess-saved-456"

    def test_chat_new_session_clears_file(self, tmp_base: Path, agent_dir: Path, jobs_file: Path):
        """/new removes the persisted session file."""
        # Pre-save a session ID
        session_file = _session_file_path(tmp_base, "testagent")
        _save_session_id(session_file, "sess-old-789")

        mock_agent = MagicMock()
        mock_agent.new_session = AsyncMock()
        mock_agent.last_cost_usd = None
        mock_agent._session_id = "sess-old-789"
        mock_gw = MagicMock()
        mock_gw.start = AsyncMock()
        mock_gw.stop = AsyncMock()
        mock_gw.agents = {"testagent": mock_agent}

        runner = CliRunner()
        with (
            patch("smolclaw.gateway.Gateway", return_value=mock_gw),
            patch("smolclaw.gateway.setup_logging"),
        ):
            runner.invoke(
                cli,
                ["--home", str(tmp_base), "chat", "testagent"],
                input="/new\n/quit\n",
            )

        assert not session_file.exists()

    def test_chat_new_session_flag(self, tmp_base: Path, agent_dir: Path, jobs_file: Path):
        """--new-session flag ignores saved session."""
        # Pre-save a session ID
        session_file = _session_file_path(tmp_base, "testagent")
        _save_session_id(session_file, "sess-ignore-me")

        mock_agent = MagicMock()
        mock_agent.last_cost_usd = None
        mock_agent._session_id = None
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
                cli,
                ["--home", str(tmp_base), "chat", "testagent", "--new-session"],
                input="/quit\n",
            )

        assert "Resuming previous session" not in result.output
        # session_id should NOT have been set from saved file
        assert mock_agent._session_id is None


class TestSessionHelpers:
    """Tests for session persistence helper functions."""

    def test_session_file_path(self, tmp_base: Path):
        path = _session_file_path(tmp_base, "myagent")
        assert path == tmp_base / "agents" / "myagent" / "sessions" / "cli.json"

    def test_save_and_load_session_id(self, tmp_path: Path):
        session_file = tmp_path / "sessions" / "cli.json"
        _save_session_id(session_file, "sess-test-1")
        assert _load_session_id(session_file) == "sess-test-1"

    def test_load_session_id_missing_file(self, tmp_path: Path):
        session_file = tmp_path / "sessions" / "cli.json"
        assert _load_session_id(session_file) is None

    def test_load_session_id_bad_json(self, tmp_path: Path):
        session_file = tmp_path / "cli.json"
        session_file.write_text("not json")
        assert _load_session_id(session_file) is None

    def test_load_session_id_missing_key(self, tmp_path: Path):
        session_file = tmp_path / "cli.json"
        session_file.write_text("{}")
        assert _load_session_id(session_file) is None

    def test_clear_session_file(self, tmp_path: Path):
        session_file = tmp_path / "cli.json"
        _save_session_id(session_file, "sess-to-delete")
        assert session_file.exists()
        _clear_session_file(session_file)
        assert not session_file.exists()

    def test_clear_session_file_missing(self, tmp_path: Path):
        """Clearing a nonexistent file is a no-op."""
        session_file = tmp_path / "cli.json"
        _clear_session_file(session_file)  # Should not raise

    def test_save_creates_parent_dirs(self, tmp_path: Path):
        session_file = tmp_path / "deep" / "nested" / "cli.json"
        _save_session_id(session_file, "sess-nested")
        assert session_file.exists()
        assert _load_session_id(session_file) == "sess-nested"


def _setup_agent_with_memory(tmp_path: Path, agent_name: str = "tars") -> Path:
    """Scaffold a minimal agent at tmp_path and create a memory DB with test data."""
    from smolclaw.memory import Memory

    # Create agent directory structure
    agent_dir = tmp_path / "agents" / agent_name
    agent_dir.mkdir(parents=True)
    (agent_dir / "agent.yaml").write_text(
        f"name: {agent_name}\nmodel: claude-sonnet-4-6\nchannels: {{}}\n"
        "memory:\n  enabled: true\n  cross_agent: false\n"
    )
    (agent_dir / "soul.md").write_text(f"# {agent_name.upper()}\nTest agent.\n")
    for subdir in ["skills", "prompts", "context", "channels", "sessions"]:
        (agent_dir / subdir).mkdir(exist_ok=True)

    # Create shared dir + memory DB
    shared_dir = tmp_path / "shared"
    shared_dir.mkdir(parents=True, exist_ok=True)
    (shared_dir / "cron").mkdir(exist_ok=True)
    db_path = shared_dir / "memory.db"
    mem = Memory(db_path, agent=agent_name)
    mem.add_fact("Magnus likes coffee", category="preference")
    mem.add_fact("Saltfish is an AI company", category="company")
    mem.add_fact("Tove is Magnus's fiancee", category="family")
    return tmp_path


class TestMemoryCli:
    def test_memory_stats(self, tmp_path: Path):
        base = _setup_agent_with_memory(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(base), "memory", "stats", "tars"])
        assert result.exit_code == 0
        assert "Facts:    3" in result.output
        assert "tars" in result.output

    def test_memory_stats_no_db(self, tmp_path: Path):
        """Stats on non-existent DB shows helpful message."""
        runner = CliRunner()
        # Create a minimal agent but no memory DB
        agent_dir = tmp_path / "agents" / "bot"
        agent_dir.mkdir(parents=True)
        (agent_dir / "agent.yaml").write_text(
            "name: bot\nmodel: claude-sonnet-4-6\nchannels: {}\nmemory:\n  enabled: true\n"
        )
        (agent_dir / "soul.md").write_text("# BOT\n")
        for subdir in ["skills", "prompts", "context", "channels", "sessions"]:
            (agent_dir / subdir).mkdir(exist_ok=True)
        result = runner.invoke(cli, ["--home", str(tmp_path), "memory", "stats", "bot"])
        assert result.exit_code == 0
        assert "No memory database" in result.output

    def test_memory_stats_unknown_agent(self, tmp_path: Path):
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_path), "memory", "stats", "nobody"])
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_memory_list(self, tmp_path: Path):
        base = _setup_agent_with_memory(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(base), "memory", "list", "tars"])
        assert result.exit_code == 0
        assert "coffee" in result.output
        assert "3 fact(s)" in result.output

    def test_memory_list_with_category(self, tmp_path: Path):
        base = _setup_agent_with_memory(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(base), "memory", "list", "tars", "-c", "family"])
        assert result.exit_code == 0
        assert "Tove" in result.output
        assert "1 fact(s)" in result.output

    def test_memory_list_with_limit(self, tmp_path: Path):
        base = _setup_agent_with_memory(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(base), "memory", "list", "tars", "-n", "2"])
        assert result.exit_code == 0
        assert "2 fact(s)" in result.output

    def test_memory_list_empty(self, tmp_path: Path):
        base = _setup_agent_with_memory(tmp_path, agent_name="tars")
        runner = CliRunner()
        # Create a second agent with no facts
        agent_dir = base / "agents" / "empty"
        agent_dir.mkdir(parents=True)
        (agent_dir / "agent.yaml").write_text(
            "name: empty\nmodel: claude-sonnet-4-6\nchannels: {}\nmemory:\n  enabled: true\n"
        )
        (agent_dir / "soul.md").write_text("# EMPTY\n")
        for subdir in ["skills", "prompts", "context", "channels", "sessions"]:
            (agent_dir / subdir).mkdir(exist_ok=True)
        result = runner.invoke(cli, ["--home", str(base), "memory", "list", "empty"])
        assert result.exit_code == 0
        assert "No facts found" in result.output

    def test_memory_search(self, tmp_path: Path):
        base = _setup_agent_with_memory(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(base), "memory", "search", "tars", "coffee"])
        assert result.exit_code == 0
        assert "coffee" in result.output
        assert "1 result(s)" in result.output

    def test_memory_search_no_results(self, tmp_path: Path):
        base = _setup_agent_with_memory(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli, ["--home", str(base), "memory", "search", "tars", "nonexistent_xyz"]
        )
        assert result.exit_code == 0
        assert "No results" in result.output

    def test_memory_add(self, tmp_path: Path):
        base = _setup_agent_with_memory(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(base), "memory", "add", "tars", "New fact here"])
        assert result.exit_code == 0
        assert "Added fact #" in result.output
        assert "general" in result.output

    def test_memory_add_with_category(self, tmp_path: Path):
        base = _setup_agent_with_memory(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--home", str(base), "memory", "add", "tars", "Work stuff", "-c", "work"],
        )
        assert result.exit_code == 0
        assert "work" in result.output

    def test_memory_delete(self, tmp_path: Path):
        base = _setup_agent_with_memory(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(base), "memory", "delete", "tars", "1"])
        assert result.exit_code == 0
        assert "Deleted fact #1" in result.output

    def test_memory_delete_not_found(self, tmp_path: Path):
        base = _setup_agent_with_memory(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(base), "memory", "delete", "tars", "999"])
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_memory_get(self, tmp_path: Path):
        base = _setup_agent_with_memory(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(base), "memory", "get", "tars", "1"])
        assert result.exit_code == 0
        assert "ID:" in result.output
        assert "Category:" in result.output
        assert "Content:" in result.output

    def test_memory_get_not_found(self, tmp_path: Path):
        base = _setup_agent_with_memory(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(base), "memory", "get", "tars", "999"])
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_memory_update_content(self, tmp_path: Path):
        base = _setup_agent_with_memory(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--home", str(base), "memory", "update", "tars", "1", "--content", "Updated fact"],
        )
        assert result.exit_code == 0
        assert "Updated fact #1" in result.output
        assert "content" in result.output

    def test_memory_update_category(self, tmp_path: Path):
        base = _setup_agent_with_memory(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--home", str(base), "memory", "update", "tars", "1", "-c", "work"],
        )
        assert result.exit_code == 0
        assert "Updated fact #1" in result.output
        assert "work" in result.output

    def test_memory_update_both(self, tmp_path: Path):
        base = _setup_agent_with_memory(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "--home",
                str(base),
                "memory",
                "update",
                "tars",
                "1",
                "--content",
                "New content",
                "-c",
                "decision",
            ],
        )
        assert result.exit_code == 0
        assert "content" in result.output
        assert "decision" in result.output

    def test_memory_update_nothing(self, tmp_path: Path):
        """Update with no --content or --category should fail."""
        base = _setup_agent_with_memory(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(base), "memory", "update", "tars", "1"])
        assert result.exit_code != 0
        assert "Nothing to update" in result.output

    def test_memory_update_not_found(self, tmp_path: Path):
        base = _setup_agent_with_memory(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--home", str(base), "memory", "update", "tars", "999", "--content", "x"],
        )
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_memory_get_then_update_roundtrip(self, tmp_path: Path):
        """Get a fact, update it, get it again to verify the change."""
        base = _setup_agent_with_memory(tmp_path)
        runner = CliRunner()

        # Get original
        result = runner.invoke(cli, ["--home", str(base), "memory", "get", "tars", "1"])
        assert result.exit_code == 0

        # Update content
        result = runner.invoke(
            cli,
            ["--home", str(base), "memory", "update", "tars", "1", "--content", "I love tea now"],
        )
        assert result.exit_code == 0

        # Get updated
        result = runner.invoke(cli, ["--home", str(base), "memory", "get", "tars", "1"])
        assert result.exit_code == 0
        assert "tea" in result.output

    def test_memory_list_long_content_truncated(self, tmp_path: Path):
        """Long fact content gets truncated in list output."""
        from smolclaw.memory import Memory

        base = _setup_agent_with_memory(tmp_path)
        db_path = base / "shared" / "memory.db"
        mem = Memory(db_path, agent="tars")
        mem.add_fact("A" * 200, category="test")

        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(base), "memory", "list", "tars"])
        assert result.exit_code == 0
        assert "..." in result.output


class TestMain:
    def test_main_invokes_cli(self):
        """main() should invoke the cli group."""
        with patch("smolclaw.cli.cli"):
            main()


class TestGetLatestVersion:
    """Tests for _get_latest_version() — direct unit tests of the network function."""

    def test_release_api_success(self):
        """GitHub release API returns version."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"tag_name": "v0.2.0"}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            ver, source = _get_latest_version()
        assert ver == "0.2.0"
        assert source == "release"

    def test_release_api_fails_pyproject_fallback(self):
        """When release API fails, falls back to pyproject.toml on main."""
        import urllib.error

        pyproject_content = b'[project]\nversion = "0.3.1"\n'
        mock_resp = MagicMock()
        mock_resp.read.return_value = pyproject_content
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        def side_effect(req, **kwargs):
            if "releases" in (req.full_url if hasattr(req, "full_url") else req):
                raise urllib.error.HTTPError("url", 404, "Not Found", {}, None)
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=side_effect):
            ver, source = _get_latest_version()
        assert ver == "0.3.1"
        assert source == "main"

    def test_both_fail_returns_none(self):
        """When both release API and pyproject.toml fail, returns (None, '')."""
        import urllib.error

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("no network"),
        ):
            ver, source = _get_latest_version()
        assert ver is None
        assert source == ""

    def test_release_api_empty_tag(self):
        """Release API with empty tag falls through to pyproject fallback."""
        import urllib.error

        mock_resp_release = MagicMock()
        mock_resp_release.read.return_value = json.dumps({"tag_name": ""}).encode()
        mock_resp_release.__enter__ = lambda s: s
        mock_resp_release.__exit__ = MagicMock(return_value=False)

        call_count = 0

        def side_effect(req, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_resp_release  # Empty tag
            raise urllib.error.URLError("no pyproject")

        with patch("urllib.request.urlopen", side_effect=side_effect):
            ver, source = _get_latest_version()
        assert ver is None
        assert source == ""


class TestIsEditableInstallEdgeCases:
    """Extra edge cases for _is_editable_install."""

    def test_exception_returns_false(self):
        """Any exception during metadata lookup returns False."""
        with patch("importlib.metadata.distribution", side_effect=RuntimeError("boom")):
            assert _is_editable_install() is False


class TestIsGatewayRunningEdgeCases:
    """Edge cases for _is_gateway_running."""

    def test_config_load_exception_returns_false(self, tmp_path: Path):
        """Config load failure returns False."""
        with patch("smolclaw.config.load_gateway_config", side_effect=Exception("bad config")):
            assert _is_gateway_running(tmp_path) is False

    def test_gateway_running_returns_true(self, tmp_base: Path):
        """Successful API probe returns True."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            assert _is_gateway_running(tmp_base) is True


class TestRestartGatewayEdgeCases:
    """Edge cases for _restart_gateway."""

    def test_launchctl_load_failure(self, tmp_base: Path):
        """Launchctl load failure returns error message."""
        plist_file = tmp_base / "test.plist"
        plist_file.write_text("plist content")

        def mock_run_side_effect(*args, **kwargs):
            cmd = args[0]
            result = MagicMock()
            if "unload" in cmd:
                result.returncode = 0
            else:
                result.returncode = 1
                result.stderr = "Load failed: already loaded"
            return result

        with (
            patch("smolclaw.cli._plist_path", return_value=plist_file),
            patch("smolclaw.cli.subprocess.run", side_effect=mock_run_side_effect),
        ):
            msg = _restart_gateway(tmp_base)
        assert "failed" in msg.lower()


class TestCronRunConfigReading:
    """Tests for cron run reading port and api_key from config.yaml."""

    def test_cron_run_reads_custom_port(self, tmp_base: Path):
        """cron run uses custom port from config.yaml."""
        import urllib.error

        # Write config with custom port
        (tmp_base / "config.yaml").write_text("host: 127.0.0.1\nport: 9999\n")

        runner = CliRunner()
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("Connection refused"),
        ) as mock_open:
            result = runner.invoke(cli, ["--home", str(tmp_base), "cron", "run", "test-job"])

        assert result.exit_code == 1
        # Verify URL uses port 9999
        call_args = mock_open.call_args[0][0]
        assert "9999" in call_args.full_url

    def test_cron_run_reads_custom_host(self, tmp_base: Path):
        """cron run uses custom host from config.yaml."""
        import urllib.error

        (tmp_base / "config.yaml").write_text("host: 0.0.0.0\nport: 7890\n")

        runner = CliRunner()
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("Connection refused"),
        ) as mock_open:
            result = runner.invoke(cli, ["--home", str(tmp_base), "cron", "run", "test-job"])

        assert result.exit_code == 1
        call_args = mock_open.call_args[0][0]
        assert "0.0.0.0" in call_args.full_url

    def test_cron_run_reads_api_key(self, tmp_base: Path):
        """cron run includes auth header when api_key is configured."""
        (tmp_base / "config.yaml").write_text(
            "host: 127.0.0.1\nport: 7890\napi_key: secret-key-123\n"
        )

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {"status": "triggered", "job_id": "j", "response": "ok"}
        ).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        runner = CliRunner()
        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            result = runner.invoke(cli, ["--home", str(tmp_base), "cron", "run", "test-job"])

        assert result.exit_code == 0
        req = mock_open.call_args[0][0]
        assert req.get_header("Authorization") == "Bearer secret-key-123"

    def test_cron_run_bad_config_yaml(self, tmp_base: Path):
        """cron run handles malformed config.yaml gracefully."""
        import urllib.error

        (tmp_base / "config.yaml").write_text("not: valid: yaml: [[[")

        runner = CliRunner()
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("Connection refused"),
        ):
            result = runner.invoke(cli, ["--home", str(tmp_base), "cron", "run", "test-job"])

        # Should still attempt (falls back to default port), not crash
        assert result.exit_code == 1
        assert "Gateway not running" in result.output


class TestIsGatewayRunningHealthEndpoint:
    """Verify _is_gateway_running uses /api/health (always public, no auth required)."""

    def test_probes_health_endpoint(self, tmp_base: Path):
        """Gateway check hits /api/health, not an auth-protected endpoint."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            result = _is_gateway_running(tmp_base)

        assert result is True
        call_args = mock_open.call_args[0]
        assert "/api/health" in call_args[0]


class TestTryApiSendAuth:
    """Verify _try_api_send includes auth headers when api_key is configured."""

    def test_send_includes_auth_header(self, tmp_base: Path):
        """API send includes Bearer token when api_key is set."""
        (tmp_base / "config.yaml").write_text("host: 127.0.0.1\nport: 7890\napi_key: my-secret\n")
        # Create a minimal agent so validation passes
        agent_dir = tmp_base / "agents" / "tars"
        agent_dir.mkdir(parents=True, exist_ok=True)
        (agent_dir / "agent.yaml").write_text("name: tars\nmodel: claude-sonnet-4-6\n")

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"response": "hello"}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            result = _try_api_send(tmp_base, "tars", "hi")

        assert result == "hello"
        req = mock_open.call_args[0][0]
        assert req.get_header("Authorization") == "Bearer my-secret"

    def test_send_no_auth_when_no_key(self, tmp_base: Path):
        """API send omits auth header when no api_key is configured."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"response": "hi"}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            result = _try_api_send(tmp_base, "tars", "hello")

        assert result == "hi"
        req = mock_open.call_args[0][0]
        assert req.get_header("Authorization") is None


class TestCronListEdgeCases:
    """Edge cases for cron list command."""

    def test_cron_list_all_disabled_no_flag(self, tmp_base: Path):
        """All jobs disabled without --all shows 'No jobs found'."""
        jobs_path = tmp_base / "shared" / "cron" / "jobs.json"
        jobs = [
            {
                "id": "disabled-job",
                "agent": "tars",
                "schedule": "0 8 * * *",
                "enabled": False,
                "status": "disabled",
            }
        ]
        jobs_path.write_text(json.dumps(jobs))

        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_base), "cron", "list"])
        assert result.exit_code == 0
        assert "No jobs found" in result.output
        assert "--all" in result.output

    def test_cron_list_with_timestamps(self, tmp_base: Path):
        """Jobs with last_run and next_run timestamps get trimmed."""
        jobs_path = tmp_base / "shared" / "cron" / "jobs.json"
        jobs = [
            {
                "id": "timed-job",
                "agent": "tars",
                "schedule": "0 8 * * *",
                "enabled": True,
                "status": "ok",
                "last_run": "2026-03-16T10:00:00.123456",
                "next_run": "2026-03-17T08:00:00.654321",
            }
        ]
        jobs_path.write_text(json.dumps(jobs))

        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_base), "cron", "list"])
        assert result.exit_code == 0
        assert "timed-job" in result.output
        # Trimmed to seconds (first 19 chars)
        assert "2026-03-16T10:00:00" in result.output
        assert "2026-03-17T08:00:00" in result.output
        # Microseconds should be trimmed
        assert ".123456" not in result.output


class TestDoctorPortEdgeCases:
    """Edge cases for doctor port checking."""

    def test_doctor_port_socket_exception(self, tmp_base: Path, agent_dir: Path):
        """Socket exception during port check shows 'could not check'."""
        runner = CliRunner()
        with patch("socket.socket") as mock_sock:
            mock_sock.return_value.connect_ex.side_effect = OSError("network error")
            mock_sock.return_value.settimeout = MagicMock()
            result = runner.invoke(cli, ["--home", str(tmp_base), "doctor"])

        assert result.exit_code == 0
        assert "could not check" in result.output

    def test_doctor_all_good(self, tmp_base: Path, agent_dir: Path):
        """doctor with healthy setup shows 'all good'."""
        # Create memory DB so that check passes
        from smolclaw.memory import Memory

        db_path = tmp_base / "shared" / "memory.db"
        Memory(db_path, agent="test")

        runner = CliRunner()
        # Patch socket to return "not in use" and mock shutil.which so
        # Claude CLI check passes in CI where it's not installed
        with (
            patch("socket.socket") as mock_sock,
            patch("shutil.which", return_value="/usr/local/bin/claude"),
        ):
            mock_sock.return_value.connect_ex.return_value = 1  # Port not in use
            mock_sock.return_value.settimeout = MagicMock()
            mock_sock.return_value.close = MagicMock()
            result = runner.invoke(cli, ["--home", str(tmp_base), "doctor"])

        assert result.exit_code == 0
        assert "all good" in result.output


class TestStatusSdkExtrasEdgeCases:
    """Edge cases for SDK extras display in status command."""

    def test_status_max_turns_and_output_format(self, tmp_base: Path):
        """status shows max_turns and structured_output when configured."""
        agent = tmp_base / "agents" / "limited"
        for subdir in ["skills", "prompts", "context", "channels", "sessions"]:
            (agent / subdir).mkdir(parents=True)
        (agent / "agent.yaml").write_text(
            "name: limited\nmodel: claude-sonnet-4-6\n"
            "max_turns: 10\n"
            "output_format:\n  type: json_object\n"
        )
        (agent / "soul.md").write_text("Limited agent")

        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_base), "status"])
        assert result.exit_code == 0
        assert "max_turns=10" in result.output
        assert "structured_output" in result.output

    def test_status_mcp_string(self, tmp_base: Path):
        """status shows mcp=<string> when mcp_servers is a string path."""
        agent = tmp_base / "agents" / "mcpbot"
        for subdir in ["skills", "prompts", "context", "channels", "sessions"]:
            (agent / subdir).mkdir(parents=True)
        (agent / "agent.yaml").write_text(
            "name: mcpbot\nmodel: claude-sonnet-4-6\nmcp_servers: /path/to/config.json\n"
        )
        (agent / "soul.md").write_text("MCP agent")

        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_base), "status"])
        assert result.exit_code == 0
        assert "mcp=/path/to/config.json" in result.output


class TestMemoryStatsVec:
    """Tests for memory stats vec_facts/vec_chunks display."""

    def test_memory_stats_with_vec_info(self, tmp_path: Path):
        """When vec_facts is present, stats shows vector counts."""
        base = _setup_agent_with_memory(tmp_path)
        runner = CliRunner()

        # Mock stats() to return vec info
        with patch("smolclaw.memory.Memory.stats") as mock_stats:
            mock_stats.return_value = {
                "facts": 3,
                "total_facts": 3,
                "chunks": 0,
                "total_chunks": 0,
                "vec_enabled": True,
                "vec_facts": 3,
                "vec_chunks": 0,
            }
            result = runner.invoke(cli, ["--home", str(base), "memory", "stats", "tars"])

        assert result.exit_code == 0
        assert "Vec facts:  3" in result.output
        assert "Vec chunks: 0" in result.output


class TestLogsReadError:
    """Tests for logs command error handling."""

    def test_logs_read_oserror(self, tmp_path: Path):
        """OSError reading log file shows error message."""
        log_file = tmp_path / "smolclaw.log"
        log_file.write_text("content", encoding="utf-8")

        runner = CliRunner()
        with patch.object(Path, "read_text", side_effect=OSError("Permission denied")):
            result = runner.invoke(cli, ["--home", str(tmp_path), "logs"])

        assert result.exit_code == 0
        assert "Error reading log file" in result.output


class TestMemorySearchTruncation:
    """Tests for memory search result content truncation."""

    def test_search_long_content_truncated(self, tmp_path: Path):
        """Search results with content > 60 chars get truncated."""
        base = _setup_agent_with_memory(tmp_path)

        # Add a fact with very long content containing a searchable word
        from smolclaw.memory import Memory

        db_path = base / "shared" / "memory.db"
        mem = Memory(db_path, agent="tars")
        long_text = "searchterm " + "padding " * 20
        mem.add_fact(long_text, category="test")

        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(base), "memory", "search", "tars", "searchterm"])
        assert result.exit_code == 0
        assert "..." in result.output


# ---------------------------------------------------------------------------
# Export / Import
# ---------------------------------------------------------------------------


class TestExport:
    """Tests for the export command."""

    def _create_agent(self, base: Path, name: str = "tars") -> Path:
        """Create a minimal agent for export testing."""
        agent_dir = base / "agents" / name
        agent_dir.mkdir(parents=True, exist_ok=True)
        (agent_dir / "agent.yaml").write_text(f"name: {name}\nmodel: claude-sonnet-4-6\n")
        (agent_dir / "soul.md").write_text(f"# {name}\nTest soul.\n")
        (agent_dir / "agents.md").write_text(f"# {name} rules\n")
        # Create subdirectories
        (agent_dir / "skills" / "mskill").mkdir(parents=True, exist_ok=True)
        (agent_dir / "skills" / "mskill" / "SKILL.md").write_text("---\nname: mskill\n---\n")
        (agent_dir / "prompts").mkdir(exist_ok=True)
        (agent_dir / "prompts" / "test.md").write_text("Test prompt\n")
        (agent_dir / "context").mkdir(exist_ok=True)
        (agent_dir / "context" / "COMPANY.md").write_text("# Company\n")
        (agent_dir / "channels").mkdir(exist_ok=True)
        (agent_dir / "channels" / "telegram.env").write_text("TOKEN=secret123\n")
        (agent_dir / "sessions").mkdir(exist_ok=True)
        (agent_dir / "sessions" / "cli.json").write_text('{"session_id": "abc"}\n')
        return agent_dir

    def test_export_basic(self, tmp_base: Path, tmp_path: Path):
        """Export creates a .tar.gz with agent files."""
        import tarfile

        self._create_agent(tmp_base)
        out = tmp_path / "tars.tar.gz"

        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_base), "export", "tars", "-o", str(out)])

        assert result.exit_code == 0
        assert out.exists()
        assert "Exported agent 'tars'" in result.output

        # Verify contents
        with tarfile.open(str(out), "r:gz") as tar:
            names = tar.getnames()
            assert "tars/agent.yaml" in names
            assert "tars/soul.md" in names
            assert "tars/skills/mskill/SKILL.md" in names
            assert "tars/prompts/test.md" in names
            assert "tars/context/COMPANY.md" in names

    def test_export_excludes_sessions(self, tmp_base: Path, tmp_path: Path):
        """Sessions directory is excluded from export."""
        import tarfile

        self._create_agent(tmp_base)
        out = tmp_path / "tars.tar.gz"

        runner = CliRunner()
        runner.invoke(cli, ["--home", str(tmp_base), "export", "tars", "-o", str(out)])

        with tarfile.open(str(out), "r:gz") as tar:
            names = tar.getnames()
            assert not any("sessions" in n for n in names)

    def test_export_excludes_env_by_default(self, tmp_base: Path, tmp_path: Path):
        """Env files (secrets) are excluded by default."""
        import tarfile

        self._create_agent(tmp_base)
        out = tmp_path / "tars.tar.gz"

        runner = CliRunner()
        runner.invoke(cli, ["--home", str(tmp_base), "export", "tars", "-o", str(out)])

        with tarfile.open(str(out), "r:gz") as tar:
            names = tar.getnames()
            assert not any(".env" in n for n in names)

    def test_export_includes_env_with_flag(self, tmp_base: Path, tmp_path: Path):
        """--include-env flag includes .env files."""
        import tarfile

        self._create_agent(tmp_base)
        out = tmp_path / "tars.tar.gz"

        runner = CliRunner()
        runner.invoke(
            cli, ["--home", str(tmp_base), "export", "tars", "--include-env", "-o", str(out)]
        )

        with tarfile.open(str(out), "r:gz") as tar:
            names = tar.getnames()
            assert any(".env" in n for n in names)

    def test_export_nonexistent_agent(self, tmp_base: Path):
        """Export of missing agent shows error."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_base), "export", "ghost"])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_export_default_output_name(self, tmp_base: Path):
        """Default output is <name>.tar.gz in cwd."""
        self._create_agent(tmp_base)

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["--home", str(tmp_base), "export", "tars"])
            assert result.exit_code == 0
            assert Path("tars.tar.gz").exists()

    def test_export_resolves_symlinks(self, tmp_base: Path, tmp_path: Path):
        """Symlinked skills are resolved (actual files included)."""
        import tarfile

        self._create_agent(tmp_base)

        # Create a shared skill and symlink it
        shared_skill = tmp_base / "shared" / "skills" / "remote-skill"
        shared_skill.mkdir(parents=True, exist_ok=True)
        (shared_skill / "SKILL.md").write_text("---\nname: remote-skill\n---\nRemote!\n")

        agent_skill = tmp_base / "agents" / "tars" / "skills" / "remote-skill"
        agent_skill.symlink_to(shared_skill)

        out = tmp_path / "tars.tar.gz"
        runner = CliRunner()
        runner.invoke(cli, ["--home", str(tmp_base), "export", "tars", "-o", str(out)])

        with tarfile.open(str(out), "r:gz") as tar:
            names = tar.getnames()
            assert "tars/skills/remote-skill/SKILL.md" in names
            # Read the actual content (should be resolved, not a broken link)
            member = tar.getmember("tars/skills/remote-skill/SKILL.md")
            content = tar.extractfile(member).read().decode()
            assert "Remote!" in content


class TestImport:
    """Tests for the import command."""

    def _make_archive(self, tmp_path: Path, name: str = "tars") -> Path:
        """Create a test .tar.gz archive for import testing."""
        import tarfile

        archive = tmp_path / f"{name}.tar.gz"
        with tarfile.open(str(archive), "w:gz") as tar:
            # agent.yaml
            content = f"name: {name}\nmodel: claude-sonnet-4-6\n".encode()
            info = tarfile.TarInfo(name=f"{name}/agent.yaml")
            info.size = len(content)
            tar.addfile(info, fileobj=__import__("io").BytesIO(content))

            # soul.md
            soul = f"# {name}\nImported agent.\n".encode()
            info = tarfile.TarInfo(name=f"{name}/soul.md")
            info.size = len(soul)
            tar.addfile(info, fileobj=__import__("io").BytesIO(soul))

            # skills/mskill/SKILL.md
            skill = b"---\nname: mskill\n---\nA skill.\n"
            info = tarfile.TarInfo(name=f"{name}/skills/mskill/SKILL.md")
            info.size = len(skill)
            tar.addfile(info, fileobj=__import__("io").BytesIO(skill))

        return archive

    def test_import_basic(self, tmp_base: Path, tmp_path: Path):
        """Import creates agent directory from archive."""
        archive = self._make_archive(tmp_path, "tars")

        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_base), "import", str(archive)])

        assert result.exit_code == 0
        assert "Imported agent 'tars'" in result.output

        agent_dir = tmp_base / "agents" / "tars"
        assert (agent_dir / "agent.yaml").exists()
        assert (agent_dir / "soul.md").exists()
        assert (agent_dir / "skills" / "mskill" / "SKILL.md").exists()

    def test_import_with_rename(self, tmp_base: Path, tmp_path: Path):
        """Import with --rename creates agent under new name."""
        archive = self._make_archive(tmp_path, "tars")

        runner = CliRunner()
        result = runner.invoke(
            cli, ["--home", str(tmp_base), "import", str(archive), "--rename", "jarvis"]
        )

        assert result.exit_code == 0
        assert "Imported agent 'jarvis'" in result.output

        agent_dir = tmp_base / "agents" / "jarvis"
        assert (agent_dir / "agent.yaml").exists()
        # Verify name was updated in agent.yaml
        content = (agent_dir / "agent.yaml").read_text()
        assert "name: jarvis" in content

    def test_import_existing_agent_without_force(self, tmp_base: Path, tmp_path: Path):
        """Import refuses to overwrite existing agent without --force."""
        archive = self._make_archive(tmp_path, "tars")

        # Create existing agent
        agent_dir = tmp_base / "agents" / "tars"
        agent_dir.mkdir(parents=True, exist_ok=True)
        (agent_dir / "agent.yaml").write_text("name: tars\n")

        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_base), "import", str(archive)])
        assert result.exit_code == 1
        assert "already exists" in result.output

    def test_import_existing_with_force(self, tmp_base: Path, tmp_path: Path):
        """Import with --force overwrites existing agent."""
        archive = self._make_archive(tmp_path, "tars")

        # Create existing agent
        agent_dir = tmp_base / "agents" / "tars"
        agent_dir.mkdir(parents=True, exist_ok=True)
        (agent_dir / "agent.yaml").write_text("name: tars\n")

        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_base), "import", str(archive), "--force"])
        assert result.exit_code == 0
        assert "Imported agent 'tars'" in result.output

    def test_import_missing_archive(self, tmp_base: Path):
        """Import with nonexistent file shows error."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--home", str(tmp_base), "import", "/tmp/nonexistent.tar.gz"])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_roundtrip_export_import(self, tmp_base: Path, tmp_path: Path):
        """Export then import produces identical agent."""
        # Create agent
        agent_dir = tmp_base / "agents" / "tars"
        agent_dir.mkdir(parents=True, exist_ok=True)
        (agent_dir / "agent.yaml").write_text("name: tars\nmodel: claude-opus-4-6\n")
        (agent_dir / "soul.md").write_text("# TARS\nHumor: 60%\n")
        (agent_dir / "prompts").mkdir(exist_ok=True)
        (agent_dir / "prompts" / "brief.md").write_text("Morning briefing.\n")

        archive = tmp_path / "tars.tar.gz"
        runner = CliRunner()

        # Export
        result = runner.invoke(cli, ["--home", str(tmp_base), "export", "tars", "-o", str(archive)])
        assert result.exit_code == 0

        # Remove original
        import shutil as _shutil

        _shutil.rmtree(agent_dir)
        assert not agent_dir.exists()

        # Import
        result = runner.invoke(cli, ["--home", str(tmp_base), "import", str(archive)])
        assert result.exit_code == 0

        # Verify roundtrip
        assert (agent_dir / "agent.yaml").read_text() == "name: tars\nmodel: claude-opus-4-6\n"
        assert (agent_dir / "soul.md").read_text() == "# TARS\nHumor: 60%\n"
        assert (agent_dir / "prompts" / "brief.md").read_text() == "Morning briefing.\n"
