"""
ClawSafe notification system.

Primary channel: Telegram bot
Fallback: Email via Resend
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


class Notifier:
    def __init__(self, config):
        self.config = config
        self._bot = None
        self._proxy_ref = None

    def set_proxy(self, proxy) -> None:
        """Give notifier a reference to proxy for handling Telegram reply overrides."""
        self._proxy_ref = proxy

    async def initialize(self) -> None:
        """Set up the Telegram bot if configured."""
        if not self.config.telegram_bot_token:
            logger.info("No Telegram bot token configured. Notifications disabled.")
            return

        try:
            from telegram import Bot

            self._bot = Bot(token=self.config.telegram_bot_token)
            bot_info = await self._bot.get_me()
            logger.info(f"Telegram bot connected: @{bot_info.username}")

        except ImportError:
            logger.warning("python-telegram-bot not installed. Run: pip install python-telegram-bot")
        except Exception as e:
            logger.warning(f"Telegram initialization failed: {e}")

    async def notify_block(
        self,
        tool: str,
        arguments: dict,
        decision,
        gray: bool = False,
    ) -> None:
        """Send a block notification."""
        emoji = "\U0001F914" if gray else "\u26D4"
        title = "ClawSafe flagged your agent" if gray else "ClawSafe blocked your agent"
        arg_summary = _summarize_args(arguments)

        message = (
            f"{emoji} *{title}*\n\n"
            f"*Action:* `{tool}`\n"
            f"*Args:* {arg_summary}\n"
            f"*Reason:* {decision.reason}\n"
            f"*Rule:* `{decision.rule_name or 'unknown'}`\n\n"
            f"Your agent has been stopped. No action was taken."
        )

        await self._send(message)

    async def notify_gray_pending(
        self,
        tool: str,
        arguments: dict,
        cloud_decision,
        action_id: str,
        timeout_seconds: int = 60,
    ) -> None:
        """Notify user of a pending gray-area action."""
        arg_summary = _summarize_args(arguments)
        short_id = action_id[:8]

        message = (
            f"\U0001F914 *ClawSafe needs your input*\n\n"
            f"*Action:* `{tool}`\n"
            f"*Args:* {arg_summary}\n"
            f"*Assessment:* {cloud_decision.reason}\n\n"
            f"Waiting *{timeout_seconds}s* for your response.\n"
            f"If no response: action will be *ALLOWED*.\n\n"
            f"Reply:\n"
            f"  `yes` or `allow` \u2014 let it through\n"
            f"  `no` or `deny` \u2014 block it\n\n"
            f"_ID: {short_id}_"
        )

        await self._send(message)

    async def _send(self, message: str) -> None:
        """Try Telegram first, fall back to email."""
        sent = False

        if self._bot and self.config.telegram_chat_id:
            try:
                await self._bot.send_message(
                    chat_id=self.config.telegram_chat_id,
                    text=message,
                    parse_mode="Markdown",
                )
                sent = True
                logger.debug("Telegram notification sent")
            except Exception as e:
                logger.error(f"Telegram send failed: {e}")

        if not sent and self.config.resend_api_key and self.config.notification_email:
            await self._send_email(message)

    async def _send_email(self, message: str) -> None:
        """Send email via Resend as fallback."""
        try:
            import resend
            resend.api_key = self.config.resend_api_key

            plain = message.replace("*", "").replace("`", "").replace("_", "")

            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: resend.Emails.send({
                    "from": "ClawSafe <alerts@clawsafe.dev>",
                    "to": self.config.notification_email,
                    "subject": "\u26D4 ClawSafe blocked your agent",
                    "text": plain,
                })
            )
            logger.debug("Email notification sent")
        except ImportError:
            logger.warning("resend package not installed: pip install resend")
        except Exception as e:
            logger.error(f"Email send failed: {e}")


def _summarize_args(arguments: dict, max_len: int = 80) -> str:
    """Create a short readable summary of tool arguments for notifications."""
    if not arguments:
        return "(none)"

    parts = []
    for key, val in list(arguments.items())[:3]:
        if isinstance(val, list):
            parts.append(f"{key}: [{len(val)} items]")
        elif isinstance(val, str) and len(val) > 40:
            parts.append(f"{key}: '{val[:37]}...'")
        else:
            parts.append(f"{key}: {val!r}")

    summary = ", ".join(parts)
    if len(arguments) > 3:
        summary += f" (+{len(arguments) - 3} more)"

    return summary[:max_len]
