"""Tests for smolclaw.__main__ module."""

from __future__ import annotations

from unittest.mock import patch


class TestMain:
    def test_main_invokes_cli(self):
        """python -m smolclaw should call cli.main()."""
        with patch("smolclaw.cli.main") as mock_main:
            # runpy.run_module simulates `python -m smolclaw`
            import runpy

            runpy.run_module("smolclaw", run_name="__main__", alter_sys=False)
            mock_main.assert_called_once()
