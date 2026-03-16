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

__all__ = [
    "CHANNEL_TYPES",
    "Channel",
    "TelegramChannel",
    "WebhookChannel",
    "create_channel",
    "list_channel_types",
    "register_channel",
]


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
        # Normalize authorized_users to a set — accept both int and str IDs
        self._authorized: set[int | str] = set(config.authorized_users)

    def _is_authorized(self, user_id: int) -> bool:
        """Check if a user is authorized (empty set = allow all)."""
        if not self._authorized:
            return True
        # Match against both raw int and string representation
        return user_id in self._authorized or str(user_id) in self._authorized

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


# --- Channel Registry ---

_BUILTIN_CHANNELS: dict[str, type[Channel]] = {
    "telegram": TelegramChannel,
    "webhook": WebhookChannel,
}

_custom_channels: dict[str, type[Channel]] = {}

# Backward-compatible alias — prefer register_channel() / list_channel_types() for new code.
CHANNEL_TYPES = _BUILTIN_CHANNELS


def register_channel(name: str, cls: type[Channel]) -> None:
    """Register a custom channel type.

    Third-party packages can call this to add new channel adapters
    (e.g. Discord, Slack, WhatsApp) without modifying smolclaw core.

    Args:
        name: Channel type name (used in agent.yaml ``channels:`` section).
        cls: A :class:`Channel` subclass implementing ``start``, ``stop``, ``send``.

    Raises:
        TypeError: If *cls* is not a :class:`Channel` subclass.
        ValueError: If *name* conflicts with a built-in channel type.

    Example::

        from smolclaw.channel import Channel, register_channel

        class MyChannel(Channel):
            channel_type = "my_platform"
            async def start(self): ...
            async def stop(self): ...
            async def send(self, chat_id, text): ...

        register_channel("my_platform", MyChannel)
    """
    if not (isinstance(cls, type) and issubclass(cls, Channel)):
        raise TypeError(f"Expected a Channel subclass, got {cls!r}")
    if name in _BUILTIN_CHANNELS:
        raise ValueError(
            f"Cannot override built-in channel '{name}'. "
            f"Choose a different name for your custom channel."
        )
    _custom_channels[name] = cls
    log.info(f"Registered custom channel type: {name}")


def _discover_entrypoint_channels() -> dict[str, type[Channel]]:
    """Discover channel plugins via ``smolclaw.channels`` entry points.

    Third-party packages declare entry points in their ``pyproject.toml``::

        [project.entry-points."smolclaw.channels"]
        discord = "smolclaw_discord:DiscordChannel"

    Returns:
        Mapping of channel-type name to Channel subclass.
    """
    from importlib.metadata import entry_points

    discovered: dict[str, type[Channel]] = {}
    eps = entry_points(group="smolclaw.channels")
    for ep in eps:
        try:
            cls = ep.load()
            if isinstance(cls, type) and issubclass(cls, Channel):
                discovered[ep.name] = cls
                log.debug(f"Discovered channel plugin: {ep.name} → {cls.__name__}")
            else:
                log.warning(f"Channel entry point '{ep.name}' is not a Channel subclass, skipping")
        except Exception as e:
            log.warning(f"Failed to load channel entry point '{ep.name}': {e}")
    return discovered


def list_channel_types() -> list[str]:
    """Return all available channel type names (built-in + custom + plugins)."""
    all_types = {**_BUILTIN_CHANNELS, **_custom_channels, **_discover_entrypoint_channels()}
    return sorted(all_types)


def create_channel(
    channel_type: str,
    agent_name: str,
    config: ChannelConfig,
    router: Router,
) -> Channel:
    """Create a channel adapter by type name.

    Resolution order:
    1. Built-in channels (telegram, webhook)
    2. Channels registered via :func:`register_channel`
    3. Channels discovered via ``smolclaw.channels`` entry points
    """
    cls = _BUILTIN_CHANNELS.get(channel_type)
    if not cls:
        cls = _custom_channels.get(channel_type)
    if not cls:
        # Try entry-point discovery as last resort
        ep_channels = _discover_entrypoint_channels()
        cls = ep_channels.get(channel_type)
    if not cls:
        available = list_channel_types()
        raise ValueError(f"Unknown channel type: {channel_type}. Available: {available}")
    return cls(agent_name, config, router)
