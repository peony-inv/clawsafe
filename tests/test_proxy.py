"""Tests for the proxy server routing logic."""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from clawsafe.rules.models import Decision, Verdict


@pytest.mark.asyncio
async def test_proxy_blocks_summer_yue(tmp_path):
    """Integration test: proxy must block the Summer Yue scenario end-to-end."""
    from clawsafe.proxy import ClawSafeProxy
    from clawsafe.config import Config

    config = MagicMock(spec=Config)
    config.config_dir = tmp_path
    config.proxy_port = 18799
    config.openclaw_original_endpoint = "http://localhost:9999"
    config.cloud_enabled = False
    config.hold_timeout_seconds = 60
    config.allow_shell_exec = False

    proxy = ClawSafeProxy(config)
    proxy.audit = AsyncMock()
    proxy.notifier = AsyncMock()

    message = {
        "jsonrpc": "2.0",
        "method": "tool/call",
        "params": {
            "tool": "gmail_delete",
            "arguments": {"message_ids": [f"msg_{i}" for i in range(247)]}
        },
        "id": "req_001"
    }

    response = await proxy._handle_message(json.dumps(message))

    assert "error" in response
    assert "blocked" in response["error"]["message"].lower()
    proxy.notifier.notify_block.assert_called_once()


@pytest.mark.asyncio
async def test_proxy_allows_safe_action(tmp_path):
    """Proxy must forward safe actions without modification."""
    from clawsafe.proxy import ClawSafeProxy
    from clawsafe.config import Config

    config = MagicMock(spec=Config)
    config.config_dir = tmp_path
    config.proxy_port = 18799
    config.openclaw_original_endpoint = "http://localhost:9999"
    config.cloud_enabled = False
    config.hold_timeout_seconds = 60
    config.allow_shell_exec = False

    proxy = ClawSafeProxy(config)
    proxy.audit = AsyncMock()
    proxy.notifier = AsyncMock()

    # Mock the forward call
    proxy._forward_raw = AsyncMock(return_value={"jsonrpc": "2.0", "result": "ok", "id": "req_001"})

    message = {
        "jsonrpc": "2.0",
        "method": "tool/call",
        "params": {
            "tool": "gmail_read",   # Read = safe
            "arguments": {"inbox": "primary"}
        },
        "id": "req_001"
    }

    response = await proxy._handle_message(json.dumps(message))

    assert "error" not in response
    proxy._forward_raw.assert_called_once()
