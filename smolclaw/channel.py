"""Channel adapters — normalize messages from platforms and route to agents."""

from __future__ import annotations

import asyncio
import html
import logging
import os
import re
from abc import ABC, abstractmethod
from pathlib import Path

from .config import AgentInfo, ChannelConfig
from .router import InboundMessage, OutboundMessage, Router

log = logging.getLogger("smolclaw")


class Channel(ABC):
    """Base class for messaging channel adapters."""

    channel_type: str = "base"

    def __init__(self, agent_name: str, config: ChannelConfig, router: Router):
        self.agent_name = agent_name
        self.config = config
        self.router = router

    @abstractmethod
    async def start(self):
        """Start listening for messages."""

    @abstractmethod
    async def stop(self):
        """Stop the channel."""

    @abstractmethod
    async def send(self, chat_id: str, text: str):
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
        super().__init__(agent_name, config, router)
        self._app = None
        self._token = os.environ.get(config.token_env, "")
        self._authorized = set(config.authorized_users)

    def _is_authorized(self, user_id: int) -> bool:
        if not self._authorized:
            return True
        return user_id in self._authorized

    async def start(self):
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
                except Exception:
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
            except asyncio.TimeoutError:
                await update.message.reply_text("Request timed out.")
            except Exception as e:
                await update.message.reply_text(f"Error: {e}")
            finally:
                typing_task.cancel()
                try:
                    await typing_task
                except asyncio.CancelledError:
                    pass

        async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not is_auth(update.effective_user.id):
                await update.message.reply_text(f"Unauthorized. Your ID: {update.effective_user.id}")
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

    async def stop(self):
        if self._app:
            log.info(f"[{self.agent_name}] Telegram channel stopping")
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
            self._app = None

    async def send(self, chat_id: str, text: str):
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
            except Exception:
                plain = re.sub(r"<[^>]+>", "", chunk)
                try:
                    await self._app.bot.send_message(chat_id=int(chat_id), text=plain)
                except Exception as e:
                    log.error(f"[{self.agent_name}] Telegram send to {chat_id} failed: {e}")


# --- Channel Factory ---

CHANNEL_TYPES: dict[str, type[Channel]] = {
    "telegram": TelegramChannel,
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
