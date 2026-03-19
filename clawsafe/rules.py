"""Rule engine for ClawSafe - pure Python implementation with YAML custom rules."""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
from pathlib import Path

import yaml

from .config import config_dir


class Verdict(str, Enum):
    ALLOW = "allow"
    BLOCK = "block"
    GRAY = "gray"


@dataclass
class Decision:
    verdict: Verdict
    reason: str
    rule: str = ""


@dataclass
class ToolCall:
    tool: str
    arguments: dict[str, Any]


@dataclass
class RuleConfig:
    bulk_delete_limit: int = 10
    bulk_send_limit: int = 5
    allow_shell_exec: bool = False


@dataclass
class CustomRule:
    """A user-defined rule from YAML."""
    name: str
    tools: list[str]  # Tools to match (empty = all)
    conditions: dict[str, Any]  # Conditions on arguments
    action: Verdict
    reason: str
    enabled: bool = True
    priority: int = 0  # Higher = checked first

    def matches(self, call: ToolCall) -> bool:
        """Check if this rule matches the tool call."""
        # Check tool match
        if self.tools and call.tool not in self.tools:
            return False

        # Check argument conditions
        for arg_path, condition in self.conditions.items():
            value = self._get_nested_value(call.arguments, arg_path)
            if not self._check_condition(value, condition):
                return False

        return True

    def _get_nested_value(self, obj: dict, path: str) -> Any:
        """Get a nested value from a dict using dot notation."""
        parts = path.split(".")
        current = obj
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
        return current

    def _check_condition(self, value: Any, condition: Any) -> bool:
        """Check if a value matches a condition."""
        # Direct equality
        if not isinstance(condition, dict):
            return value == condition

        # Operator-based conditions
        for op, expected in condition.items():
            if op == "equals":
                if value != expected:
                    return False
            elif op == "not_equals":
                if value == expected:
                    return False
            elif op == "contains":
                if not isinstance(value, str) or expected not in value:
                    return False
            elif op == "not_contains":
                if isinstance(value, str) and expected in value:
                    return False
            elif op == "startswith":
                if not isinstance(value, str) or not value.startswith(expected):
                    return False
            elif op == "endswith":
                if not isinstance(value, str) or not value.endswith(expected):
                    return False
            elif op == "matches":
                if not isinstance(value, str) or not re.search(expected, value):
                    return False
            elif op == "gt":
                if not isinstance(value, (int, float)) or value <= expected:
                    return False
            elif op == "gte":
                if not isinstance(value, (int, float)) or value < expected:
                    return False
            elif op == "lt":
                if not isinstance(value, (int, float)) or value >= expected:
                    return False
            elif op == "lte":
                if not isinstance(value, (int, float)) or value > expected:
                    return False
            elif op == "in":
                if value not in expected:
                    return False
            elif op == "not_in":
                if value in expected:
                    return False
            elif op == "exists":
                if expected and value is None:
                    return False
                if not expected and value is not None:
                    return False
            elif op == "length_gt":
                if not hasattr(value, "__len__") or len(value) <= expected:
                    return False
            elif op == "length_lt":
                if not hasattr(value, "__len__") or len(value) >= expected:
                    return False

        return True


def rules_file_path() -> Path:
    """Get the path to the custom rules file."""
    return config_dir() / "rules.yaml"


def load_custom_rules() -> list[CustomRule]:
    """Load custom rules from the YAML file."""
    path = rules_file_path()
    if not path.exists():
        return []

    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        return []

    rules = []
    for rule_data in data.get("rules", []):
        try:
            # Parse tools - can be string or list
            tools = rule_data.get("match", {}).get("tools", [])
            if isinstance(tools, str):
                tools = [tools]

            # Parse action
            action_str = rule_data.get("action", "block").lower()
            action = Verdict(action_str)

            rules.append(CustomRule(
                name=rule_data.get("name", "unnamed"),
                tools=tools,
                conditions=rule_data.get("match", {}).get("arguments", {}),
                action=action,
                reason=rule_data.get("reason", "custom rule triggered"),
                enabled=rule_data.get("enabled", True),
                priority=rule_data.get("priority", 0),
            ))
        except Exception:
            continue  # Skip invalid rules

    # Sort by priority (higher first)
    rules.sort(key=lambda r: r.priority, reverse=True)
    return rules


