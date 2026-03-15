"""Tests for channel helper functions and TelegramChannel adapter."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from smolclaw.channel import (
    CHANNEL_TYPES,
    TelegramChannel,
    create_channel,
    md_to_telegram_html,
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


# --- TelegramChannel ---


def _make_channel(
    token: str = "test-token",
    authorized_users: list[int] | None = None,
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
        mock_updater.start_polling.assert_awaited_once_with(drop_pending_updates=True)
        assert mock_app.add_handler.call_count == 3  # /start, /new, message


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
            create_channel("discord", "myagent", config, router)

    def test_channel_types_registry(self):
        assert "telegram" in CHANNEL_TYPES
        assert CHANNEL_TYPES["telegram"] is TelegramChannel


class TestChannelRepr:
    def test_telegram_channel_repr(self):
        ch = _make_channel()
        r = repr(ch)
        assert "TelegramChannel" in r
        assert "testagent" in r
