"""Channel adapters — normalize messages from platforms and route to agents."""

from __future__ import annotations

import asyncio
import contextlib
import html
import logging
import os
import re
from abc import ABC, abstractmethod

from .config import ChannelConfig
from .router import InboundMessage, Router

log = logging.getLogger("smolclaw")

__all__ = ["Channel", "SlackChannel", "TelegramChannel", "WebhookChannel", "create_channel"]


class Channel(ABC):
    """Base class for messaging channel adapters."""

    channel_type: str = "base"

    def __init__(self, agent_name: str, config: ChannelConfig, router: Router):
        """Initialize the channel adapter.

        Args:
            agent_name: Name of the agent this channel serves.
            config: Channel-specific configuration (token env var, auth users).
            router: The message router for dispatching inbound messages.
        """
        self.agent_name = agent_name
        self.config = config
        self.router = router

    def __repr__(self) -> str:
        return f"{type(self).__name__}(agent={self.agent_name!r})"

    @abstractmethod
    async def start(self) -> None:
        """Start listening for messages."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop the channel."""

    @abstractmethod
    async def send(self, chat_id: str, text: str) -> None:
        """Send a message to a chat."""


# --- Telegram Channel ---

MAX_TELEGRAM_LENGTH = 4000
TYPING_INTERVAL = 5


def md_to_telegram_html(text: str) -> str:
    """Convert markdown to Telegram-compatible HTML."""
    result = text

    # Extract code blocks to protect them
    code_blocks: list[str] = []

    def save_code_block(m):
        code_blocks.append(m.group(2))
        return f"\x00CODEBLOCK{len(code_blocks) - 1}\x00"

    result = re.sub(r"```(\w*)\n?(.*?)```", save_code_block, result, flags=re.DOTALL)

    # Extract inline code
    inline_codes: list[str] = []

    def save_inline_code(m):
        inline_codes.append(m.group(1))
        return f"\x00INLINE{len(inline_codes) - 1}\x00"

    result = re.sub(r"`([^`]+)`", save_inline_code, result)

    # Escape HTML
    result = html.escape(result)

    # Bold
    result = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", result)
    result = re.sub(r"__(.+?)__", r"<b>\1</b>", result)

    # Italic
    result = re.sub(r"(?<!\w)\*([^*]+?)\*(?!\w)", r"<i>\1</i>", result)
    result = re.sub(r"(?<!\w)_([^_]+?)_(?!\w)", r"<i>\1</i>", result)

    # Strikethrough
    result = re.sub(r"~~(.+?)~~", r"<s>\1</s>", result)

    # Links
    result = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', result)

    # Headings → bold
    result = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", result, flags=re.MULTILINE)

    # Restore inline code
    for i, code in enumerate(inline_codes):
        result = result.replace(f"\x00INLINE{i}\x00", f"<code>{html.escape(code)}</code>")

    # Restore code blocks
    for i, code in enumerate(code_blocks):
        result = result.replace(f"\x00CODEBLOCK{i}\x00", f"<pre>{html.escape(code)}</pre>")

    return result


def split_message(text: str, max_len: int = MAX_TELEGRAM_LENGTH) -> list[str]:
    """Split long text at paragraph boundaries."""
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    current = ""

    for paragraph in text.split("\n\n"):
        if len(current) + len(paragraph) + 2 > max_len:
            if current:
                chunks.append(current.strip())
                current = ""
            if len(paragraph) > max_len:
                for line in paragraph.split("\n"):
                    if len(current) + len(line) + 1 > max_len:
                        if current:
                            chunks.append(current.strip())
                        current = line + "\n"
                    else:
                        current += line + "\n"
            else:
                current = paragraph + "\n\n"
        else:
            current += paragraph + "\n\n"

    if current.strip():
        chunks.append(current.strip())

    return chunks if chunks else [text[:max_len]]


