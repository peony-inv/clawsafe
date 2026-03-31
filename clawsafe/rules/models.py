"""
ClawSafe core data models.

These are the fundamental types that flow through the entire system:
ToolCall -> RuleEngine -> Decision -> Proxy -> (forward or block)
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Verdict(str, Enum):
    """The three possible outcomes of rule evaluation."""
    ALLOW = "allow"
    BLOCK = "block"
    GRAY = "gray"


@dataclass
class ToolCall:
    """
    Represents a single tool call intercepted from the OpenClaw agent.

    OpenClaw sends tool calls as JSON-RPC 2.0 over WebSocket:
    {
        "jsonrpc": "2.0",
        "method": "tool/call",
        "params": {
            "tool": "gmail_delete",
            "arguments": {"message_ids": ["id1", "id2", ...]}
        },
        "id": "req_123"
    }
    """
    tool: str
    arguments: dict[str, Any]
    request_id: str
    timestamp: float = field(default_factory=time.time)
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_jsonrpc(cls, message: dict) -> "ToolCall":
        """Parse a JSON-RPC tool call message into a ToolCall."""
        params = message.get("params", {})
        return cls(
            tool=params.get("tool", "unknown"),
            arguments=params.get("arguments", {}),
            request_id=str(message.get("id", uuid.uuid4())),
            raw=message,
        )


@dataclass
class Decision:
    """
    The result of evaluating a ToolCall against the rule engine.

    Produced by: RuleEngine.evaluate()
    Consumed by: ClawSafeProxy._process_tool_call()
    """
    verdict: Verdict
    reason: str = ""
    rule_name: str = ""
    confidence: float = 1.0

    @classmethod
    def allow(cls) -> "Decision":
        return cls(verdict=Verdict.ALLOW)

    @classmethod
    def block(cls, reason: str, rule_name: str = "") -> "Decision":
        return cls(verdict=Verdict.BLOCK, reason=reason, rule_name=rule_name)

    @classmethod
    def gray(cls, reason: str, rule_name: str = "") -> "Decision":
        return cls(verdict=Verdict.GRAY, reason=reason, rule_name=rule_name)

    @property
    def is_allow(self) -> bool:
        return self.verdict == Verdict.ALLOW

    @property
    def is_block(self) -> bool:
        return self.verdict == Verdict.BLOCK

    @property
    def is_gray(self) -> bool:
        return self.verdict == Verdict.GRAY


# Type alias for rule functions.
RuleFunction = Any  # callable[[str, dict], Decision | None]
