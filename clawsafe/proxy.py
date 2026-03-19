"""WebSocket and HTTP proxy server for ClawSafe."""

import asyncio
import json
import logging
import uuid
from typing import Any, Callable, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import JSONResponse
import httpx
import uvicorn

from .rules import RuleEngine, RuleConfig, ToolCall, Verdict
from .audit import AuditStore
from .config import load_config
from .notify import TelegramBot, UserResponse

logger = logging.getLogger("clawsafe")


class JSONRPCError:
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603
    BLOCKED = -32000
    GRAY = -32001


def make_error_response(id: Any, code: int, message: str, data: Any = None) -> dict:
    """Create a JSON-RPC error response."""
    error = {"code": code, "message": message}
    if data:
        error["data"] = data
    return {"jsonrpc": "2.0", "error": error, "id": id}


def make_success_response(id: Any, result: Any) -> dict:
    """Create a JSON-RPC success response."""
    return {"jsonrpc": "2.0", "result": result, "id": id}


class ClawSafeProxy:
    """The main proxy server that intercepts tool calls."""

    def __init__(
        self,
        port: int = 18790,
        rule_config: Optional[RuleConfig] = None,
        target_endpoint: str = "",
        on_block: Optional[Callable[[str, str], None]] = None,
    ):
        self.port = port
        self.engine = RuleEngine(rule_config)
        self.store = AuditStore()
        self.target_endpoint = target_endpoint
        self.on_block = on_block
        self.http_client: Optional[httpx.AsyncClient] = None

        # Load config for notifications
        self.config = load_config()
        self.telegram_bot = TelegramBot()
        self.hold_timeout = self.config.proxy.hold_timeout_seconds

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            self.http_client = httpx.AsyncClient(timeout=30.0)
            yield
            await self.http_client.aclose()
            self.store.close()

        self.app = FastAPI(lifespan=lifespan)
        self._setup_routes()

    def _setup_routes(self):
        """Set up FastAPI routes."""

        @self.app.get("/health")
        async def health():
            return {"status": "ok"}

        @self.app.post("/")
        async def handle_http(request: Request):
            body = await request.body()
            response = await self._process_message(body)
            return JSONResponse(content=response)

        @self.app.websocket("/")
        async def handle_websocket(websocket: WebSocket):
            await websocket.accept()
            try:
                while True:
                    message = await websocket.receive_text()
                    response = await self._process_message(message.encode())
                    await websocket.send_text(json.dumps(response))
            except WebSocketDisconnect:
                pass

    async def _process_message(self, message: bytes) -> dict:
        """Process a JSON-RPC message and return response."""
        try:
            req = json.loads(message)
        except json.JSONDecodeError:
            return make_error_response(None, JSONRPCError.PARSE_ERROR, "Parse error")

        req_id = req.get("id")
        method = req.get("method", "")

        # Only intercept tool/call requests
        if method != "tool/call":
            return await self._forward_request(req)

        params = req.get("params", {})
        tool = params.get("tool", "")
        arguments = params.get("arguments", {})

        # Evaluate against rules
        call = ToolCall(tool=tool, arguments=arguments)
        decision = self.engine.evaluate(call)

        if decision.verdict == Verdict.BLOCK:
            # Log and return block
            self.store.log_event(
                tool=tool,
                arguments=arguments,
                verdict="block",
                rule=decision.rule,
                reason=decision.reason,
            )

            logger.warning(f"BLOCKED: {tool} - {decision.reason}")
            if self.on_block:
                self.on_block(tool, decision.reason)

            # Send Telegram notification (fire and forget)
            if self.telegram_bot.is_configured:
                asyncio.create_task(
                    self.telegram_bot.notify_block(tool, decision.reason, arguments)
                )

            return make_error_response(
                req_id,
                JSONRPCError.BLOCKED,
                f"ClawSafe blocked: {decision.reason}",
                {"verdict": "block", "rule": decision.rule}
            )

        elif decision.verdict == Verdict.GRAY:
            # Handle gray area - needs human approval via Telegram
            return await self._handle_gray(
                req_id, tool, arguments, decision.rule, decision.reason
            )

        else:
            # ALLOW - log and forward
            self.store.log_event(
                tool=tool,
                arguments=arguments,
                verdict="allow",
                rule=decision.rule,
                reason=decision.reason,
            )
            logger.info(f"ALLOWED: {tool}")
            return await self._forward_request(req)

    async def _handle_gray(
        self,
        req_id: Any,
        tool: str,
        arguments: dict,
        rule: str,
        reason: str,
    ) -> dict:
        """Handle a gray area decision - get human approval via Telegram."""
        request_id = str(uuid.uuid4())[:8]
        logger.warning(f"GRAY: {tool} - {reason} (request_id={request_id})")

        final_verdict = "block"
        final_reason = reason

        # Try Telegram notification (human in the loop)
        if self.telegram_bot.is_configured:
            if self.on_block:
                self.on_block(tool, f"GRAY: {reason} - waiting for approval...")

            user_response = await self.telegram_bot.notify_gray(
                request_id=request_id,
                tool=tool,
                reason=reason,
                arguments=arguments,
                timeout_seconds=self.hold_timeout,
            )

            if user_response == UserResponse.ALLOW:
                final_verdict = "allow"
                final_reason = "approved by user"
            elif user_response == UserResponse.ALLOW_ALWAYS:
                final_verdict = "allow"
                final_reason = "approved by user (added to allowlist)"
                # Add to allowlist
                self.store.add_to_allowlist(tool)
            elif user_response == UserResponse.BLOCK:
                final_verdict = "block"
                final_reason = "blocked by user"
            else:  # TIMEOUT
                final_verdict = "block"
                final_reason = "no response - blocked for safety"

        else:
            # No Telegram configured - block for safety
            final_verdict = "block"
            final_reason = "gray area - blocked (Telegram not configured)"
            if self.on_block:
                self.on_block(tool, final_reason)

        # Log the decision
        self.store.log_event(
            tool=tool,
            arguments=arguments,
            verdict=final_verdict,
            rule=rule,
            reason=final_reason,
        )

        if final_verdict == "allow":
            logger.info(f"GRAY->ALLOW: {tool} - {final_reason}")
            return await self._forward_request({
                "jsonrpc": "2.0",
                "method": "tool/call",
                "params": {"tool": tool, "arguments": arguments},
                "id": req_id,
            })
        else:
            logger.warning(f"GRAY->BLOCK: {tool} - {final_reason}")
            if self.on_block:
                self.on_block(tool, final_reason)

            return make_error_response(
                req_id,
                JSONRPCError.GRAY,
                f"ClawSafe blocked: {final_reason}",
                {"verdict": "block", "rule": rule}
            )

    async def _forward_request(self, req: dict) -> dict:
        """Forward a request to the target endpoint."""
        if not self.target_endpoint:
            return make_success_response(
                req.get("id"),
                {"status": "forwarded (no target configured)"}
            )

        try:
            response = await self.http_client.post(
                self.target_endpoint,
                json=req,
                headers={"Content-Type": "application/json"}
            )
            return response.json()
        except Exception as e:
            return make_error_response(
                req.get("id"),
                JSONRPCError.INTERNAL_ERROR,
                f"Forward error: {str(e)}"
            )

    def run(self):
        """Run the proxy server (blocking)."""
        config = uvicorn.Config(
            self.app,
            host="127.0.0.1",
            port=self.port,
            log_level="info",
        )
        server = uvicorn.Server(config)
        server.run()

    async def start_async(self):
        """Start the proxy server asynchronously."""
        config = uvicorn.Config(
            self.app,
            host="127.0.0.1",
            port=self.port,
            log_level="info",
        )
        server = uvicorn.Server(config)
        await server.serve()
