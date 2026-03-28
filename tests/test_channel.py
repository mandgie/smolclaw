"""Tests for channel helper functions, TelegramChannel, and WebhookChannel adapters."""

from __future__ import annotations

import asyncio
import contextlib
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from smolclaw.channel import (
    CHANNEL_TYPES,
    MAX_DISCORD_LENGTH,
    Channel,
    DiscordChannel,
    TelegramChannel,
    WebhookChannel,
    _custom_channels,
    _discover_entrypoint_channels,
    _hard_split,
    create_channel,
    list_channel_types,
    md_to_telegram_html,
    register_channel,
    split_message,
)
from smolclaw.config import ChannelConfig
from smolclaw.router import Router

# --- md_to_telegram_html ---


class TestMdToTelegramHtml:
    def test_bold(self):
        assert "<b>bold</b>" in md_to_telegram_html("**bold**")

    def test_bold_underscore(self):
        assert "<b>bold</b>" in md_to_telegram_html("__bold__")

    def test_italic(self):
        assert "<i>italic</i>" in md_to_telegram_html("*italic*")

    def test_italic_underscore(self):
        assert "<i>italic</i>" in md_to_telegram_html("_italic_")

    def test_strikethrough(self):
        assert "<s>strike</s>" in md_to_telegram_html("~~strike~~")

    def test_inline_code(self):
        result = md_to_telegram_html("Use `foo()` here")
        assert "<code>foo()</code>" in result

    def test_code_block(self):
        result = md_to_telegram_html("```python\nprint('hi')\n```")
        assert "<pre>" in result
        assert "print(" in result

    def test_code_block_no_language(self):
        result = md_to_telegram_html("```\nsome code\n```")
        assert "<pre>" in result
        assert "some code" in result

    def test_heading_becomes_bold(self):
        result = md_to_telegram_html("## My Heading")
        assert "<b>My Heading</b>" in result

    def test_h1_heading(self):
        result = md_to_telegram_html("# Title")
        assert "<b>Title</b>" in result

    def test_link(self):
        result = md_to_telegram_html("[click](https://example.com)")
        assert '<a href="https://example.com">click</a>' in result

    def test_html_escape(self):
        result = md_to_telegram_html("1 < 2 & 3 > 0")
        assert "&lt;" in result
        assert "&amp;" in result
        assert "&gt;" in result

    def test_code_not_escaped(self):
        result = md_to_telegram_html("`a < b`")
        assert "<code>a &lt; b</code>" in result

    def test_code_block_html_escaped(self):
        result = md_to_telegram_html("```\n<script>alert('xss')</script>\n```")
        assert "&lt;script&gt;" in result

    def test_mixed_formatting(self):
        result = md_to_telegram_html("**bold** and *italic* and `code`")
        assert "<b>bold</b>" in result
        assert "<i>italic</i>" in result
        assert "<code>code</code>" in result

    def test_plain_text_unchanged(self):
        result = md_to_telegram_html("Hello world")
        assert result == "Hello world"

    def test_multiple_code_blocks_preserved(self):
        text = "```\nfirst\n```\n\ntext\n\n```\nsecond\n```"
        result = md_to_telegram_html(text)
        assert "first" in result
        assert "second" in result
        assert result.count("<pre>") == 2

    def test_multiple_inline_codes(self):
        result = md_to_telegram_html("`a` and `b` and `c`")
        assert result.count("<code>") == 3


# --- split_message ---


class TestSplitMessage:
    def test_short_message_no_split(self):
        assert split_message("Hello") == ["Hello"]

    def test_long_message_splits_at_paragraphs(self):
        text = ("A" * 100 + "\n\n") * 50
        chunks = split_message(text, max_len=500)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= 500

    def test_single_long_paragraph_splits_at_lines(self):
        text = "\n".join(["Line " + str(i) for i in range(200)])
        chunks = split_message(text, max_len=200)
        assert len(chunks) > 1

    def test_empty_returns_original(self):
        assert split_message("") == [""]

    def test_exactly_at_limit(self):
        text = "A" * 4000
        assert split_message(text, max_len=4000) == [text]

    def test_one_over_limit(self):
        text = "A" * 4001
        chunks = split_message(text, max_len=4000)
        assert len(chunks) >= 1

    def test_preserves_all_content(self):
        paragraphs = [f"Paragraph {i}" for i in range(20)]
        text = "\n\n".join(paragraphs)
        chunks = split_message(text, max_len=100)
        rejoined = " ".join(chunks)
        for p in paragraphs:
            assert p in rejoined

    def test_single_huge_line_fallback(self):
        """A single line longer than max_len should produce at least one chunk."""
        text = "X" * 500
        chunks = split_message(text, max_len=100)
        assert len(chunks) >= 1

    def test_single_huge_line_respects_max_len(self):
        """Every chunk must be within max_len, even for a single unbroken line."""
        text = "X" * 500
        chunks = split_message(text, max_len=100)
        assert len(chunks) == 5
        for chunk in chunks:
            assert len(chunk) <= 100

    def test_huge_line_with_spaces_splits_at_words(self):
        """Long lines with spaces should split at word boundaries."""
        words = ["word"] * 100  # 100 words, ~500 chars with spaces
        text = " ".join(words)
        chunks = split_message(text, max_len=100)
        for chunk in chunks:
            assert len(chunk) <= 100
        # All content should be preserved
        rejoined = " ".join(chunks)
        assert rejoined.replace("  ", " ").count("word") == 100

    def test_huge_line_inside_paragraph(self):
        """A paragraph with one normal line and one oversized line."""
        text = "Short line\n" + "X" * 300
        chunks = split_message(text, max_len=100)
        for chunk in chunks:
            assert len(chunk) <= 100
        rejoined = " ".join(chunks)
        assert "Short line" in rejoined

    def test_mixed_paragraphs_and_huge_line(self):
        """Mix of normal paragraphs and one containing an oversized line."""
        text = "Normal para 1\n\n" + "Y" * 250 + "\n\nNormal para 2"
        chunks = split_message(text, max_len=100)
        for chunk in chunks:
            assert len(chunk) <= 100
        rejoined = " ".join(chunks)
        assert "Normal para 1" in rejoined
        assert "Normal para 2" in rejoined

    def test_one_over_limit_respects_max_len(self):
        """Regression: text just over limit must still be split properly."""
        text = "A" * 4001
        chunks = split_message(text, max_len=4000)
        assert len(chunks) == 2
        for chunk in chunks:
            assert len(chunk) <= 4000


# --- _hard_split ---