def save_custom_rules(rules: list[CustomRule]) -> None:
    """Save custom rules to the YAML file."""
    path = rules_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    rules_data = []
    for rule in rules:
        rule_dict = {
            "name": rule.name,
            "match": {},
            "action": rule.action.value,
            "reason": rule.reason,
            "enabled": rule.enabled,
        }
        if rule.tools:
            rule_dict["match"]["tools"] = rule.tools
        if rule.conditions:
            rule_dict["match"]["arguments"] = rule.conditions
        if rule.priority != 0:
            rule_dict["priority"] = rule.priority
        rules_data.append(rule_dict)

    with open(path, "w") as f:
        yaml.dump({"rules": rules_data}, f, default_flow_style=False, sort_keys=False)


def add_custom_rule(rule: CustomRule) -> None:
    """Add a new custom rule."""
    rules = load_custom_rules()
    # Remove existing rule with same name
    rules = [r for r in rules if r.name != rule.name]
    rules.append(rule)
    save_custom_rules(rules)


def remove_custom_rule(name: str) -> bool:
    """Remove a custom rule by name. Returns True if removed."""
    rules = load_custom_rules()
    new_rules = [r for r in rules if r.name != name]
    if len(new_rules) == len(rules):
        return False
    save_custom_rules(new_rules)
    return True


def set_rule_enabled(name: str, enabled: bool) -> bool:
    """Enable or disable a rule. Returns True if found."""
    rules = load_custom_rules()
    for rule in rules:
        if rule.name == name:
            rule.enabled = enabled
            save_custom_rules(rules)
            return True
    return False


