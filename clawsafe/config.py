"""
ClawSafe configuration manager.

Config file location: ~/.clawsafe/config.yaml
Config file permissions: 600 (user read/write only — contains API keys)
"""

from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_CONFIG_DIR = Path.home() / ".clawsafe"
DEFAULT_PROXY_PORT = 18790


@dataclass
class Config:
    config_dir: Path = field(default_factory=lambda: DEFAULT_CONFIG_DIR)

    # Proxy
    proxy_port: int = DEFAULT_PROXY_PORT
    hold_timeout_seconds: int = 60

    # OpenClaw
    openclaw_gateway_config: str = ""
    openclaw_original_endpoint: str = ""

    # Notifications — Telegram
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Notifications — Email
    notification_email: str = ""
    resend_api_key: str = ""

    # Cloud (paid tier)
    cloud_enabled: bool = False
    cloud_api_key: str = ""
    cloud_endpoint: str = "https://api.clawsafe.dev"

    # Rule overrides
    bulk_delete_limit: int = 10
    bulk_send_limit: int = 5
    allow_shell_exec: bool = False

    # Dashboard sync
    dashboard_sync_interval: int = 60
    dashboard_enabled: bool = False

    @classmethod
    def load(cls, config_dir: Path | None = None) -> "Config":
        """Load config from YAML file. Returns default config if file doesn't exist."""
        config_dir = config_dir or DEFAULT_CONFIG_DIR
        config_file = config_dir / "config.yaml"

        if not config_file.exists():
            return cls(config_dir=config_dir)

        with open(config_file) as f:
            data = yaml.safe_load(f) or {}

        def get(path: str, default=None):
            keys = path.split(".")
            val = data
            for key in keys:
                if not isinstance(val, dict):
                    return default
                val = val.get(key, default)
                if val is None:
                    return default
            return val

        return cls(
            config_dir=config_dir,
            proxy_port=get("proxy.port", DEFAULT_PROXY_PORT),
            hold_timeout_seconds=get("proxy.hold_timeout_seconds", 60),
            openclaw_gateway_config=get("openclaw.gateway_config", ""),
            openclaw_original_endpoint=get("openclaw.original_endpoint", ""),
            telegram_bot_token=get("notifications.telegram.bot_token", ""),
            telegram_chat_id=get("notifications.telegram.chat_id", ""),
            notification_email=get("notifications.email.address", ""),
            resend_api_key=get("notifications.email.resend_api_key", ""),
            cloud_enabled=get("cloud.enabled", False),
            cloud_api_key=get("cloud.api_key", ""),
            cloud_endpoint=get("cloud.endpoint", "https://api.clawsafe.dev"),
            bulk_delete_limit=get("rules.bulk_delete_limit", 10),
            bulk_send_limit=get("rules.bulk_send_limit", 5),
            allow_shell_exec=get("rules.allow_shell_exec", False),
            dashboard_sync_interval=get("dashboard.sync_interval_seconds", 60),
            dashboard_enabled=get("dashboard.enabled", False),
        )

    def save(self) -> None:
        """Write config to disk with secure permissions."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        config_file = self.config_dir / "config.yaml"

        data = {
            "version": 1,
            "proxy": {
                "port": self.proxy_port,
                "hold_timeout_seconds": self.hold_timeout_seconds,
            },
            "openclaw": {
                "gateway_config": self.openclaw_gateway_config,
                "original_endpoint": self.openclaw_original_endpoint,
            },
            "notifications": {
                "telegram": {
                    "bot_token": self.telegram_bot_token,
                    "chat_id": self.telegram_chat_id,
                },
                "email": {
                    "address": self.notification_email,
                    "resend_api_key": self.resend_api_key,
                },
            },
            "cloud": {
                "enabled": self.cloud_enabled,
                "api_key": self.cloud_api_key,
                "endpoint": self.cloud_endpoint,
            },
            "rules": {
                "bulk_delete_limit": self.bulk_delete_limit,
                "bulk_send_limit": self.bulk_send_limit,
                "allow_shell_exec": self.allow_shell_exec,
            },
            "dashboard": {
                "sync_interval_seconds": self.dashboard_sync_interval,
                "enabled": self.dashboard_enabled,
            },
        }

        with open(config_file, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

        os.chmod(config_file, 0o600)

    def generate_api_key(self) -> str:
        """Generate a new unique API key and save it to config."""
        key = f"cs_{uuid.uuid4().hex}"
        self.cloud_api_key = key
        self.save()
        return key

    @property
    def user_id(self) -> str:
        """Anonymised user ID for cloud calls."""
        if not self.cloud_api_key:
            return "anonymous"
        return hashlib.sha256(self.cloud_api_key.encode()).hexdigest()[:16]

    @property
    def has_notifications(self) -> bool:
        return bool(self.telegram_bot_token or self.resend_api_key)
