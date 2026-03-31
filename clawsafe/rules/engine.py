"""
Rule Engine — the heart of ClawSafe.

Evaluates ToolCalls against an ordered list of rules.
Default rules run first, then user-defined rules.

Design principles:
1. Rules are pure Python functions — no side effects
2. First non-None result wins — evaluation stops at the first matching rule
3. Default is ALLOW — if no rule matches, the action is permitted
4. Fail safe — if a rule raises an exception, default to BLOCK
5. Config overrides — shell_exec can be enabled via config without editing rules
"""

from __future__ import annotations

import logging
from pathlib import Path

from .default import DEFAULT_RULES
from .loader import load_user_rules
from .models import Decision, ToolCall, Verdict, RuleFunction

logger = logging.getLogger(__name__)


class RuleEngine:
    """Evaluates tool calls against a set of rules."""

    def __init__(self, config_dir: Path, config=None):
        self.config_dir = config_dir
        self.config = config
        self._rules: list[RuleFunction] = []
        self._load_all_rules()

    def _load_all_rules(self) -> None:
        """Load default rules followed by user-defined rules."""
        self._rules = list(DEFAULT_RULES)

        user_rules = load_user_rules(self.config_dir)
        self._rules.extend(user_rules)

        logger.info(
            f"Rule engine initialized: {len(DEFAULT_RULES)} default rules "
            f"+ {len(user_rules)} user rules = {len(self._rules)} total"
        )

    def reload(self) -> None:
        """Reload all rules from disk."""
        self._load_all_rules()
        logger.info(f"Rule engine reloaded: {len(self._rules)} total rules")

    @property
    def rule_count(self) -> int:
        return len(self._rules)

    def evaluate(self, call: ToolCall) -> Decision:
        """
        Evaluate a tool call against all rules in order.
        Returns the first non-None Decision, or ALLOW if no rule matches.
        """
        # Apply config overrides before rule evaluation
        if self.config and getattr(self.config, 'allow_shell_exec', False):
            if call.tool in {
                "exec", "execute", "shell_exec", "shell", "bash", "sh",
                "run_command", "run_script", "terminal"
            }:
                logger.debug(f"Shell exec allowed by config for tool: {call.tool}")
                return Decision.allow()

        for rule in self._rules:
            try:
                result = rule(call.tool, call.arguments)
                if result is not None:
                    logger.debug(
                        f"Rule '{getattr(rule, '__name__', 'unknown')}' matched "
                        f"tool '{call.tool}' -> {result.verdict.value}"
                    )
                    return result
            except Exception as e:
                rule_name = getattr(rule, "__name__", "unknown")
                logger.error(
                    f"Rule '{rule_name}' raised an exception for tool '{call.tool}': {e}. "
                    f"Defaulting to BLOCK."
                )
                return Decision.block(
                    reason=f"Rule error in '{rule_name}': {e}. Blocked for safety.",
                    rule_name=f"rule_error_{rule_name}"
                )

        logger.debug(f"No rule matched tool '{call.tool}' -> ALLOW")
        return Decision.allow()

    def get_rules_summary(self) -> list[dict]:
        """Return metadata about loaded rules for status/doctor commands."""
        return [
            {
                "name": getattr(rule, "__name__", "unknown"),
                "source": "default" if rule in DEFAULT_RULES else "user",
                "docstring": (rule.__doc__ or "").strip().split("\n")[0][:80],
            }
            for rule in self._rules
        ]
