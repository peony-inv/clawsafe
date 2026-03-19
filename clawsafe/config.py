"""Configuration management for ClawSafe."""

import os
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional
import yaml


@dataclass
class ProxyConfig:
    port: int = 18790
    hold_timeout_seconds: int = 60


@dataclass
class OpenClawConfig:
    gateway_config: str = "~/.openclaw/gateway.yaml"
    original_endpoint: str = ""


@dataclass
class TelegramConfig:
    bot_token: str = ""
    chat_id: str = ""


@dataclass
class EmailConfig:
    address: str = ""


@dataclass
class NotificationsConfig:
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    email: EmailConfig = field(default_factory=EmailConfig)


@dataclass
class CloudConfig:
    enabled: bool = False
    api_key: str = ""
    endpoint: str = "https://api.clawsafe.dev"


@dataclass
class RulesConfig:
    bulk_delete_limit: int = 10
    bulk_send_limit: int = 5
    allow_shell_exec: bool = False


@dataclass
class DashboardConfig:
    sync_interval_seconds: int = 60
    enabled: bool = False


@dataclass
class Config:
    version: int = 1
    proxy: ProxyConfig = field(default_factory=ProxyConfig)
    openclaw: OpenClawConfig = field(default_factory=OpenClawConfig)
    notifications: NotificationsConfig = field(default_factory=NotificationsConfig)
    cloud: CloudConfig = field(default_factory=CloudConfig)
    rules: RulesConfig = field(default_factory=RulesConfig)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)


def config_dir() -> Path:
    """Get the ClawSafe config directory."""
    if env_path := os.environ.get("CLAWSAFE_CONFIG_PATH"):
        return Path(env_path).parent
    return Path.home() / ".clawsafe"


def config_path() -> Path:
    """Get the ClawSafe config file path."""
    if env_path := os.environ.get("CLAWSAFE_CONFIG_PATH"):
        return Path(env_path)
    return config_dir() / "config.yaml"


def expand_path(path: str) -> Path:
    """Expand ~ in paths."""
    return Path(path).expanduser()


def load_config() -> Config:
    """Load config from disk, or return defaults."""
    path = config_path()

    if not path.exists():
        return Config()

    with open(path) as f:
        data = yaml.safe_load(f) or {}

    return _dict_to_config(data)


def save_config(cfg: Config) -> None:
    """Save config to disk."""
    dir_path = config_dir()
    dir_path.mkdir(parents=True, exist_ok=True)

    path = config_path()

    with open(path, "w") as f:
        yaml.dump(_config_to_dict(cfg), f, default_flow_style=False)

    # Set secure permissions
    path.chmod(0o600)


def _config_to_dict(cfg: Config) -> dict:
    """Convert Config dataclass to dict for YAML."""
    def convert(obj):
        if hasattr(obj, "__dataclass_fields__"):
            return {k: convert(v) for k, v in asdict(obj).items()}
        return obj
    return convert(cfg)


def _dict_to_config(data: dict) -> Config:
    """Convert dict from YAML to Config dataclass."""
    cfg = Config()

    if "version" in data:
        cfg.version = data["version"]

    if "proxy" in data:
        cfg.proxy = ProxyConfig(**data["proxy"])

    if "openclaw" in data:
        cfg.openclaw = OpenClawConfig(**data["openclaw"])

    if "cloud" in data:
        cfg.cloud = CloudConfig(**data["cloud"])

    if "rules" in data:
        cfg.rules = RulesConfig(**data["rules"])

    if "dashboard" in data:
        cfg.dashboard = DashboardConfig(**data["dashboard"])

    return cfg
