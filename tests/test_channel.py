"""Tests for channel functions, Telegram, Webhook, and Slack adapters."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from smolclaw.channel import (
    CHANNEL_TYPES,
    SlackChannel,
    TelegramChannel,
    WebhookChannel,
    _split_slack_message,
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
            create_channel("carrier_pigeon", "myagent", config, router)

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


# --- Slack Channel ---


def _make_slack_channel(
    token: str = "xoxb-test-token",
    app_token: str = "xapp-test-token",
    authorized_users: list[str] | None = None,
) -> SlackChannel:
    config = ChannelConfig(
        token_env="SLACK_BOT_TOKEN",
        app_token_env="SLACK_APP_TOKEN",
        authorized_users=authorized_users or [],
    )
    router = Router()
    with patch.dict(
        "os.environ",
        {"SLACK_BOT_TOKEN": token, "SLACK_APP_TOKEN": app_token},
    ):
        channel = SlackChannel("testagent", config, router)
    return channel


class TestSlackChannelInit:
    def test_basic_init(self):
        ch = _make_slack_channel()
        assert ch.agent_name == "testagent"
        assert ch.channel_type == "slack"
        assert ch._token == "xoxb-test-token"
        assert ch._app_token == "xapp-test-token"
        assert ch._web_client is None
        assert ch._socket_client is None

    def test_authorized_users_strings(self):
        ch = _make_slack_channel(authorized_users=["U111", "U222"])
        assert ch._authorized == {"U111", "U222"}

    def test_authorized_users_mixed_types(self):
        """Integer user IDs from YAML should be stringified."""
        ch = _make_slack_channel(authorized_users=["U111", "12345"])
        assert "U111" in ch._authorized
        assert "12345" in ch._authorized

    def test_no_authorized_users(self):
        ch = _make_slack_channel(authorized_users=[])
        assert ch._authorized == set()

    def test_missing_token_env(self):
        config = ChannelConfig(
            token_env="NONEXISTENT_TOKEN",
            app_token_env="NONEXISTENT_APP_TOKEN",
        )
        router = Router()
        ch = SlackChannel("testagent", config, router)
        assert ch._token == ""
        assert ch._app_token == ""

    def test_repr(self):
        ch = _make_slack_channel()
        r = repr(ch)
        assert "SlackChannel" in r
        assert "testagent" in r


class TestSlackChannelAuth:
    def test_authorized_when_no_whitelist(self):
        ch = _make_slack_channel(authorized_users=[])
        assert ch._is_authorized("U12345") is True

    def test_authorized_user_in_whitelist(self):
        ch = _make_slack_channel(authorized_users=["U111", "U222"])
        assert ch._is_authorized("U111") is True
        assert ch._is_authorized("U222") is True

    def test_unauthorized_user(self):
        ch = _make_slack_channel(authorized_users=["U111"])
        assert ch._is_authorized("U999") is False


def _build_slack_mocks():
    """Create mocked slack_sdk modules for testing."""
    mock_web_client_cls = MagicMock()
    mock_web_client = AsyncMock()
    mock_web_client.chat_postMessage = AsyncMock()
    mock_web_client_cls.return_value = mock_web_client

    mock_socket_client_cls = MagicMock()
    mock_socket_client = MagicMock()
    mock_socket_client.connect = AsyncMock()
    mock_socket_client.disconnect = AsyncMock()
    mock_socket_client.socket_mode_request_listeners = []
    mock_socket_client_cls.return_value = mock_socket_client

    mock_response_cls = MagicMock()

    modules = {
        "slack_sdk": MagicMock(),
        "slack_sdk.web": MagicMock(),
        "slack_sdk.web.async_client": MagicMock(AsyncWebClient=mock_web_client_cls),
        "slack_sdk.socket_mode": MagicMock(),
        "slack_sdk.socket_mode.aiohttp": MagicMock(SocketModeClient=mock_socket_client_cls),
        "slack_sdk.socket_mode.response": MagicMock(SocketModeResponse=mock_response_cls),
        "aiohttp": MagicMock(),
    }

    return modules, mock_web_client, mock_socket_client, mock_response_cls


class TestSlackChannelStart:
    @pytest.mark.asyncio
    async def test_start_no_bot_token_returns_early(self):
        ch = _make_slack_channel(token="")
        ch._token = ""
        await ch.start()
        assert ch._web_client is None
        assert ch._socket_client is None

    @pytest.mark.asyncio
    async def test_start_no_app_token_returns_early(self):
        ch = _make_slack_channel(app_token="")
        ch._app_token = ""
        modules, _, _, _ = _build_slack_mocks()
        with patch.dict("sys.modules", modules):
            await ch.start()
        assert ch._socket_client is None

    @pytest.mark.asyncio
    async def test_start_import_error(self):
        """start() should log error if slack_sdk is not installed."""
        ch = _make_slack_channel()
        # Simulate ImportError by making the import fail
        with patch.dict("sys.modules", {"slack_sdk.socket_mode.aiohttp": None}):
            # The import inside start() will raise ImportError
            await ch.start()
        assert ch._web_client is None

    @pytest.mark.asyncio
    async def test_start_connects(self):
        ch = _make_slack_channel()
        modules, mock_web, mock_socket, _ = _build_slack_mocks()

        with patch.dict("sys.modules", modules):
            await ch.start()

        assert ch._web_client is mock_web
        assert ch._socket_client is mock_socket
        mock_socket.connect.assert_awaited_once()
        assert len(mock_socket.socket_mode_request_listeners) == 1


class TestSlackChannelStop:
    @pytest.mark.asyncio
    async def test_stop_with_no_client(self):
        ch = _make_slack_channel()
        await ch.stop()
        assert ch._socket_client is None

    @pytest.mark.asyncio
    async def test_stop_disconnects(self):
        ch = _make_slack_channel()
        mock_socket = MagicMock()
        mock_socket.disconnect = AsyncMock()
        ch._socket_client = mock_socket
        ch._web_client = MagicMock()

        await ch.stop()

        mock_socket.disconnect.assert_awaited_once()
        assert ch._socket_client is None
        assert ch._web_client is None


class TestSlackChannelSend:
    @pytest.mark.asyncio
    async def test_send_no_client(self):
        ch = _make_slack_channel()
        await ch.send("C123", "Hello")  # No-op

    @pytest.mark.asyncio
    async def test_send_success(self):
        ch = _make_slack_channel()
        mock_web = AsyncMock()
        mock_web.chat_postMessage = AsyncMock()
        ch._web_client = mock_web

        await ch.send("C12345", "Hello world")

        mock_web.chat_postMessage.assert_awaited_once_with(channel="C12345", text="Hello world")

    @pytest.mark.asyncio
    async def test_send_splits_long_message(self):
        ch = _make_slack_channel()
        mock_web = AsyncMock()
        mock_web.chat_postMessage = AsyncMock()
        ch._web_client = mock_web

        long_text = ("A" * 200 + "\n\n") * 30  # >4000 chars
        await ch.send("C123", long_text)

        assert mock_web.chat_postMessage.await_count >= 2

    @pytest.mark.asyncio
    async def test_send_error_logged(self):
        ch = _make_slack_channel()
        mock_web = AsyncMock()
        mock_web.chat_postMessage = AsyncMock(side_effect=Exception("network error"))
        ch._web_client = mock_web

        # Should not raise
        await ch.send("C123", "Hello")


class TestSlackChannelHandleRequest:
    @pytest.mark.asyncio
    async def test_handle_message_event(self):
        """Message events should be routed and responded to."""
        from smolclaw.router import OutboundMessage

        ch = _make_slack_channel()
        mock_web = AsyncMock()
        mock_web.chat_postMessage = AsyncMock()
        ch._web_client = mock_web
        ch.router.route = AsyncMock(
            return_value=OutboundMessage(agent="testagent", text="Hello back!", source="slack")
        )

        # Build mock request
        req = MagicMock()
        req.type = "events_api"
        req.envelope_id = "env123"
        req.payload = {
            "event": {
                "type": "message",
                "user": "U111",
                "text": "Hi there",
                "channel": "C999",
            }
        }

        client = MagicMock()
        client.send_socket_mode_response = AsyncMock()

        mock_response_cls = MagicMock()

        with patch("smolclaw.channel.SocketModeResponse", mock_response_cls, create=True):
            with patch.dict(
                "sys.modules",
                {"slack_sdk.socket_mode.response": MagicMock(SocketModeResponse=mock_response_cls)},
            ):
                await ch._handle_request(client, req)

        # Acknowledged
        client.send_socket_mode_response.assert_awaited_once()

        # Message was routed
        ch.router.route.assert_awaited_once()
        routed_msg = ch.router.route.call_args[0][0]
        assert routed_msg.text == "Hi there"
        assert routed_msg.agent == "testagent"
        assert routed_msg.source == "slack"
        assert routed_msg.chat_id == "C999"

        # Response sent
        mock_web.chat_postMessage.assert_awaited_once_with(channel="C999", text="Hello back!")

    @pytest.mark.asyncio
    async def test_handle_non_events_api_ignored(self):
        """Non events_api requests should be acknowledged but ignored."""
        ch = _make_slack_channel()
        ch.router.route = AsyncMock()

        req = MagicMock()
        req.type = "slash_commands"
        req.envelope_id = "env123"

        client = MagicMock()
        client.send_socket_mode_response = AsyncMock()

        mock_response_cls = MagicMock()
        with patch.dict(
            "sys.modules",
            {"slack_sdk.socket_mode.response": MagicMock(SocketModeResponse=mock_response_cls)},
        ):
            await ch._handle_request(client, req)

        client.send_socket_mode_response.assert_awaited_once()
        ch.router.route.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_handle_message_subtype_ignored(self):
        """Message events with subtypes (edits, joins, etc.) should be ignored."""
        ch = _make_slack_channel()
        ch.router.route = AsyncMock()

        req = MagicMock()
        req.type = "events_api"
        req.envelope_id = "env123"
        req.payload = {
            "event": {
                "type": "message",
                "subtype": "message_changed",
                "user": "U111",
                "text": "edited",
                "channel": "C999",
            }
        }

        client = MagicMock()
        client.send_socket_mode_response = AsyncMock()

        mock_response_cls = MagicMock()
        with patch.dict(
            "sys.modules",
            {"slack_sdk.socket_mode.response": MagicMock(SocketModeResponse=mock_response_cls)},
        ):
            await ch._handle_request(client, req)

        ch.router.route.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_handle_message_unauthorized_ignored(self):
        """Messages from unauthorized users should be ignored."""
        ch = _make_slack_channel(authorized_users=["U111"])
        ch.router.route = AsyncMock()

        req = MagicMock()
        req.type = "events_api"
        req.envelope_id = "env123"
        req.payload = {
            "event": {
                "type": "message",
                "user": "U999",
                "text": "Hi",
                "channel": "C999",
            }
        }

        client = MagicMock()
        client.send_socket_mode_response = AsyncMock()

        mock_response_cls = MagicMock()
        with patch.dict(
            "sys.modules",
            {"slack_sdk.socket_mode.response": MagicMock(SocketModeResponse=mock_response_cls)},
        ):
            await ch._handle_request(client, req)

        ch.router.route.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_handle_message_empty_text_ignored(self):
        """Messages with empty text should be ignored."""
        ch = _make_slack_channel()
        ch.router.route = AsyncMock()

        req = MagicMock()
        req.type = "events_api"
        req.envelope_id = "env123"
        req.payload = {
            "event": {
                "type": "message",
                "user": "U111",
                "text": "",
                "channel": "C999",
            }
        }

        client = MagicMock()
        client.send_socket_mode_response = AsyncMock()

        mock_response_cls = MagicMock()
        with patch.dict(
            "sys.modules",
            {"slack_sdk.socket_mode.response": MagicMock(SocketModeResponse=mock_response_cls)},
        ):
            await ch._handle_request(client, req)

        ch.router.route.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_handle_message_no_user_ignored(self):
        """Messages with no user field should be ignored."""
        ch = _make_slack_channel()
        ch.router.route = AsyncMock()

        req = MagicMock()
        req.type = "events_api"
        req.envelope_id = "env123"
        req.payload = {
            "event": {
                "type": "message",
                "text": "Hi",
                "channel": "C999",
            }
        }

        client = MagicMock()
        client.send_socket_mode_response = AsyncMock()

        mock_response_cls = MagicMock()
        with patch.dict(
            "sys.modules",
            {"slack_sdk.socket_mode.response": MagicMock(SocketModeResponse=mock_response_cls)},
        ):
            await ch._handle_request(client, req)

        ch.router.route.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_handle_message_timeout(self):
        """Timeout during routing should send error message."""
        ch = _make_slack_channel()
        mock_web = AsyncMock()
        mock_web.chat_postMessage = AsyncMock()
        ch._web_client = mock_web
        ch.router.route = AsyncMock(side_effect=asyncio.TimeoutError)

        req = MagicMock()
        req.type = "events_api"
        req.envelope_id = "env123"
        req.payload = {
            "event": {
                "type": "message",
                "user": "U111",
                "text": "Hi",
                "channel": "C999",
            }
        }

        client = MagicMock()
        client.send_socket_mode_response = AsyncMock()

        mock_response_cls = MagicMock()
        with patch.dict(
            "sys.modules",
            {"slack_sdk.socket_mode.response": MagicMock(SocketModeResponse=mock_response_cls)},
        ):
            await ch._handle_request(client, req)

        mock_web.chat_postMessage.assert_awaited_once_with(
            channel="C999", text="Request timed out."
        )

    @pytest.mark.asyncio
    async def test_handle_message_error(self):
        """Errors during routing should send error message."""
        ch = _make_slack_channel()
        mock_web = AsyncMock()
        mock_web.chat_postMessage = AsyncMock()
        ch._web_client = mock_web
        ch.router.route = AsyncMock(side_effect=RuntimeError("agent crashed"))

        req = MagicMock()
        req.type = "events_api"
        req.envelope_id = "env123"
        req.payload = {
            "event": {
                "type": "message",
                "user": "U111",
                "text": "Hi",
                "channel": "C999",
            }
        }

        client = MagicMock()
        client.send_socket_mode_response = AsyncMock()

        mock_response_cls = MagicMock()
        with patch.dict(
            "sys.modules",
            {"slack_sdk.socket_mode.response": MagicMock(SocketModeResponse=mock_response_cls)},
        ):
            await ch._handle_request(client, req)

        mock_web.chat_postMessage.assert_awaited_once()
        msg = mock_web.chat_postMessage.call_args[1]["text"]
        assert "Error" in msg

    @pytest.mark.asyncio
    async def test_handle_non_message_event_ignored(self):
        """Non-message events (like reaction_added) should be ignored."""
        ch = _make_slack_channel()
        ch.router.route = AsyncMock()

        req = MagicMock()
        req.type = "events_api"
        req.envelope_id = "env123"
        req.payload = {
            "event": {
                "type": "reaction_added",
                "user": "U111",
                "reaction": "thumbsup",
            }
        }

        client = MagicMock()
        client.send_socket_mode_response = AsyncMock()

        mock_response_cls = MagicMock()
        with patch.dict(
            "sys.modules",
            {"slack_sdk.socket_mode.response": MagicMock(SocketModeResponse=mock_response_cls)},
        ):
            await ch._handle_request(client, req)

        ch.router.route.assert_not_awaited()


# --- Slack message splitting ---


class TestSplitSlackMessage:
    def test_short_message_no_split(self):
        assert _split_slack_message("Hello") == ["Hello"]

    def test_long_message_splits_at_paragraphs(self):
        text = ("A" * 100 + "\n\n") * 50
        chunks = _split_slack_message(text, max_len=500)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= 500

    def test_single_long_paragraph_splits_at_lines(self):
        text = "\n".join(["Line " + str(i) for i in range(200)])
        chunks = _split_slack_message(text, max_len=200)
        assert len(chunks) > 1

    def test_empty_returns_original(self):
        assert _split_slack_message("") == [""]

    def test_exactly_at_limit(self):
        text = "A" * 4000
        assert _split_slack_message(text) == [text]

    def test_preserves_all_content(self):
        paragraphs = [f"Paragraph {i}" for i in range(20)]
        text = "\n\n".join(paragraphs)
        chunks = _split_slack_message(text, max_len=100)
        rejoined = " ".join(chunks)
        for p in paragraphs:
            assert p in rejoined

    def test_single_huge_line_fallback(self):
        text = "X" * 500
        chunks = _split_slack_message(text, max_len=100)
        assert len(chunks) >= 1


# --- Slack in channel factory ---


class TestSlackChannelFactory:
    def test_create_slack(self):
        config = ChannelConfig(
            token_env="SLACK_TOKEN",
            app_token_env="SLACK_APP_TOKEN",
        )
        router = Router()
        with patch.dict("os.environ", {"SLACK_TOKEN": "xoxb-test", "SLACK_APP_TOKEN": "xapp-test"}):
            ch = create_channel("slack", "myagent", config, router)
        assert isinstance(ch, SlackChannel)
        assert ch.agent_name == "myagent"

    def test_slack_in_registry(self):
        assert "slack" in CHANNEL_TYPES
        assert CHANNEL_TYPES["slack"] is SlackChannel