class TestHardSplit:
    def test_short_text_no_split(self):
        assert _hard_split("Hello", 100) == ["Hello"]

    def test_splits_at_character_boundary(self):
        text = "X" * 250
        pieces = _hard_split(text, 100)
        assert len(pieces) == 3
        for piece in pieces:
            assert len(piece) <= 100

    def test_prefers_space_boundary(self):
        text = "aaaa bbbb cccc dddd eeee ffff"  # 29 chars
        pieces = _hard_split(text, 20)
        for piece in pieces:
            assert len(piece) <= 20
        # Content preserved
        assert " ".join(pieces) == text

    def test_no_space_hard_cuts(self):
        text = "A" * 50
        pieces = _hard_split(text, 20)
        assert all(len(p) <= 20 for p in pieces)
        assert "".join(pieces) == text

    def test_empty_string(self):
        assert _hard_split("", 100) == []

    def test_exact_length(self):
        text = "A" * 100
        assert _hard_split(text, 100) == [text]


# --- TelegramChannel ---


def _make_channel(
    token: str = "test-token",
    authorized_users: list[int | str] | None = None,
) -> TelegramChannel:
    config = ChannelConfig(
        token_env="TEST_BOT_TOKEN",
        authorized_users=authorized_users or [],
    )
    router = Router()
    with patch.dict("os.environ", {"TEST_BOT_TOKEN": token}):
        channel = TelegramChannel("testagent", config, router)
    return channel


class TestTelegramChannelInit:
    def test_basic_init(self):
        ch = _make_channel()
        assert ch.agent_name == "testagent"
        assert ch.channel_type == "telegram"
        assert ch._token == "test-token"
        assert ch._app is None

    def test_authorized_users(self):
        ch = _make_channel(authorized_users=[111, 222])
        assert ch._authorized == {111, 222}

    def test_no_authorized_users(self):
        ch = _make_channel(authorized_users=[])
        assert ch._authorized == set()

    def test_missing_token_env(self):
        config = ChannelConfig(token_env="NONEXISTENT_TOKEN", authorized_users=[])
        router = Router()
        ch = TelegramChannel("testagent", config, router)
        assert ch._token == ""


class TestTelegramChannelAuth:
    def test_authorized_when_no_whitelist(self):
        ch = _make_channel(authorized_users=[])
        assert ch._is_authorized(12345) is True

    def test_authorized_user_in_whitelist(self):
        ch = _make_channel(authorized_users=[111, 222])
        assert ch._is_authorized(111) is True
        assert ch._is_authorized(222) is True

    def test_unauthorized_user(self):
        ch = _make_channel(authorized_users=[111])
        assert ch._is_authorized(999) is False


def _build_telegram_mocks():
    """Create a complete set of mocked telegram objects for start() testing."""
    mock_updater = MagicMock()
    mock_updater.start_polling = AsyncMock()
    mock_updater.stop = AsyncMock()

    mock_app = MagicMock()
    mock_app.initialize = AsyncMock()
    mock_app.start = AsyncMock()
    mock_app.stop = AsyncMock()
    mock_app.shutdown = AsyncMock()
    mock_app.updater = mock_updater
    mock_app.add_handler = MagicMock()

    mock_builder = MagicMock()
    mock_builder.token.return_value = mock_builder
    mock_builder.get_updates_read_timeout.return_value = mock_builder
    mock_builder.get_updates_connect_timeout.return_value = mock_builder
    mock_builder.get_updates_pool_timeout.return_value = mock_builder
    mock_builder.build.return_value = mock_app

    mock_application_cls = MagicMock()
    mock_application_cls.builder.return_value = mock_builder

    mock_parse_mode = MagicMock()
    mock_parse_mode.HTML = "HTML"
    mock_chat_action = MagicMock()

    # Build the sys.modules dict for patching
    telegram_mod = MagicMock()
    telegram_mod.Update = MagicMock()
    telegram_mod.constants.ChatAction = mock_chat_action
    telegram_mod.constants.ParseMode = mock_parse_mode

    telegram_constants = MagicMock()
    telegram_constants.ChatAction = mock_chat_action
    telegram_constants.ParseMode = mock_parse_mode

    telegram_ext = MagicMock()
    telegram_ext.Application = mock_application_cls
    telegram_ext.CommandHandler = MagicMock()
    telegram_ext.MessageHandler = MagicMock()
    telegram_ext.ContextTypes = MagicMock()
    telegram_ext.filters = MagicMock()

    modules = {
        "telegram": telegram_mod,
        "telegram.constants": telegram_constants,
        "telegram.ext": telegram_ext,
    }
    return modules, mock_app, mock_updater


class TestTelegramChannelStart:
    @pytest.mark.asyncio
    async def test_start_no_token_returns_early(self):
        """start() should log error and return if no token."""
        ch = _make_channel(token="")
        ch._token = ""
        await ch.start()
        assert ch._app is None

    @pytest.mark.asyncio
    async def test_start_builds_and_starts_app(self):
        """start() should build and start a Telegram Application."""
        ch = _make_channel()
        modules, mock_app, mock_updater = _build_telegram_mocks()

        with patch.dict("sys.modules", modules):
            await ch.start()

        assert ch._app is mock_app
        mock_app.initialize.assert_awaited_once()
        mock_app.start.assert_awaited_once()
        mock_updater.start_polling.assert_awaited_once()
        call_kwargs = mock_updater.start_polling.call_args[1]
        assert call_kwargs["drop_pending_updates"] is True
        assert callable(call_kwargs["error_callback"])
        assert mock_app.add_handler.call_count == 3  # /start, /new, message
        mock_app.add_error_handler.assert_called_once()
        # Cleanup watchdog
        if ch._watchdog_task:
            ch._watchdog_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await ch._watchdog_task


async def _start_channel_and_get_handlers(
    authorized_users: list[int] | None = None,
) -> tuple[TelegramChannel, dict]:
    """Start a channel with mocked telegram and capture registered handlers."""
    ch = _make_channel(authorized_users=authorized_users)
    modules, _mock_app, _ = _build_telegram_mocks()

    # Track CommandHandler and MessageHandler calls
    captured = {"command": {}, "message": None}

    def track_cmd(cmd_name, func, *args, **kwargs):
        captured["command"][cmd_name] = func
        return MagicMock()

    def track_msg(filter_, func, *args, **kwargs):
        captured["message"] = func
        return MagicMock()

    modules["telegram.ext"].CommandHandler = track_cmd
    modules["telegram.ext"].MessageHandler = track_msg

    with patch.dict("sys.modules", modules):
        await ch.start()

    # Cleanup watchdog spawned by start()
    if ch._watchdog_task:
        ch._watchdog_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await ch._watchdog_task

    return ch, captured


