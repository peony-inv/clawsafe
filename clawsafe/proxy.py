"""
ClawSafe Proxy Server.

Listens on localhost:18790 (WebSocket only — never 0.0.0.0).
Intercepts, evaluates, and either forwards or blocks each tool call.

GRAY handling:
  Free tier: immediately BLOCK
  Paid tier: ask cloud judge -> if BLOCK, block. If ALLOW, hold 60s for user override.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

import httpx
import websockets
import websockets.server

from .audit import AuditLog
from .cloud import CloudJudge
from .config import Config
from .notify import Notifier
from .rules.engine import RuleEngine
from .rules.models import Decision, ToolCall, Verdict

logger = logging.getLogger(__name__)


class ClawSafeProxy:

    def __init__(self, config: Config):
        self.config = config
        self.rule_engine = RuleEngine(config.config_dir, config)
        self.audit = AuditLog(config.config_dir / "audit.db")
        self.notifier = Notifier(config)
        self.cloud_judge = CloudJudge(config) if config.cloud_enabled else None
        self._forward_client = httpx.AsyncClient(timeout=30.0)

        # Pending GRAY actions awaiting user override
        self._pending: dict[str, asyncio.Future] = {}

        self.notifier.set_proxy(self)

    async def start(self) -> None:
        """Initialize all components and start the WebSocket server."""
        await self.audit.initialize()
        await self.notifier.initialize()

        logger.info(f"ClawSafe proxy starting on localhost:{self.config.proxy_port}")
        logger.info(f"Rule engine: {self.rule_engine.rule_count} rules loaded")
        logger.info(f"Cloud judge: {'enabled' if self.cloud_judge else 'disabled (free tier)'}")

        async with websockets.server.serve(
            self._handle_connection,
            "127.0.0.1",
            self.config.proxy_port,
            ping_interval=30,
            ping_timeout=10,
        ):
            logger.info(f"ClawSafe proxy listening on ws://127.0.0.1:{self.config.proxy_port}")
            await asyncio.Future()  # Run forever

    async def _handle_connection(self, websocket: websockets.server.WebSocketServerProtocol) -> None:
        """Handle one WebSocket connection from OpenClaw."""
        logger.info(f"OpenClaw connected from {websocket.remote_address}")
        try:
            async for raw_message in websocket:
                try:
                    response = await self._handle_message(str(raw_message))
                    await websocket.send(json.dumps(response))
                except Exception as e:
                    logger.error(f"Error handling message: {e}")
                    error_resp = self._make_error(None, f"ClawSafe internal error: {e}")
                    await websocket.send(json.dumps(error_resp))
        except websockets.exceptions.ConnectionClosed:
            logger.info("OpenClaw disconnected")

    async def _handle_message(self, raw: str) -> dict[str, Any]:
        """Parse and route a single message."""
        try:
            message = json.loads(raw)
        except json.JSONDecodeError as e:
            return self._make_error(None, f"Invalid JSON from agent: {e}")

        if message.get("method") != "tool/call":
            return await self._forward_raw(message)

        try:
            call = ToolCall.from_jsonrpc(message)
        except Exception as e:
            return self._make_error(message.get("id"), f"Invalid tool call format: {e}")

        return await self._process_tool_call(call)

    async def _process_tool_call(self, call: ToolCall) -> dict[str, Any]:
        """Main decision routing for a single tool call."""
        decision = self.rule_engine.evaluate(call)

        if decision.verdict == Verdict.ALLOW:
            await self.audit.log_event(
                tool=call.tool,
                arguments=call.arguments,
                verdict="allow",
                rule_name=decision.rule_name,
                reason=decision.reason,
            )
            return await self._forward_raw(call.raw)

        if decision.verdict == Verdict.BLOCK:
            await self.audit.log_event(
                tool=call.tool,
                arguments=call.arguments,
                verdict="block",
                rule_name=decision.rule_name,
                reason=decision.reason,
            )
            await self.notifier.notify_block(call.tool, call.arguments, decision)
            return self._make_error(
                call.request_id,
                f"ClawSafe blocked: {decision.reason}"
            )

        if decision.verdict == Verdict.GRAY:
            return await self._handle_gray(call, decision)

        return self._make_error(call.request_id, "ClawSafe: unknown verdict")

    async def _handle_gray(self, call: ToolCall, initial_decision: Decision) -> dict[str, Any]:
        """Handle a GRAY (ambiguous) action."""
        if not self.cloud_judge:
            # Free tier: gray area defaults to BLOCK
            block_decision = Decision.block(
                reason=(
                    f"{initial_decision.reason} "
                    "(Upgrade to Shell plan for AI-assisted gray area judgment)"
                ),
                rule_name=initial_decision.rule_name
            )
            await self.audit.log_event(
                tool=call.tool,
                arguments=call.arguments,
                verdict="block",
                rule_name=block_decision.rule_name,
                reason=block_decision.reason,
            )
            await self.notifier.notify_block(call.tool, call.arguments, block_decision, gray=True)
            return self._make_error(call.request_id, block_decision.reason)

        # Paid tier: consult cloud judge
        cloud_decision = await self.cloud_judge.judge(call)

        if cloud_decision.verdict == Verdict.BLOCK:
            await self.audit.log_event(
                tool=call.tool,
                arguments=call.arguments,
                verdict="block",
                rule_name=cloud_decision.rule_name,
                reason=cloud_decision.reason,
                cloud_used=True,
            )
            await self.notifier.notify_block(call.tool, call.arguments, cloud_decision, gray=True)
            return self._make_error(call.request_id, cloud_decision.reason)

        # Cloud says ALLOW — give user 60s to override
        action_id = str(uuid.uuid4())
        loop = asyncio.get_event_loop()
        future: asyncio.Future[str] = loop.create_future()
        self._pending[action_id] = future

        try:
            await self.notifier.notify_gray_pending(
                tool=call.tool,
                arguments=call.arguments,
                cloud_decision=cloud_decision,
                action_id=action_id,
                timeout_seconds=self.config.hold_timeout_seconds,
            )

            try:
                user_override = await asyncio.wait_for(
                    future,
                    timeout=float(self.config.hold_timeout_seconds)
                )
            except asyncio.TimeoutError:
                user_override = "allow"
                logger.info(
                    f"Gray action {action_id[:8]} timed out — defaulting to ALLOW (cloud said OK)"
                )

        finally:
            self._pending.pop(action_id, None)

        if user_override == "allow":
            await self.audit.log_event(
                tool=call.tool,
                arguments=call.arguments,
                verdict="allow",
                rule_name=cloud_decision.rule_name,
                reason="Cloud: OK, user: no response (timeout) / allowed",
                cloud_used=True,
            )
            return await self._forward_raw(call.raw)
        else:
            deny_decision = Decision.block(
                reason="User denied via phone override",
                rule_name="user_override"
            )
            await self.audit.log_event(
                tool=call.tool,
                arguments=call.arguments,
                verdict="block",
                rule_name=deny_decision.rule_name,
                reason=deny_decision.reason,
                cloud_used=True,
                overridden=True,
            )
            return self._make_error(call.request_id, deny_decision.reason)

    async def handle_user_override(self, action_id: str, verdict: str) -> bool:
        """Called by Telegram bot when user replies."""
        future = self._pending.get(action_id)
        if future is None or future.done():
            return False
        future.set_result(verdict)
        return True

    async def _forward_raw(self, message: dict[str, Any]) -> dict[str, Any]:
        """Forward a message to the real OpenClaw endpoint."""
        endpoint = self.config.openclaw_original_endpoint
        if not endpoint:
            return self._make_error(
                message.get("id"),
                "ClawSafe: original endpoint not configured. Run: clawsafe wrap openclaw"
            )

        try:
            response = await self._forward_client.post(
                endpoint,
                json=message,
                headers={"Content-Type": "application/json"},
            )
            return response.json()
        except Exception as e:
            logger.error(f"Forward to {endpoint} failed: {e}")
            return self._make_error(
                message.get("id"),
                f"ClawSafe: failed to forward to OpenClaw endpoint: {e}"
            )

    def _make_error(self, request_id: Any, message: str) -> dict[str, Any]:
        """Create a JSON-RPC 2.0 error response."""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -32000,
                "message": message,
                "data": {"source": "clawsafe"}
            }
        }

    async def cleanup(self) -> None:
        """Graceful shutdown."""
        if self.cloud_judge:
            await self.cloud_judge.close()
        await self._forward_client.aclose()
        await self.audit.close()
