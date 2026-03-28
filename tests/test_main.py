"""Tests for smolclaw.__main__ module and package-level exports."""

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


class TestPackageExports:
    """Verify all public types are importable from the top-level package."""

    def test_channel_config_exported(self):
        """ChannelConfig should be importable from smolclaw (needed by custom channel authors)."""
        from smolclaw import ChannelConfig

        cfg = ChannelConfig(token_env="TEST_TOKEN")
        assert cfg.token_env == "TEST_TOKEN"

    def test_all_public_types_importable(self):
        """All types listed in __all__ should actually be importable."""
        import smolclaw

        for name in smolclaw.__all__:
            assert hasattr(smolclaw, name), f"{name} listed in __all__ but not importable"