def _make_mock_update(
    text: str = "Hello",
    user_id: int = 111,
    chat_id: int = 999,
) -> MagicMock:
    """Create a mock Telegram Update object."""
    update = MagicMock()
    update.message.text = text
    update.message.chat_id = chat_id
    update.message.reply_text = AsyncMock()
    update.message.chat.send_action = AsyncMock()
    update.effective_user.id = user_id
    return update


class TestTelegramHandlers:
    @pytest.mark.asyncio
    async def test_cmd_start_authorized(self):
        _ch, handlers = await _start_channel_and_get_handlers()
        update = _make_mock_update(user_id=111)
        context = MagicMock()

        await handlers["command"]["start"](update, context)

        update.message.reply_text.assert_awaited_once()
        msg = update.message.reply_text.call_args[0][0]
        assert "testagent" in msg
        assert "online" in msg

    @pytest.mark.asyncio
    async def test_cmd_start_unauthorized(self):
        _ch, handlers = await _start_channel_and_get_handlers(authorized_users=[111])
        update = _make_mock_update(user_id=999)
        context = MagicMock()

        await handlers["command"]["start"](update, context)

        msg = update.message.reply_text.call_args[0][0]
        assert "Unauthorized" in msg

    @pytest.mark.asyncio
    async def test_cmd_new_resets_session(self):
        ch, handlers = await _start_channel_and_get_handlers()
        mock_agent = MagicMock()
        mock_agent.new_session = AsyncMock()
        ch.router._agents["testagent"] = mock_agent

        update = _make_mock_update(user_id=111)
        context = MagicMock()

        await handlers["command"]["new"](update, context)

        mock_agent.new_session.assert_awaited_once()
        msg = update.message.reply_text.call_args[0][0]
        assert "Session cleared" in msg

    @pytest.mark.asyncio
    async def test_cmd_new_unauthorized_ignored(self):
        _ch, handlers = await _start_channel_and_get_handlers(authorized_users=[111])
        update = _make_mock_update(user_id=999)
        context = MagicMock()

        await handlers["command"]["new"](update, context)
        update.message.reply_text.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_handle_message_routes_and_responds(self):
        from smolclaw.router import OutboundMessage

        ch, handlers = await _start_channel_and_get_handlers()
        update = _make_mock_update(text="Hi there", user_id=111)
        context = MagicMock()

        # Mock the router.route to return an outbound message
        ch.router.route = AsyncMock(
            return_value=OutboundMessage(agent="testagent", text="Hello back!", source="telegram")
        )

        await handlers["message"](update, context)

        ch.router.route.assert_awaited_once()
        routed_msg = ch.router.route.call_args[0][0]
        assert routed_msg.text == "Hi there"
        assert routed_msg.agent == "testagent"
        assert routed_msg.source == "telegram"
        # Response sent back
        update.message.reply_text.assert_awaited()

    @pytest.mark.asyncio
    async def test_handle_message_unauthorized_ignored(self):
        _ch, handlers = await _start_channel_and_get_handlers(authorized_users=[111])
        update = _make_mock_update(text="Hi", user_id=999)
        context = MagicMock()

        await handlers["message"](update, context)
        update.message.reply_text.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_handle_message_no_text_ignored(self):
        _ch, handlers = await _start_channel_and_get_handlers()
        update = MagicMock()
        update.message = None
        context = MagicMock()

        await handlers["message"](update, context)
        # Should return early without error

    @pytest.mark.asyncio
    async def test_handle_message_empty_text_ignored(self):
        ch, handlers = await _start_channel_and_get_handlers()
        update = _make_mock_update()
        update.message.text = None
        context = MagicMock()

        await handlers["message"](update, context)
        # Router should not be called
        assert not hasattr(ch.router, "route") or not isinstance(ch.router.route, AsyncMock)

    @pytest.mark.asyncio
    async def test_handle_message_timeout(self):
        ch, handlers = await _start_channel_and_get_handlers()
        update = _make_mock_update(text="Hi", user_id=111)
        context = MagicMock()

        ch.router.route = AsyncMock(side_effect=asyncio.TimeoutError)

        await handlers["message"](update, context)

        msg = update.message.reply_text.call_args[0][0]
        assert "timed out" in msg.lower()

    @pytest.mark.asyncio
    async def test_handle_message_error(self):
        ch, handlers = await _start_channel_and_get_handlers()
        update = _make_mock_update(text="Hi", user_id=111)
        context = MagicMock()

        ch.router.route = AsyncMock(side_effect=RuntimeError("agent crashed"))

        await handlers["message"](update, context)

        msg = update.message.reply_text.call_args[0][0]
        assert "Error" in msg

    @pytest.mark.asyncio
    async def test_handle_message_html_fallback(self):
        """If HTML response fails to send, falls back to plain text."""
        from smolclaw.router import OutboundMessage

        ch, handlers = await _start_channel_and_get_handlers()
        update = _make_mock_update(text="Hi", user_id=111)
        # First reply (HTML) fails, second (plain) succeeds
        update.message.reply_text = AsyncMock(side_effect=[Exception("parse error"), None])
        context = MagicMock()

        ch.router.route = AsyncMock(
            return_value=OutboundMessage(agent="testagent", text="Response", source="telegram")
        )

        await handlers["message"](update, context)

        assert update.message.reply_text.await_count == 2


class TestTelegramChannelStop:
    @pytest.mark.asyncio
    async def test_stop_with_no_app(self):
        """stop() should be a no-op if app was never started."""
        ch = _make_channel()
        await ch.stop()  # Should not raise
        assert ch._app is None

    @pytest.mark.asyncio
    async def test_stop_with_running_app(self):
        ch = _make_channel()
        mock_updater = MagicMock()
        mock_updater.stop = AsyncMock()
        mock_app = MagicMock()
        mock_app.updater = mock_updater
        mock_app.stop = AsyncMock()
        mock_app.shutdown = AsyncMock()
        ch._app = mock_app

        await ch.stop()

        mock_updater.stop.assert_awaited_once()
        mock_app.stop.assert_awaited_once()
        mock_app.shutdown.assert_awaited_once()
        assert ch._app is None


