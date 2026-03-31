"""Tests for the rule engine evaluation logic."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock
from clawsafe.rules.engine import RuleEngine
from clawsafe.rules.models import Decision, ToolCall, Verdict


def make_engine(tmp_path: Path) -> RuleEngine:
    """Create a rule engine with no user rules (clean test environment)."""
    config = MagicMock()
    config.allow_shell_exec = False
    return RuleEngine(config_dir=tmp_path, config=config)


def make_call(tool: str, arguments: dict) -> ToolCall:
    return ToolCall(tool=tool, arguments=arguments, request_id="test-123")


class TestRuleEngine:
    def test_default_is_allow(self, tmp_path):
        engine = make_engine(tmp_path)
        call = make_call("some_unknown_tool", {})
        decision = engine.evaluate(call)
        assert decision.verdict == Verdict.ALLOW

    def test_blocks_summer_yue_scenario(self, tmp_path):
        engine = make_engine(tmp_path)
        call = make_call("gmail_delete", {"message_ids": [f"msg_{i}" for i in range(247)]})
        decision = engine.evaluate(call)
        assert decision.verdict == Verdict.BLOCK

    def test_buggy_rule_defaults_to_block(self, tmp_path):
        """If a rule raises an exception, the engine must BLOCK (not crash or ALLOW)."""
        engine = make_engine(tmp_path)

        def buggy_rule(tool, args):
            raise ValueError("I am a buggy rule")

        engine._rules.insert(0, buggy_rule)
        call = make_call("any_tool", {})
        decision = engine.evaluate(call)
        assert decision.verdict == Verdict.BLOCK

    def test_shell_exec_bypassed_by_config(self, tmp_path):
        config = MagicMock()
        config.allow_shell_exec = True
        engine = RuleEngine(config_dir=tmp_path, config=config)
        call = make_call("bash", {"command": "ls"})
        decision = engine.evaluate(call)
        assert decision.verdict == Verdict.ALLOW

    def test_first_matching_rule_wins(self, tmp_path):
        engine = make_engine(tmp_path)
        calls_count = {"n": 0}

        def rule_a(tool, args):
            calls_count["n"] += 1
            return Decision.block("rule_a fired", "rule_a")

        def rule_b(tool, args):
            calls_count["n"] += 1
            return Decision.block("rule_b fired", "rule_b")

        engine._rules = [rule_a, rule_b]
        call = make_call("test_tool", {})
        decision = engine.evaluate(call)

        assert decision.rule_name == "rule_a"
        assert calls_count["n"] == 1  # rule_b never evaluated
