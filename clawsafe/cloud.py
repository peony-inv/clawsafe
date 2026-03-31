"""
Cloud judgment client.

Sends gray-area tool calls to the ClawSafe cloud API for evaluation by Claude Haiku.

CRITICAL DESIGN RULE — FAIL SAFE:
    If the cloud is unreachable for ANY reason, return BLOCK.
    Never return ALLOW on a cloud failure.
"""

from __future__ import annotations

import logging

import httpx

from .rules.models import Decision, ToolCall, Verdict

logger = logging.getLogger(__name__)

JUDGE_TIMEOUT_SECONDS = 5.0


class CloudJudge:
    """Async HTTP client for the ClawSafe cloud judgment API."""

    def __init__(self, config):
        self.config = config
        self._client = httpx.AsyncClient(
            base_url=config.cloud_endpoint,
            timeout=JUDGE_TIMEOUT_SECONDS,
            headers={
                "Authorization": f"Bearer {config.cloud_api_key}",
                "Content-Type": "application/json",
                "X-ClawSafe-Version": "0.1.0",
            }
        )

    async def judge(self, call: ToolCall) -> Decision:
        """
        Ask Claude Haiku whether this tool call is safe.
        Returns BLOCK on ANY failure.
        """
        try:
            payload = {
                "tool": call.tool,
                "arguments": call.arguments,
                "request_id": call.request_id,
                "user_id": self.config.user_id,
            }

            response = await self._client.post("/judge", json=payload)
            response.raise_for_status()
            data = response.json()

            verdict_str = data.get("verdict", "block").lower()
            if verdict_str not in ("allow", "block", "gray"):
                verdict_str = "block"

            return Decision(
                verdict=Verdict(verdict_str),
                reason=data.get("reason", "cloud judgment"),
                rule_name="cloud_haiku",
                confidence=float(data.get("confidence", 0.5)),
            )

        except httpx.TimeoutException:
            logger.error(
                f"Cloud judge timed out after {JUDGE_TIMEOUT_SECONDS}s "
                f"for tool '{call.tool}' — defaulting to BLOCK"
            )
            return Decision.block(
                reason=f"Cloud judgment timed out ({JUDGE_TIMEOUT_SECONDS}s). Blocked for safety.",
                rule_name="cloud_timeout"
            )

        except httpx.HTTPStatusError as e:
            logger.error(
                f"Cloud judge returned HTTP {e.response.status_code} "
                f"for tool '{call.tool}' — defaulting to BLOCK"
            )
            return Decision.block(
                reason=f"Cloud service error (HTTP {e.response.status_code}). Blocked for safety.",
                rule_name="cloud_http_error"
            )

        except httpx.RequestError as e:
            logger.error(
                f"Cloud judge network error for tool '{call.tool}': {e} — defaulting to BLOCK"
            )
            return Decision.block(
                reason="Cloud service unreachable. Blocked for safety.",
                rule_name="cloud_network_error"
            )

        except Exception as e:
            logger.error(
                f"Cloud judge unexpected error for tool '{call.tool}': {e} — defaulting to BLOCK"
            )
            return Decision.block(
                reason=f"Unexpected cloud error: {type(e).__name__}. Blocked for safety.",
                rule_name="cloud_error"
            )

    async def close(self) -> None:
        await self._client.aclose()