class TestTelegramPollingWatchdog:
    @pytest.mark.asyncio
    async def test_watchdog_restarts_dead_polling(self):
        """Watchdog should restart polling when updater.running is False."""
        ch = _make_channel()
        mock_updater = MagicMock()
        mock_updater.running = False
        mock_updater.start_polling = AsyncMock()
        mock_app = MagicMock()
        mock_app.updater = mock_updater
        ch._app = mock_app

        # Run watchdog for one iteration by patching the sleep interval
        with patch("smolclaw.channel.POLLING_WATCHDOG_INTERVAL", 0):
            task = asyncio.create_task(ch._polling_watchdog())
            await asyncio.sleep(0.05)
            # After restart, set running=True to prevent further restarts
            mock_updater.running = True
            await asyncio.sleep(0.05)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        mock_updater.start_polling.assert_awaited()
        assert mock_updater.start_polling.call_args[1]["drop_pending_updates"] is True

    @pytest.mark.asyncio
    async def test_watchdog_noop_when_polling_healthy(self):
        """Watchdog should not restart polling when updater.running is True."""
        ch = _make_channel()
        mock_updater = MagicMock()
        mock_updater.running = True
        mock_updater.start_polling = AsyncMock()
        mock_app = MagicMock()
        mock_app.updater = mock_updater
        ch._app = mock_app

        with patch("smolclaw.channel.POLLING_WATCHDOG_INTERVAL", 0):
            task = asyncio.create_task(ch._polling_watchdog())
            await asyncio.sleep(0.05)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        mock_updater.start_polling.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_watchdog_gives_up_after_max_failures(self):
        """Watchdog should stop after POLLING_WATCHDOG_MAX_FAILURES consecutive failures."""
        ch = _make_channel()
        mock_updater = MagicMock()
        mock_updater.running = False
        mock_updater.start_polling = AsyncMock(side_effect=RuntimeError("connection failed"))
        mock_app = MagicMock()
        mock_app.updater = mock_updater
        ch._app = mock_app

        with (
            patch("smolclaw.channel.POLLING_WATCHDOG_INTERVAL", 0),
            patch("smolclaw.channel.POLLING_WATCHDOG_MAX_FAILURES", 2),
        ):
            task = asyncio.create_task(ch._polling_watchdog())
            # Let it hit max failures and exit naturally
            await asyncio.sleep(0.1)
            assert task.done()

        assert mock_updater.start_polling.await_count >= 2

    @pytest.mark.asyncio
    async def test_stop_cancels_watchdog(self):
        """stop() should cancel the watchdog task."""
        ch = _make_channel()
        mock_updater = MagicMock()
        mock_updater.running = True
        mock_updater.stop = AsyncMock()
        mock_app = MagicMock()
        mock_app.updater = mock_updater
        mock_app.stop = AsyncMock()
        mock_app.shutdown = AsyncMock()
        ch._app = mock_app

        # Create a real watchdog task
        with patch("smolclaw.channel.POLLING_WATCHDOG_INTERVAL", 60):
            ch._watchdog_task = asyncio.create_task(ch._polling_watchdog())
            await asyncio.sleep(0.01)
            await ch.stop()

        assert ch._watchdog_task is None
        assert ch._app is None


class TestTelegramChannelSend:
    @pytest.mark.asyncio
    async def test_send_no_app(self):
        """send() should return early if no app."""
        ch = _make_channel()
        await ch.send("123", "Hello")  # No-op, should not raise

    @pytest.mark.asyncio
    async def test_send_success_html(self):
        ch = _make_channel()
        mock_bot = AsyncMock()
        mock_app = MagicMock()
        mock_app.bot = mock_bot
        ch._app = mock_app

        await ch.send("12345", "Hello **world**")

        mock_bot.send_message.assert_awaited_once()
        call_kwargs = mock_bot.send_message.call_args[1]
        assert call_kwargs["chat_id"] == 12345
        assert call_kwargs["parse_mode"] == "HTML"
        assert "<b>world</b>" in call_kwargs["text"]

    @pytest.mark.asyncio
    async def test_send_html_fallback_to_plain(self):
        """If HTML send fails, should retry with plain text."""
        ch = _make_channel()
        mock_bot = AsyncMock()
        # First call (HTML) fails, second call (plain) succeeds
        mock_bot.send_message.side_effect = [Exception("parse error"), None]
        mock_app = MagicMock()
        mock_app.bot = mock_bot
        ch._app = mock_app

        await ch.send("12345", "Hello")

        assert mock_bot.send_message.await_count == 2
        # Second call should not have parse_mode
        second_call = mock_bot.send_message.call_args_list[1]
        assert "parse_mode" not in second_call[1]

    @pytest.mark.asyncio
    async def test_send_both_fail_logs_error(self):
        """If both HTML and plain send fail, should log error."""
        ch = _make_channel()
        mock_bot = AsyncMock()
        mock_bot.send_message.side_effect = Exception("network error")
        mock_app = MagicMock()
        mock_app.bot = mock_bot
        ch._app = mock_app

        # Should not raise
        await ch.send("12345", "Hello")
        assert mock_bot.send_message.await_count == 2

    @pytest.mark.asyncio
    async def test_send_splits_long_message(self):
        ch = _make_channel()
        mock_bot = AsyncMock()
        mock_app = MagicMock()
        mock_app.bot = mock_bot
        ch._app = mock_app

        # Create a message that will be split (>4000 chars)
        long_text = ("A" * 200 + "\n\n") * 30  # ~6000+ chars with paragraphs
        await ch.send("123", long_text)

        assert mock_bot.send_message.await_count >= 2


# --- Channel Factory ---


class TestCreateChannel:
    def test_create_telegram(self):
        config = ChannelConfig(token_env="TEST_TOKEN", authorized_users=[])
        router = Router()
        ch = create_channel("telegram", "myagent", config, router)
        assert isinstance(ch, TelegramChannel)
        assert ch.agent_name == "myagent"

    def test_unknown_type_raises(self):
        config = ChannelConfig(token_env="TEST_TOKEN", authorized_users=[])
        router = Router()
        with pytest.raises(ValueError, match="Unknown channel type"):
            create_channel("nonexistent_platform", "myagent", config, router)

    def test_channel_types_registry(self):
        assert "telegram" in CHANNEL_TYPES
        assert CHANNEL_TYPES["telegram"] is TelegramChannel


class TestChannelRepr:
    def test_telegram_channel_repr(self):
        ch = _make_channel()
        r = repr(ch)
        assert "TelegramChannel" in r
        assert "testagent" in r


# --- Webhook Channel ---


def _make_webhook_channel(
    url: str = "https://hooks.example.com/test",
    headers: dict | None = None,
) -> WebhookChannel:
    config = ChannelConfig(url=url, headers=headers or {})
    router = Router()
    return WebhookChannel("testagent", config, router)


class TestWebhookChannelInit:
    def test_defaults(self):
        ch = _make_webhook_channel()
        assert ch.channel_type == "webhook"
        assert ch.agent_name == "testagent"
        assert ch._url == "https://hooks.example.com/test"
        assert ch._headers["Content-Type"] == "application/json"

    def test_custom_headers(self):
        ch = _make_webhook_channel(headers={"X-Custom": "value"})
        assert ch._headers["X-Custom"] == "value"
        assert ch._headers["Content-Type"] == "application/json"

    def test_repr(self):
        ch = _make_webhook_channel()
        r = repr(ch)
        assert "WebhookChannel" in r
        assert "testagent" in r