class TelegramChannel(Channel):
    """Telegram bot channel adapter."""

    channel_type = "telegram"

    def __init__(self, agent_name: str, config: ChannelConfig, router: Router):
        """Initialize the Telegram channel with token and authorization config."""
        super().__init__(agent_name, config, router)
        self._app = None
        self._token = os.environ.get(config.token_env, "")
        self._authorized = set(config.authorized_users)

    def _is_authorized(self, user_id: int) -> bool:
        if not self._authorized:
            return True
        return user_id in self._authorized

    async def start(self) -> None:
        """Start polling Telegram for messages and register command handlers."""
        from telegram import Update
        from telegram.constants import ChatAction, ParseMode
        from telegram.ext import (
            Application,
            CommandHandler,
            ContextTypes,
            MessageHandler,
            filters,
        )

        if not self._token:
            log.error(f"[{self.agent_name}] Telegram: no token in env var {self.config.token_env}")
            return

        agent_name = self.agent_name
        router = self.router
        authorized = self._authorized

        def is_auth(user_id: int) -> bool:
            return not authorized or user_id in authorized

        async def send_response(update: Update, text: str):
            html_text = md_to_telegram_html(text)
            for chunk in split_message(html_text):
                try:
                    await update.message.reply_text(chunk, parse_mode=ParseMode.HTML)
                except Exception as e:
                    log.debug(f"[{agent_name}] HTML send failed, falling back to plain: {e}")
                    plain = re.sub(r"<[^>]+>", "", chunk)
                    try:
                        await update.message.reply_text(plain)
                    except Exception as e:
                        log.error(f"[{agent_name}] Telegram send failed: {e}")

        async def send_typing(update: Update):
            try:
                while True:
                    await update.message.chat.send_action(ChatAction.TYPING)
                    await asyncio.sleep(TYPING_INTERVAL)
            except asyncio.CancelledError:
                pass

        async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not update.message or not update.message.text:
                return
            if not is_auth(update.effective_user.id):
                return

            chat_id = str(update.message.chat_id)
            text = update.message.text

            typing_task = asyncio.create_task(send_typing(update))
            try:
                msg = InboundMessage(
                    agent=agent_name,
                    text=text,
                    source="telegram",
                    chat_id=chat_id,
                )
                outbound = await asyncio.wait_for(router.route(msg), timeout=900)
                await send_response(update, outbound.text)
            except TimeoutError:
                await update.message.reply_text("Request timed out.")
            except Exception as e:
                await update.message.reply_text(f"Error: {e}")
            finally:
                typing_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await typing_task

        async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not is_auth(update.effective_user.id):
                uid = update.effective_user.id
                await update.message.reply_text(f"Unauthorized. Your ID: {uid}")
                return
            await update.message.reply_text(f"{agent_name} online. Send me a message.")

        async def cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not is_auth(update.effective_user.id):
                return
            agent = router.get_agent(agent_name)
            if agent:
                await agent.new_session()
            await update.message.reply_text("Session cleared.")

        app = (
            Application.builder()
            .token(self._token)
            .get_updates_read_timeout(15)
            .get_updates_connect_timeout(10)
            .get_updates_pool_timeout(10)
            .build()
        )

        app.add_handler(CommandHandler("start", cmd_start))
        app.add_handler(CommandHandler("new", cmd_new))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        self._app = app

        log.info(f"[{self.agent_name}] Telegram channel starting")
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)

    async def stop(self) -> None:
        """Stop the Telegram polling loop and shut down the application."""
        if self._app:
            log.info(f"[{self.agent_name}] Telegram channel stopping")
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
            self._app = None

    async def send(self, chat_id: str, text: str) -> None:
        """Send a message to a specific chat (for cron delivery etc.)."""
        if not self._app:
            return
        html_text = md_to_telegram_html(text)
        for chunk in split_message(html_text):
            try:
                await self._app.bot.send_message(
                    chat_id=int(chat_id),
                    text=chunk,
                    parse_mode="HTML",
                )
            except Exception as e:
                log.debug(f"[{self.agent_name}] HTML send failed, falling back to plain: {e}")
                plain = re.sub(r"<[^>]+>", "", chunk)
                try:
                    await self._app.bot.send_message(chat_id=int(chat_id), text=plain)
                except Exception as e:
                    log.error(f"[{self.agent_name}] Telegram send to {chat_id} failed: {e}")