class RuleEngine:
    """Pure Python rule engine for evaluating tool calls."""

    # Tools that perform deletions
    DELETE_TOOLS = {"gmail_delete", "file_delete", "message_delete", "calendar_delete"}

    # Tools that send messages
    SEND_TOOLS = {"send_message", "send_email", "imessage_send"}

    # Tools that execute shell commands
    SHELL_TOOLS = {"exec", "shell_exec", "bash", "run_command", "terminal"}

    # Tools that perform file operations
    FILE_TOOLS = {"file_delete", "file_move"}

    # Tools that perform payments
    PAYMENT_TOOLS = {"purchase", "pay", "checkout", "stripe_charge"}

    def __init__(self, config: Optional[RuleConfig] = None, load_custom: bool = True):
        self.config = config or RuleConfig()
        self.user_home = str(Path.home())
        self.custom_rules: list[CustomRule] = []
        if load_custom:
            self.reload_custom_rules()

    def reload_custom_rules(self):
        """Reload custom rules from disk."""
        self.custom_rules = load_custom_rules()

    def evaluate(self, call: ToolCall) -> Decision:
        """Evaluate a tool call against all rules.

        Order: custom rules (by priority), then built-in deny, then built-in gray, then allow.
        """
        # Check custom rules first (they take precedence)
        if decision := self._check_custom_rules(call):
            return decision

        # Check built-in deny rules
        if decision := self._check_deny_rules(call):
            return decision

        # Check built-in gray rules
        if decision := self._check_gray_rules(call):
            return decision

        # Default: allow
        return Decision(
            verdict=Verdict.ALLOW,
            reason="no rules triggered",
            rule=""
        )

    def _check_custom_rules(self, call: ToolCall) -> Optional[Decision]:
        """Check custom YAML rules."""
        for rule in self.custom_rules:
            if not rule.enabled:
                continue
            if rule.matches(call):
                return Decision(
                    verdict=rule.action,
                    reason=rule.reason,
                    rule=f"custom:{rule.name}"
                )
        return None

    def _check_deny_rules(self, call: ToolCall) -> Optional[Decision]:
        """Check all built-in deny rules."""

        # Rule 1: Bulk delete
        if call.tool in self.DELETE_TOOLS:
            ids = call.arguments.get("ids", [])
            if isinstance(ids, list) and len(ids) > self.config.bulk_delete_limit:
                return Decision(
                    verdict=Verdict.BLOCK,
                    reason=f"bulk delete blocked: {len(ids)} items exceeds limit of {self.config.bulk_delete_limit}",
                    rule="builtin:bulk_delete"
                )

        # Rule 2: Query-based delete
        if call.tool == "gmail_delete":
            query = call.arguments.get("query", "")
            ids = call.arguments.get("ids")
            if query and not ids:
                return Decision(
                    verdict=Verdict.BLOCK,
                    reason="query-based delete blocked: unknown number of items affected",
                    rule="builtin:query_delete"
                )

        # Rule 3: Bulk send
        if call.tool in self.SEND_TOOLS:
            recipients = call.arguments.get("recipients", [])
            if isinstance(recipients, list) and len(recipients) > self.config.bulk_send_limit:
                return Decision(
                    verdict=Verdict.BLOCK,
                    reason=f"bulk send blocked: {len(recipients)} recipients exceeds limit of {self.config.bulk_send_limit}",
                    rule="builtin:bulk_send"
                )

        # Rule 4: Shell execution
        if call.tool in self.SHELL_TOOLS:
            if not self.config.allow_shell_exec:
                return Decision(
                    verdict=Verdict.BLOCK,
                    reason="shell execution requires explicit --allow-exec flag",
                    rule="builtin:shell_exec"
                )

        # Rule 5: Recursive file operations
        if call.tool in self.FILE_TOOLS:
            if call.arguments.get("recursive", False):
                return Decision(
                    verdict=Verdict.BLOCK,
                    reason="recursive file operation blocked",
                    rule="builtin:recursive_file_op"
                )

        # Rule 6: Payment actions
        if call.tool in self.PAYMENT_TOOLS:
            return Decision(
                verdict=Verdict.BLOCK,
                reason="payment actions require explicit human approval",
                rule="builtin:payment"
            )

        return None

    def _check_gray_rules(self, call: ToolCall) -> Optional[Decision]:
        """Check built-in gray area rules."""

        # Gray 1: Multiple recipients (but within limit)
        if call.tool in self.SEND_TOOLS:
            recipients = call.arguments.get("recipients", [])
            if isinstance(recipients, list):
                count = len(recipients)
                if 1 < count <= self.config.bulk_send_limit:
                    return Decision(
                        verdict=Verdict.GRAY,
                        reason="sending to multiple recipients - verifying intent",
                        rule="builtin:multiple_recipients"
                    )

        # Gray 2: File writes outside home directory
        if call.tool == "file_write":
            path = call.arguments.get("path", "")
            if path and not path.startswith(self.user_home):
                return Decision(
                    verdict=Verdict.GRAY,
                    reason="writing outside home directory - verifying intent",
                    rule="builtin:outside_home"
                )

        return None


# Built-in rules metadata for display
BUILTIN_RULES = [
    {
        "name": "bulk_delete",
        "type": "block",
        "description": "Block bulk deletions exceeding limit",
        "tools": ["gmail_delete", "file_delete", "message_delete", "calendar_delete"],
    },
    {
        "name": "query_delete",
        "type": "block",
        "description": "Block query-based deletions (unknown item count)",
        "tools": ["gmail_delete"],
    },
    {
        "name": "bulk_send",
        "type": "block",
        "description": "Block bulk sends exceeding recipient limit",
        "tools": ["send_message", "send_email", "imessage_send"],
    },
    {
        "name": "shell_exec",
        "type": "block",
        "description": "Block shell command execution",
        "tools": ["exec", "shell_exec", "bash", "run_command", "terminal"],
    },
    {
        "name": "recursive_file_op",
        "type": "block",
        "description": "Block recursive file operations",
        "tools": ["file_delete", "file_move"],
    },
    {
        "name": "payment",
        "type": "block",
        "description": "Block payment/purchase actions",
        "tools": ["purchase", "pay", "checkout", "stripe_charge"],
    },
    {
        "name": "multiple_recipients",
        "type": "gray",
        "description": "Flag sends to multiple recipients for review",
        "tools": ["send_message", "send_email"],
    },
    {
        "name": "outside_home",
        "type": "gray",
        "description": "Flag file writes outside home directory",
        "tools": ["file_write"],
    },
]
