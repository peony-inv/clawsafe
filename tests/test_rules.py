"""
Tests for the default rule set.
These are the core safety properties that must hold.
"""

import pytest
from clawsafe.rules.default import (
    bulk_delete_rule, query_delete_rule, bulk_send_block_rule,
    shell_exec_rule, recursive_file_rule, payment_rule,
    public_post_rule, multi_recipient_send_gray_rule,
)
from clawsafe.rules.models import Verdict


class TestBulkDeleteRule:
    def test_blocks_above_limit(self):
        d = bulk_delete_rule("gmail_delete", {"message_ids": ["id"] * 247})
        assert d is not None
        assert d.verdict == Verdict.BLOCK
        assert "247" in d.reason

    def test_allows_below_limit(self):
        d = bulk_delete_rule("gmail_delete", {"message_ids": ["id"] * 5})
        assert d is None  # No opinion — pass through

    def test_blocks_exactly_at_limit_plus_one(self):
        d = bulk_delete_rule("gmail_delete", {"message_ids": ["id"] * 11})
        assert d is not None
        assert d.verdict == Verdict.BLOCK

    def test_allows_at_exact_limit(self):
        d = bulk_delete_rule("gmail_delete", {"message_ids": ["id"] * 10})
        assert d is None

    def test_ignores_non_delete_tools(self):
        d = bulk_delete_rule("gmail_send", {"message_ids": ["id"] * 247})
        assert d is None

    def test_summer_yue_scenario(self):
        """The exact scenario from the Summer Yue incident."""
        d = bulk_delete_rule("gmail_delete", {"message_ids": [f"msg_{i}" for i in range(247)]})
        assert d is not None
        assert d.verdict == Verdict.BLOCK
        assert d.rule_name == "bulk_delete"

    def test_works_with_ids_field(self):
        d = bulk_delete_rule("file_delete", {"ids": ["f"] * 50})
        assert d is not None
        assert d.verdict == Verdict.BLOCK


class TestQueryDeleteRule:
    def test_blocks_query_without_ids(self):
        d = query_delete_rule("gmail_delete", {"query": "older_than:7d"})
        assert d is not None
        assert d.verdict == Verdict.BLOCK

    def test_allows_query_with_explicit_ids(self):
        d = query_delete_rule("gmail_delete", {
            "query": "older_than:7d",
            "message_ids": ["id1", "id2"]
        })
        assert d is None

    def test_ignores_non_delete_tools(self):
        d = query_delete_rule("gmail_search", {"query": "older_than:7d"})
        assert d is None


class TestBulkSendRule:
    def test_blocks_above_limit(self):
        d = bulk_send_block_rule("send_message", {"recipients": ["a"] * 6})
        assert d is not None
        assert d.verdict == Verdict.BLOCK

    def test_allows_single_recipient(self):
        d = bulk_send_block_rule("send_message", {"recipients": ["alice@example.com"]})
        assert d is None

    def test_chris_boyd_scenario(self):
        """500 iMessages to random contacts."""
        d = bulk_send_block_rule("imessage_send", {"recipients": [f"+1555{i:07d}" for i in range(500)]})
        assert d is not None
        assert d.verdict == Verdict.BLOCK


class TestMultiRecipientGray:
    def test_grays_2_to_5_recipients(self):
        for n in [2, 3, 4, 5]:
            d = multi_recipient_send_gray_rule("send_email", {"to": ["a"] * n})
            assert d is not None, f"Expected GRAY for {n} recipients"
            assert d.verdict == Verdict.GRAY

    def test_no_opinion_on_single_recipient(self):
        d = multi_recipient_send_gray_rule("send_email", {"to": ["alice@example.com"]})
        assert d is None


class TestShellExecRule:
    def test_blocks_bash(self):
        d = shell_exec_rule("bash", {"command": "rm -rf /"})
        assert d is not None
        assert d.verdict == Verdict.BLOCK

    def test_blocks_exec(self):
        d = shell_exec_rule("exec", {"cmd": "anything"})
        assert d is not None
        assert d.verdict == Verdict.BLOCK

    def test_allows_other_tools(self):
        d = shell_exec_rule("gmail_read", {})
        assert d is None


class TestPaymentRule:
    def test_blocks_all_payment_tools(self):
        for tool in ["purchase", "pay", "checkout", "stripe_charge"]:
            d = payment_rule(tool, {"amount": 99.99})
            assert d is not None
            assert d.verdict == Verdict.BLOCK, f"Expected BLOCK for {tool}"


class TestPublicPostRule:
    def test_blocks_tweet(self):
        d = public_post_rule("tweet", {"text": "hello world"})
        assert d is not None
        assert d.verdict == Verdict.BLOCK