# --- Webhook Channel ---


class WebhookChannel(Channel):
    """Outgoing webhook channel — POSTs agent responses to a configured URL.

    Send-only channel for delivering messages to HTTP endpoints (e.g. Slack
    incoming webhooks, Discord webhooks, custom APIs). Does not receive
    inbound messages (use the REST API for that).

    Config in agent.yaml::

        channels:
          webhook:
            url: "https://hooks.example.com/endpoint"
            headers:
              X-Custom-Header: "value"
    """

    channel_type = "webhook"

    def __init__(self, agent_name: str, config: ChannelConfig, router: Router):
        """Initialize the webhook channel with URL and optional headers."""
        super().__init__(agent_name, config, router)
        self._url = config.url
        self._headers = {
            "Content-Type": "application/json",
            **config.headers,
        }

    async def start(self) -> None:
        """Validate webhook configuration (no persistent connection needed)."""
        if not self._url:
            log.error(f"[{self.agent_name}] Webhook: no url configured")
            return
        log.info(f"[{self.agent_name}] Webhook channel ready → {self._url}")

    async def stop(self) -> None:
        """No-op — webhook channel has no persistent connection."""

    async def send(self, chat_id: str, text: str) -> None:
        """POST a JSON payload to the configured webhook URL."""
        import json
        import urllib.request

        if not self._url:
            return

        payload = json.dumps(
            {
                "agent": self.agent_name,
                "text": text,
                "chat_id": chat_id,
            }
        ).encode()

        req = urllib.request.Request(
            self._url,
            data=payload,
            headers=self._headers,
            method="POST",
        )

        try:
            await asyncio.to_thread(urllib.request.urlopen, req, timeout=30)
        except Exception as e:
            log.error(f"[{self.agent_name}] Webhook POST to {self._url} failed: {e}")


# --- Slack Channel ---

MAX_SLACK_LENGTH = 4000