class TestWebhookChannelStart:
    @pytest.mark.asyncio
    async def test_start_with_url(self):
        """start() logs ready when URL is configured."""
        ch = _make_webhook_channel()
        await ch.start()  # Should not raise

    @pytest.mark.asyncio
    async def test_start_without_url(self):
        """start() logs error when no URL is configured."""
        ch = _make_webhook_channel(url="")
        await ch.start()  # Should not raise, just logs error


class TestWebhookChannelStop:
    @pytest.mark.asyncio
    async def test_stop_is_noop(self):
        """stop() is a no-op for webhook channels."""
        ch = _make_webhook_channel()
        await ch.stop()  # Should not raise


class TestWebhookChannelSend:
    @pytest.mark.asyncio
    async def test_send_posts_json(self):
        """send() POSTs correct JSON payload to configured URL."""
        ch = _make_webhook_channel()

        with patch("smolclaw.channel.asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
            await ch.send("chat123", "Hello world")

            mock_thread.assert_awaited_once()
            # First arg to to_thread is urlopen, second is the Request
            call_args = mock_thread.call_args
            req = call_args[0][1]

            assert req.full_url == "https://hooks.example.com/test"
            assert req.method == "POST"
            assert req.get_header("Content-type") == "application/json"

            payload = json.loads(req.data)
            assert payload["agent"] == "testagent"
            assert payload["text"] == "Hello world"
            assert payload["chat_id"] == "chat123"

    @pytest.mark.asyncio
    async def test_send_includes_custom_headers(self):
        """send() includes custom headers from config."""
        ch = _make_webhook_channel(headers={"X-Token": "secret"})

        with patch("smolclaw.channel.asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
            await ch.send("123", "Hi")

            req = mock_thread.call_args[0][1]
            assert req.get_header("X-token") == "secret"

    @pytest.mark.asyncio
    async def test_send_no_url_noop(self):
        """send() is a no-op when no URL is configured."""
        ch = _make_webhook_channel(url="")

        with patch("smolclaw.channel.asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
            await ch.send("123", "Hello")
            mock_thread.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_send_error_logged(self):
        """send() catches and logs errors instead of raising."""
        ch = _make_webhook_channel()

        with patch(
            "smolclaw.channel.asyncio.to_thread",
            new_callable=AsyncMock,
            side_effect=Exception("network error"),
        ):
            # Should not raise
            await ch.send("123", "Hello")

    @pytest.mark.asyncio
    async def test_send_timeout(self):
        """send() passes timeout to urlopen."""
        ch = _make_webhook_channel()

        with patch("smolclaw.channel.asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
            await ch.send("123", "Hello")

            # Verify timeout kwarg is passed
            call_args = mock_thread.call_args
            assert call_args[1].get("timeout") == 30 or call_args[0][2] == 30


class TestWebhookChannelFactory:
    def test_create_webhook(self):
        config = ChannelConfig(url="https://example.com/hook")
        router = Router()
        ch = create_channel("webhook", "myagent", config, router)
        assert isinstance(ch, WebhookChannel)
        assert ch.agent_name == "myagent"

    def test_webhook_in_registry(self):
        assert "webhook" in CHANNEL_TYPES
        assert CHANNEL_TYPES["webhook"] is WebhookChannel


# --- Channel Plugin Registry ---


class _DummyChannel(Channel):
    """Minimal Channel subclass for testing the plugin registry."""

    channel_type = "dummy"

    async def start(self):
        pass

    async def stop(self):
        pass

    async def send(self, chat_id, text):
        pass


class TestRegisterChannel:
    """Tests for the register_channel() API."""

    def setup_method(self):
        """Clear custom channels before each test."""
        _custom_channels.clear()

    def teardown_method(self):
        """Ensure custom channels are clean after each test."""
        _custom_channels.clear()

    def test_register_custom_channel(self):
        register_channel("dummy", _DummyChannel)
        assert "dummy" in _custom_channels
        assert _custom_channels["dummy"] is _DummyChannel

    def test_register_not_a_class_raises(self):
        with pytest.raises(TypeError, match="Expected a Channel subclass"):
            register_channel("bad", "not_a_class")  # type: ignore[arg-type]

    def test_register_non_channel_class_raises(self):
        class NotAChannel:
            pass

        with pytest.raises(TypeError, match="Expected a Channel subclass"):
            register_channel("bad", NotAChannel)  # type: ignore[arg-type]

    def test_register_builtin_name_raises(self):
        with pytest.raises(ValueError, match="Cannot override built-in channel"):
            register_channel("telegram", _DummyChannel)

    def test_register_builtin_webhook_raises(self):
        with pytest.raises(ValueError, match="Cannot override built-in channel"):
            register_channel("webhook", _DummyChannel)

    def test_register_builtin_discord_raises(self):
        with pytest.raises(ValueError, match="Cannot override built-in channel"):
            register_channel("discord", _DummyChannel)

    def test_register_then_create(self):
        register_channel("dummy", _DummyChannel)
        config = ChannelConfig()
        router = Router()
        ch = create_channel("dummy", "agent1", config, router)
        assert isinstance(ch, _DummyChannel)
        assert ch.agent_name == "agent1"

    def test_register_overrides_same_custom(self):
        """Registering the same name twice replaces the previous entry."""
        register_channel("dummy", _DummyChannel)

        class AnotherDummy(Channel):
            channel_type = "dummy2"

            async def start(self):
                pass

            async def stop(self):
                pass

            async def send(self, chat_id, text):
                pass

        register_channel("dummy", AnotherDummy)
        assert _custom_channels["dummy"] is AnotherDummy


class TestListChannelTypes:
    """Tests for list_channel_types()."""

    def setup_method(self):
        _custom_channels.clear()

    def teardown_method(self):
        _custom_channels.clear()

    def test_builtins_listed(self):
        types = list_channel_types()
        assert "telegram" in types
        assert "webhook" in types
        assert "discord" in types

    def test_custom_included(self):
        register_channel("dummy", _DummyChannel)
        types = list_channel_types()
        assert "dummy" in types

    def test_sorted_output(self):
        register_channel("zzz_channel", _DummyChannel)
        types = list_channel_types()
        assert types == sorted(types)

    @patch("importlib.metadata.entry_points")
    def test_entrypoint_channels_included(self, mock_ep):
        """Entry-point discovered channels appear in list_channel_types()."""
        ep = MagicMock()
        ep.name = "ep_channel"
        ep.load.return_value = _DummyChannel
        mock_ep.return_value = [ep]

        types = list_channel_types()
        assert "ep_channel" in types


class TestDiscoverEntrypointChannels:
    """Tests for entry-point based channel discovery."""

    @patch("importlib.metadata.entry_points")
    def test_discovers_valid_channel(self, mock_ep):
        ep = MagicMock()
        ep.name = "ep_test"
        ep.load.return_value = _DummyChannel
        mock_ep.return_value = [ep]

        result = _discover_entrypoint_channels()
        assert "ep_test" in result
        assert result["ep_test"] is _DummyChannel

    @patch("importlib.metadata.entry_points")
    def test_skips_non_channel_class(self, mock_ep):
        ep = MagicMock()
        ep.name = "bad_ep"
        ep.load.return_value = "not_a_channel"
        mock_ep.return_value = [ep]

        result = _discover_entrypoint_channels()
        assert "bad_ep" not in result

    @patch("importlib.metadata.entry_points")
    def test_handles_load_error(self, mock_ep):
        ep = MagicMock()
        ep.name = "broken_ep"
        ep.load.side_effect = ImportError("missing module")
        mock_ep.return_value = [ep]

        result = _discover_entrypoint_channels()
        assert "broken_ep" not in result

    @patch("importlib.metadata.entry_points")
    def test_empty_entry_points(self, mock_ep):
        mock_ep.return_value = []
        result = _discover_entrypoint_channels()
        assert result == {}

    @patch("importlib.metadata.entry_points")
    def test_create_channel_falls_through_to_entrypoints(self, mock_ep):
        """create_channel() discovers entry-point channels when not built-in or custom."""
        _custom_channels.clear()
        ep = MagicMock()
        ep.name = "ep_channel"
        ep.load.return_value = _DummyChannel
        mock_ep.return_value = [ep]

        config = ChannelConfig()
        router = Router()
        ch = create_channel("ep_channel", "agent1", config, router)
        assert isinstance(ch, _DummyChannel)


class TestCreateChannelResolution:
    """Test create_channel resolution order: builtin → custom → entrypoints."""

    def setup_method(self):
        _custom_channels.clear()

    def teardown_method(self):
        _custom_channels.clear()

    def test_builtin_takes_precedence(self):
        """Built-in channels are resolved first."""
        config = ChannelConfig(token_env="TEST_BOT_TOKEN")
        router = Router()
        with patch.dict("os.environ", {"TEST_BOT_TOKEN": "tok"}):
            ch = create_channel("telegram", "a", config, router)
        assert isinstance(ch, TelegramChannel)

    def test_custom_takes_precedence_over_entrypoints(self):
        """Custom-registered channels are tried before entry points."""
        register_channel("mytype", _DummyChannel)

        config = ChannelConfig()
        router = Router()
        with patch("importlib.metadata.entry_points") as mock_ep:
            # Even if an entry point exists, custom should win
            ep = MagicMock()
            ep.name = "mytype"
            ep.load.return_value = TelegramChannel
            mock_ep.return_value = [ep]

            ch = create_channel("mytype", "a", config, router)
            assert isinstance(ch, _DummyChannel)

    def test_unknown_type_with_no_entrypoints_raises(self):
        config = ChannelConfig()
        router = Router()
        with patch("importlib.metadata.entry_points", return_value=[]):
            with pytest.raises(ValueError, match="Unknown channel type"):
                create_channel("nonexistent", "a", config, router)


# --- Multi-Platform Auth (string user IDs) ---


class TestMultiPlatformAuth:
    """Test that authorized_users supports both int and str IDs."""

    def test_string_user_ids_in_config(self):
        config = ChannelConfig(authorized_users=["U07RRK42KNJ", "U07SM1VDVSL"])
        assert config.authorized_users == ["U07RRK42KNJ", "U07SM1VDVSL"]

    def test_mixed_int_str_user_ids(self):
        config = ChannelConfig(authorized_users=[12345, "U07RRK42KNJ"])
        assert config.authorized_users == [12345, "U07RRK42KNJ"]

    def test_telegram_auth_with_int_users(self):
        ch = _make_channel(authorized_users=[111, 222])
        assert ch._is_authorized(111) is True
        assert ch._is_authorized(999) is False

    def test_telegram_auth_with_string_users(self):
        """String user IDs should match when the int is passed as string."""
        ch = _make_channel(authorized_users=["111", "222"])
        # Integer user_id 111 should match string "111" in authorized set
        assert ch._is_authorized(111) is True
        assert ch._is_authorized(999) is False

    def test_telegram_auth_empty_allows_all(self):
        ch = _make_channel(authorized_users=[])
        assert ch._is_authorized(99999) is True


class TestChannelConfigAppToken:
    """Test the app_token_env field for dual-token auth."""

    def test_default_empty(self):
        config = ChannelConfig()
        assert config.app_token_env == ""

    def test_set_app_token(self):
        config = ChannelConfig(app_token_env="SLACK_APP_TOKEN")
        assert config.app_token_env == "SLACK_APP_TOKEN"

    def test_both_tokens(self):
        config = ChannelConfig(token_env="SLACK_BOT_TOKEN", app_token_env="SLACK_APP_TOKEN")
        assert config.token_env == "SLACK_BOT_TOKEN"
        assert config.app_token_env == "SLACK_APP_TOKEN"


# --- Discord Channel ---


def _make_discord_channel(
    token: str = "discord-test-token",
    authorized_users: list[int | str] | None = None,
) -> DiscordChannel:
    config = ChannelConfig(
        token_env="TEST_DISCORD_TOKEN",
        authorized_users=authorized_users or [],
    )
    router = Router()
    with patch.dict("os.environ", {"TEST_DISCORD_TOKEN": token}):
        channel = DiscordChannel("testagent", config, router)
    return channel


class TestDiscordChannelInit:
    def test_basic_init(self):
        ch = _make_discord_channel()
        assert ch.agent_name == "testagent"
        assert ch.channel_type == "discord"
        assert ch._token == "discord-test-token"
        assert ch._client is None
        assert ch._runner_task is None

    def test_authorized_users(self):
        ch = _make_discord_channel(authorized_users=[111, 222])
        assert ch._authorized == {111, 222}

    def test_no_authorized_users(self):
        ch = _make_discord_channel(authorized_users=[])
        assert ch._authorized == set()

    def test_missing_token_env(self):
        config = ChannelConfig(token_env="NONEXISTENT_TOKEN", authorized_users=[])
        router = Router()
        ch = DiscordChannel("testagent", config, router)
        assert ch._token == ""

    def test_repr(self):
        ch = _make_discord_channel()
        r = repr(ch)
        assert "DiscordChannel" in r
        assert "testagent" in r


class TestDiscordChannelAuth:
    def test_authorized_when_no_whitelist(self):
        ch = _make_discord_channel(authorized_users=[])
        assert ch._is_authorized(12345) is True

    def test_authorized_user_in_whitelist(self):
        ch = _make_discord_channel(authorized_users=[111, 222])
        assert ch._is_authorized(111) is True
        assert ch._is_authorized(222) is True

    def test_unauthorized_user(self):
        ch = _make_discord_channel(authorized_users=[111])
        assert ch._is_authorized(999) is False

    def test_string_user_ids(self):
        ch = _make_discord_channel(authorized_users=["111", "222"])
        assert ch._is_authorized(111) is True
        assert ch._is_authorized(999) is False


class TestDiscordChannelStart:
    @pytest.mark.asyncio
    async def test_start_no_token_returns_early(self):
        """start() should log error and return if no token."""
        ch = _make_discord_channel(token="")
        ch._token = ""

        mock_discord = MagicMock()
        with patch.dict("sys.modules", {"discord": mock_discord}):
            await ch.start()

        assert ch._client is None
        assert ch._runner_task is None

    @pytest.mark.asyncio
    async def test_start_missing_discord_py(self):
        """start() should log error if discord.py is not installed."""
        ch = _make_discord_channel()

        # Remove discord from sys.modules and make import fail
        with patch.dict("sys.modules", {"discord": None}):
            await ch.start()

        assert ch._client is None

    @pytest.mark.asyncio
    async def test_start_creates_client_and_task(self):
        """start() should create a Discord client and start a runner task."""
        ch = _make_discord_channel()

        mock_client = MagicMock()
        mock_client.start = AsyncMock()
        mock_client.event = lambda fn: fn  # Decorator passthrough

        mock_intents_cls = MagicMock()
        mock_intents = MagicMock()
        mock_intents_cls.default.return_value = mock_intents

        mock_discord = MagicMock()
        mock_discord.Intents = mock_intents_cls
        mock_discord.Client.return_value = mock_client
        mock_discord.DMChannel = type("DMChannel", (), {})

        with patch.dict("sys.modules", {"discord": mock_discord}):
            await ch.start()

        assert ch._client is mock_client
        assert ch._runner_task is not None

        # Cleanup
        ch._runner_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await ch._runner_task


class TestDiscordChannelStop:
    @pytest.mark.asyncio
    async def test_stop_closes_client(self):
        """stop() should close the Discord client."""
        ch = _make_discord_channel()
        mock_client = MagicMock()
        mock_client.close = AsyncMock()
        ch._client = mock_client
        ch._runner_task = asyncio.create_task(asyncio.sleep(100))

        await ch.stop()

        mock_client.close.assert_awaited_once()
        assert ch._client is None
        assert ch._runner_task is None

    @pytest.mark.asyncio
    async def test_stop_no_client_is_noop(self):
        """stop() should not raise when no client exists."""
        ch = _make_discord_channel()
        await ch.stop()  # Should not raise


class TestDiscordChannelSend:
    @pytest.mark.asyncio
    async def test_send_to_channel(self):
        """send() should fetch channel and send message chunks."""
        ch = _make_discord_channel()
        mock_channel = MagicMock()
        mock_channel.send = AsyncMock()

        mock_client = MagicMock()
        mock_client.get_channel.return_value = mock_channel
        ch._client = mock_client

        await ch.send("12345", "Hello Discord!")

        mock_client.get_channel.assert_called_once_with(12345)
        mock_channel.send.assert_awaited_once_with("Hello Discord!")

    @pytest.mark.asyncio
    async def test_send_fetches_when_cache_miss(self):
        """send() should fetch_channel when get_channel returns None."""
        ch = _make_discord_channel()
        mock_channel = MagicMock()
        mock_channel.send = AsyncMock()

        mock_client = MagicMock()
        mock_client.get_channel.return_value = None
        mock_client.fetch_channel = AsyncMock(return_value=mock_channel)
        ch._client = mock_client

        await ch.send("12345", "Hello!")

        mock_client.fetch_channel.assert_awaited_once_with(12345)
        mock_channel.send.assert_awaited_once_with("Hello!")

    @pytest.mark.asyncio
    async def test_send_splits_long_message(self):
        """send() should split messages exceeding Discord's 2000 char limit."""
        ch = _make_discord_channel()
        mock_channel = MagicMock()
        mock_channel.send = AsyncMock()

        mock_client = MagicMock()
        mock_client.get_channel.return_value = mock_channel
        ch._client = mock_client

        long_text = "A" * 3000
        await ch.send("12345", long_text)

        assert mock_channel.send.await_count >= 2
        for call in mock_channel.send.await_args_list:
            assert len(call[0][0]) <= MAX_DISCORD_LENGTH

    @pytest.mark.asyncio
    async def test_send_no_client_noop(self):
        """send() should be a no-op when client is None."""
        ch = _make_discord_channel()
        ch._client = None
        await ch.send("12345", "Hello")  # Should not raise

    @pytest.mark.asyncio
    async def test_send_error_logged(self):
        """send() should catch and log errors instead of raising."""
        ch = _make_discord_channel()
        mock_client = MagicMock()
        mock_client.get_channel.side_effect = Exception("channel not found")
        ch._client = mock_client

        await ch.send("12345", "Hello")  # Should not raise


async def _start_discord_and_get_handlers(
    authorized_users: list[int] | None = None,
) -> tuple[DiscordChannel, dict]:
    """Start a Discord channel with mocks and capture event handlers."""
    ch = _make_discord_channel(authorized_users=authorized_users)

    # Track registered event handlers
    captured: dict[str, object] = {}

    mock_client = MagicMock()
    mock_client.start = AsyncMock()
    mock_client.user = MagicMock()
    mock_client.user.id = 99999  # Bot's own user ID

    def capture_event(fn):
        captured[fn.__name__] = fn
        return fn

    mock_client.event = capture_event

    mock_intents_cls = MagicMock()
    mock_intents = MagicMock()
    mock_intents_cls.default.return_value = mock_intents

    mock_discord = MagicMock()
    mock_discord.Intents = mock_intents_cls
    mock_discord.Client.return_value = mock_client
    mock_discord.DMChannel = type("MockDMChannel", (), {})

    with patch.dict("sys.modules", {"discord": mock_discord}):
        await ch.start()

    # Store DMChannel class on channel for test access
    ch._dm_channel_cls = mock_discord.DMChannel  # type: ignore[attr-defined]

    # Cleanup runner task
    if ch._runner_task:
        ch._runner_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await ch._runner_task

    return ch, captured


def _make_mock_discord_message(
    content: str = "Hello",
    author_id: int = 111,
    channel_id: int = 999,
    is_dm: bool = True,
    mentions: list | None = None,
    author_is_bot: bool = False,
    bot_user: object | None = None,
) -> MagicMock:
    """Create a mock Discord Message object."""
    message = MagicMock()
    message.content = content
    message.author.id = author_id
    message.channel.id = channel_id
    message.channel.send = AsyncMock()
    message.mentions = mentions or []

    # For DM detection — need real isinstance check
    if is_dm:
        # Patch the channel type
        message.channel.__class__ = type("MockDMChannel", (), {})
    else:
        message.channel.__class__ = type("MockTextChannel", (), {})

    # Set author != bot user for non-bot messages
    if bot_user and author_is_bot:
        message.author = bot_user
    elif bot_user:
        # Different object
        message.author = MagicMock()
        message.author.id = author_id

    return message


class TestDiscordHandlers:
    @pytest.mark.asyncio
    async def test_on_ready_handler_captured(self):
        _ch, handlers = await _start_discord_and_get_handlers()
        assert "on_ready" in handlers

    @pytest.mark.asyncio
    async def test_on_ready_runs(self):
        _ch, handlers = await _start_discord_and_get_handlers()
        # Should not raise
        await handlers["on_ready"]()

    @pytest.mark.asyncio
    async def test_on_message_handler_captured(self):
        _ch, handlers = await _start_discord_and_get_handlers()
        assert "on_message" in handlers

    @pytest.mark.asyncio
    async def test_on_message_ignores_own_messages(self):
        ch, handlers = await _start_discord_and_get_handlers()
        # Create a message where author IS the bot
        message = MagicMock()
        message.author = ch._client.user
        message.content = "self-message"

        await handlers["on_message"](message)
        # No send should happen (message from self)

    @pytest.mark.asyncio
    async def test_on_message_ignores_unauthorized(self):
        _ch, handlers = await _start_discord_and_get_handlers(authorized_users=[111])
        message = MagicMock()
        message.author = MagicMock()
        message.author.id = 999  # Not authorized
        message.content = "Hello"

        await handlers["on_message"](message)
        # No crash = test pass

    @pytest.mark.asyncio
    async def test_on_message_ignores_non_dm_non_mention(self):
        _ch, handlers = await _start_discord_and_get_handlers()
        message = MagicMock()
        message.author = MagicMock()
        message.author.id = 111
        message.content = "Hello"
        message.mentions = []  # Bot not mentioned
        # Not a DM channel - use isinstance check mock
        message.channel.__class__ = type("TextChannel", (), {})

        # Patch isinstance for discord.DMChannel
        # The handler uses isinstance(message.channel, discord.DMChannel)
        # which will be False since we're using a fake class
        await handlers["on_message"](message)
        # No crash = test pass (message should be ignored)

    @pytest.mark.asyncio
    async def test_on_message_skips_empty_text_after_mention_strip(self):
        ch, handlers = await _start_discord_and_get_handlers()
        bot_user = ch._client.user
        bot_user.id = 99999

        message = MagicMock()
        message.author = MagicMock()
        message.author.id = 111
        # Content is just the mention — after stripping, text is empty
        message.content = "<@99999>"
        message.channel.__class__ = ch._dm_channel_cls  # type: ignore[attr-defined]
        message.mentions = [bot_user]
        message.channel.send = AsyncMock()

        await handlers["on_message"](message)
        # send should not be called since text is empty after strip
        message.channel.send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_on_message_routes_dm(self):
        ch, handlers = await _start_discord_and_get_handlers()
        from smolclaw.router import OutboundMessage

        # Create a DM channel as an instance of the mock DMChannel class
        dm_cls = ch._dm_channel_cls  # type: ignore[attr-defined]
        dm_channel = dm_cls()
        dm_channel.id = 12345
        dm_channel.send = AsyncMock()

        # Create an async context manager for typing()
        mock_typing = MagicMock()
        mock_typing.__aenter__ = AsyncMock(return_value=None)
        mock_typing.__aexit__ = AsyncMock(return_value=None)
        dm_channel.typing = MagicMock(return_value=mock_typing)

        message = MagicMock()
        message.author = MagicMock()
        message.author.id = 111
        message.content = "Hello TARS"
        message.channel = dm_channel
        message.mentions = []

        ch.router.route = AsyncMock(
            return_value=OutboundMessage(text="Hello human!", agent="testagent", source="discord")
        )

        await handlers["on_message"](message)

        dm_channel.send.assert_awaited_once_with("Hello human!")

    @pytest.mark.asyncio
    async def test_on_message_handles_timeout(self):
        ch, handlers = await _start_discord_and_get_handlers()

        dm_cls = ch._dm_channel_cls  # type: ignore[attr-defined]
        dm_channel = dm_cls()
        dm_channel.id = 12345
        dm_channel.send = AsyncMock()

        mock_typing = MagicMock()
        mock_typing.__aenter__ = AsyncMock(return_value=None)
        mock_typing.__aexit__ = AsyncMock(return_value=None)
        dm_channel.typing = MagicMock(return_value=mock_typing)

        message = MagicMock()
        message.author = MagicMock()
        message.author.id = 111
        message.content = "slow request"
        message.channel = dm_channel
        message.mentions = []

        ch.router.route = AsyncMock(side_effect=TimeoutError())

        await handlers["on_message"](message)

        dm_channel.send.assert_awaited_once_with("Request timed out.")

    @pytest.mark.asyncio
    async def test_on_message_handles_error(self):
        ch, handlers = await _start_discord_and_get_handlers()

        dm_cls = ch._dm_channel_cls  # type: ignore[attr-defined]
        dm_channel = dm_cls()
        dm_channel.id = 12345
        dm_channel.send = AsyncMock()

        mock_typing = MagicMock()
        mock_typing.__aenter__ = AsyncMock(return_value=None)
        mock_typing.__aexit__ = AsyncMock(return_value=None)
        dm_channel.typing = MagicMock(return_value=mock_typing)

        message = MagicMock()
        message.author = MagicMock()
        message.author.id = 111
        message.content = "broken request"
        message.channel = dm_channel
        message.mentions = []

        ch.router.route = AsyncMock(side_effect=RuntimeError("agent crashed"))

        await handlers["on_message"](message)

        # Error message should be sent
        dm_channel.send.assert_awaited_once()
        sent_text = dm_channel.send.call_args[0][0]
        assert "agent crashed" in sent_text


class TestDiscordChannelFactory:
    def test_create_discord(self):
        config = ChannelConfig(token_env="TEST_DISCORD_TOKEN")
        router = Router()
        with patch.dict("os.environ", {"TEST_DISCORD_TOKEN": "tok"}):
            ch = create_channel("discord", "myagent", config, router)
        assert isinstance(ch, DiscordChannel)
        assert ch.agent_name == "myagent"

    def test_discord_in_registry(self):
        assert "discord" in CHANNEL_TYPES
        assert CHANNEL_TYPES["discord"] is DiscordChannel

    def test_max_discord_length(self):
        assert MAX_DISCORD_LENGTH == 2000
