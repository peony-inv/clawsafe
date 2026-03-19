"""Telegram notification integration for ClawSafe."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional, Callable, Awaitable
from enum import Enum

import httpx

from .config import load_config, save_config

logger = logging.getLogger("clawsafe.notify")


class UserResponse(str, Enum):
    """User's response to a notification."""
    ALLOW = "allow"
    BLOCK = "block"
    ALLOW_ALWAYS = "allow_always"
    TIMEOUT = "timeout"


@dataclass
class PendingAction:
    """An action waiting for user response."""
    request_id: str
    tool: str
    arguments: dict
    reason: str
    response: Optional[UserResponse] = None
    responded: bool = False


class TelegramBot:
    """Telegram bot for ClawSafe notifications."""

    API_BASE = "https://api.telegram.org/bot"

    def __init__(self, bot_token: str = "", chat_id: str = ""):
        cfg = load_config()
        self.bot_token = bot_token or cfg.notifications.telegram.bot_token
        self.chat_id = chat_id or cfg.notifications.telegram.chat_id
        self.pending_actions: dict[str, PendingAction] = {}
        self._polling = False
        self._last_update_id = 0

    @property
    def is_configured(self) -> bool:
        """Check if Telegram is configured."""
        return bool(self.bot_token and self.chat_id)

    async def send_message(self, text: str, reply_markup: Optional[dict] = None) -> bool:
        """Send a message to the configured chat."""
        if not self.is_configured:
            logger.warning("Telegram not configured")
            return False

        url = f"{self.API_BASE}{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload)
                return response.status_code == 200
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False

    async def notify_block(self, tool: str, reason: str, arguments: dict) -> bool:
        """Send a block notification."""
        # Summarize arguments
        args_summary = ", ".join(
            f"{k}={_summarize_value(v)}"
            for k, v in list(arguments.items())[:3]
        )

        message = f"""<b>BLOCKED</b> ClawSafe blocked your agent

<b>Action:</b> {tool}
<b>Args:</b> {args_summary}
<b>Rule:</b> {reason}

This action was automatically blocked."""

        return await self.send_message(message)

    async def notify_gray(
        self,
        request_id: str,
        tool: str,
        reason: str,
        arguments: dict,
        timeout_seconds: int = 60,
    ) -> UserResponse:
        """Send a gray notification and wait for user response.

        Returns the user's response or TIMEOUT if no response within timeout.
        """
        # Summarize arguments
        args_summary = ", ".join(
            f"{k}={_summarize_value(v)}"
            for k, v in list(arguments.items())[:3]
        )

        message = f"""<b>REVIEW NEEDED</b> ClawSafe needs your input

<b>Action:</b> {tool}
<b>Args:</b> {args_summary}
<b>Reason:</b> {reason}

Waiting {timeout_seconds}s for your response.
If no response: action will be <b>BLOCKED</b>.

Reply with:
• <code>yes</code> - allow this once
• <code>no</code> - block it
• <code>always</code> - add to allowlist"""

        # Create inline keyboard
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "Allow", "callback_data": f"allow:{request_id}"},
                    {"text": "Block", "callback_data": f"block:{request_id}"},
                ],
                [
                    {"text": "Always Allow", "callback_data": f"always:{request_id}"},
                ]
            ]
        }

        # Register pending action
        pending = PendingAction(
            request_id=request_id,
            tool=tool,
            arguments=arguments,
            reason=reason,
        )
        self.pending_actions[request_id] = pending

        # Send message
        if not await self.send_message(message, reply_markup=keyboard):
            del self.pending_actions[request_id]
            return UserResponse.TIMEOUT

        # Wait for response with polling
        try:
            response = await asyncio.wait_for(
                self._wait_for_response(request_id),
                timeout=timeout_seconds
            )
            return response
        except asyncio.TimeoutError:
            # Send timeout message
            await self.send_message(
                f"<b>TIMEOUT</b> No response for {tool} - action blocked."
            )
            return UserResponse.TIMEOUT
        finally:
            self.pending_actions.pop(request_id, None)

    async def _wait_for_response(self, request_id: str) -> UserResponse:
        """Poll for a response to a specific request."""
        while True:
            pending = self.pending_actions.get(request_id)
            if pending and pending.responded:
                return pending.response

            # Poll for updates
            await self._poll_updates()
            await asyncio.sleep(1)

    async def _poll_updates(self):
        """Poll Telegram for updates (button clicks and messages)."""
        if not self.is_configured:
            return

        url = f"{self.API_BASE}{self.bot_token}/getUpdates"
        params = {
            "offset": self._last_update_id + 1,
            "timeout": 1,
        }

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(url, params=params)
                if response.status_code != 200:
                    return

                data = response.json()
                for update in data.get("result", []):
                    self._last_update_id = update["update_id"]
                    await self._handle_update(update)

        except Exception as e:
            logger.debug(f"Poll error: {e}")

    async def _handle_update(self, update: dict):
        """Handle a Telegram update."""
        # Handle callback query (button click)
        if "callback_query" in update:
            callback = update["callback_query"]
            data = callback.get("data", "")

            if ":" in data:
                action, request_id = data.split(":", 1)

                if request_id in self.pending_actions:
                    pending = self.pending_actions[request_id]

                    if action == "allow":
                        pending.response = UserResponse.ALLOW
                    elif action == "block":
                        pending.response = UserResponse.BLOCK
                    elif action == "always":
                        pending.response = UserResponse.ALLOW_ALWAYS

                    pending.responded = True

                    # Acknowledge the callback
                    await self._answer_callback(callback["id"], f"Got it: {action}")

        # Handle text message
        elif "message" in update:
            message = update["message"]
            text = message.get("text", "").lower().strip()

            # Find any pending action
            for request_id, pending in self.pending_actions.items():
                if not pending.responded:
                    if text in ("yes", "y", "allow", "ok"):
                        pending.response = UserResponse.ALLOW
                        pending.responded = True
                    elif text in ("no", "n", "block", "deny"):
                        pending.response = UserResponse.BLOCK
                        pending.responded = True
                    elif text in ("always", "allowlist"):
                        pending.response = UserResponse.ALLOW_ALWAYS
                        pending.responded = True
                    break

    async def _answer_callback(self, callback_id: str, text: str):
        """Answer a callback query."""
        url = f"{self.API_BASE}{self.bot_token}/answerCallbackQuery"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(url, json={
                    "callback_query_id": callback_id,
                    "text": text,
                })
        except Exception:
            pass

    async def test_connection(self) -> tuple[bool, str]:
        """Test the Telegram bot connection."""
        if not self.bot_token:
            return False, "No bot token configured"

        url = f"{self.API_BASE}{self.bot_token}/getMe"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    data = response.json()
                    bot_name = data.get("result", {}).get("username", "unknown")
                    return True, f"Connected to @{bot_name}"
                else:
                    return False, f"API error: {response.status_code}"
        except Exception as e:
            return False, f"Connection error: {e}"


def _summarize_value(v) -> str:
    """Summarize a value for display."""
    if isinstance(v, list):
        return f"[{len(v)} items]"
    elif isinstance(v, str) and len(v) > 20:
        return v[:17] + "..."
    else:
        return str(v)


# Singleton instance
_bot: Optional[TelegramBot] = None


def get_bot() -> TelegramBot:
    """Get the Telegram bot instance."""
    global _bot
    if _bot is None:
        _bot = TelegramBot()
    return _bot