class SlackChannel(Channel):
    """Slack bot channel adapter using Socket Mode (WebSocket).

    Bidirectional channel: receives messages via Slack's Socket Mode API and
    sends responses back. Requires the ``slack-sdk`` optional dependency with
    aiohttp for async Socket Mode support.

    Needs two tokens:
    - Bot token (xoxb-...) for sending messages via Web API
    - App-level token (xapp-...) for Socket Mode WebSocket connection

    Config in agent.yaml::

        channels:
          slack:
            token_env: SLACK_BOT_TOKEN       # xoxb-... bot token
            app_token_env: SLACK_APP_TOKEN   # xapp-... app-level token
            authorized_users: ["U12345"]     # Slack user IDs (strings), empty = allow all
    """

    channel_type = "slack"

    def __init__(self, agent_name: str, config: ChannelConfig, router: Router):
        """Initialize the Slack channel with bot and app-level tokens."""
        super().__init__(agent_name, config, router)
        self._token = os.environ.get(config.token_env, "")
        self._app_token = os.environ.get(config.app_token_env, "")
        self._authorized = {str(u) for u in config.authorized_users}
        self._web_client = None
        self._socket_client = None

    def _is_authorized(self, user_id: str) -> bool:
        if not self._authorized:
            return True
        return user_id in self._authorized

    async def start(self) -> None:
        """Connect to Slack via Socket Mode and register event handlers."""
        try:
            from slack_sdk.socket_mode.aiohttp import SocketModeClient
            from slack_sdk.web.async_client import AsyncWebClient
        except ImportError:
            log.error(
                f"[{self.agent_name}] Slack: slack-sdk not installed. "
                f"Install with: pip install smolclaw[slack]"
            )
            return

        if not self._token:
            log.error(f"[{self.agent_name}] Slack: no bot token in env var {self.config.token_env}")
            return
        if not self._app_token:
            log.error(
                f"[{self.agent_name}] Slack: no app token in env var {self.config.app_token_env}"
            )
            return

        self._web_client = AsyncWebClient(token=self._token)

        self._socket_client = SocketModeClient(
            app_token=self._app_token,
            web_client=self._web_client,
        )
        self._socket_client.socket_mode_request_listeners.append(self._handle_request)

        log.info(f"[{self.agent_name}] Slack channel starting (Socket Mode)")
        await self._socket_client.connect()

    async def _handle_request(self, client: object, req: object) -> None:
        """Handle incoming Socket Mode requests (events, interactions, etc.)."""
        from slack_sdk.socket_mode.response import SocketModeResponse

        # Acknowledge immediately to avoid Slack retries
        response = SocketModeResponse(envelope_id=req.envelope_id)  # type: ignore[attr-defined]
        await client.send_socket_mode_response(response)  # type: ignore[attr-defined]

        if req.type != "events_api":  # type: ignore[attr-defined]
            return

        event = req.payload.get("event", {})  # type: ignore[attr-defined]

        # Only handle user messages (not bot messages, edits, joins, etc.)
        if event.get("type") != "message" or event.get("subtype"):
            return

        user_id = event.get("user", "")
        text = event.get("text", "")
        channel = event.get("channel", "")

        if not text or not user_id:
            return
        if not self._is_authorized(user_id):
            return

        try:
            msg = InboundMessage(
                agent=self.agent_name,
                text=text,
                source="slack",
                chat_id=channel,
            )
            outbound = await asyncio.wait_for(self.router.route(msg), timeout=900)
            for chunk in _split_slack_message(outbound.text):
                await self._web_client.chat_postMessage(channel=channel, text=chunk)
        except TimeoutError:
            await self._web_client.chat_postMessage(channel=channel, text="Request timed out.")
        except Exception as e:
            log.error(f"[{self.agent_name}] Slack message handling failed: {e}")
            await self._web_client.chat_postMessage(channel=channel, text=f"Error: {e}")

    async def stop(self) -> None:
        """Disconnect the Socket Mode client."""
        if self._socket_client:
            log.info(f"[{self.agent_name}] Slack channel stopping")
            await self._socket_client.disconnect()
            self._socket_client = None
            self._web_client = None

    async def send(self, chat_id: str, text: str) -> None:
        """Send a message to a Slack channel (for cron delivery etc.)."""
        if not self._web_client:
            return
        for chunk in _split_slack_message(text):
            try:
                await self._web_client.chat_postMessage(channel=chat_id, text=chunk)
            except Exception as e:
                log.error(f"[{self.agent_name}] Slack send to {chat_id} failed: {e}")


def _split_slack_message(text: str, max_len: int = MAX_SLACK_LENGTH) -> list[str]:
    """Split a message into chunks that fit Slack's message limit.

    Splits on paragraph boundaries (double newline), then single newlines
    for oversized paragraphs.
    """
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    current = ""

    for paragraph in text.split("\n\n"):
        if len(current) + len(paragraph) + 2 > max_len:
            if current:
                chunks.append(current.strip())
                current = ""
            if len(paragraph) > max_len:
                for line in paragraph.split("\n"):
                    if len(current) + len(line) + 1 > max_len:
                        if current:
                            chunks.append(current.strip())
                        current = line + "\n"
                    else:
                        current += line + "\n"
            else:
                current = paragraph + "\n\n"
        else:
            current += paragraph + "\n\n"

    if current.strip():
        chunks.append(current.strip())

    return chunks if chunks else [text[:max_len]]


# --- Channel Factory ---

CHANNEL_TYPES: dict[str, type[Channel]] = {
    "slack": SlackChannel,
    "telegram": TelegramChannel,
    "webhook": WebhookChannel,
}


def create_channel(
    channel_type: str,
    agent_name: str,
    config: ChannelConfig,
    router: Router,
) -> Channel:
    """Create a channel adapter by type name."""
    cls = CHANNEL_TYPES.get(channel_type)
    if not cls:
        raise ValueError(f"Unknown channel type: {channel_type}. Available: {list(CHANNEL_TYPES)}")
    return cls(agent_name, config, router)
