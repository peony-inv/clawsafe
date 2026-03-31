"""
OpenClaw gateway config patching.

clawsafe wrap openclaw: patches gateway.yaml to route through localhost:18790
clawsafe unwrap: restores original config from backup
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

import yaml

CLAWSAFE_PROXY_ENDPOINT = "http://localhost:18790"
BACKUP_EXTENSION = ".clawsafe-backup"

OPENCLAW_CONFIG_SEARCH_PATHS = [
    Path.home() / ".openclaw" / "gateway.yaml",
    Path.home() / ".config" / "openclaw" / "gateway.yaml",
    Path.home() / "Library" / "Application Support" / "openclaw" / "gateway.yaml",
    Path("/etc/openclaw/gateway.yaml"),
    Path("/opt/openclaw/gateway.yaml"),
]


def find_gateway_config(explicit_path: str = "") -> Path | None:
    """Find the OpenClaw gateway config file."""
    if explicit_path:
        p = Path(explicit_path).expanduser()
        if p.exists():
            return p
        return None

    for path in OPENCLAW_CONFIG_SEARCH_PATHS:
        if path.exists():
            return path

    return None


def wrap(explicit_config_path: str = "") -> tuple[bool, str]:
    """Patch OpenClaw to route tool calls through ClawSafe."""
    config_path = find_gateway_config(explicit_config_path)

    if not config_path:
        return False, (
            "OpenClaw gateway config not found. "
            "Searched: " + ", ".join(str(p) for p in OPENCLAW_CONFIG_SEARCH_PATHS) + ". "
            "Is OpenClaw installed? Try: clawsafe wrap openclaw --config /path/to/gateway.yaml"
        )

    with open(config_path) as f:
        data = yaml.safe_load(f) or {}

    if data.get("tools", {}).get("_clawsafe_wrapped"):
        return True, f"OpenClaw is already wrapped by ClawSafe. Config: {config_path}"

    # Create backup before modifying
    backup_path = config_path.with_suffix(BACKUP_EXTENSION)
    shutil.copy2(config_path, backup_path)

    original_endpoint = data.get("tools", {}).get("endpoint", "")

    if "tools" not in data:
        data["tools"] = {}

    data["tools"]["endpoint"] = CLAWSAFE_PROXY_ENDPOINT
    data["tools"]["_clawsafe_wrapped"] = True
    data["tools"]["_clawsafe_original_endpoint"] = original_endpoint
    data["tools"]["_clawsafe_wrapped_at"] = datetime.now(timezone.utc).isoformat()

    with open(config_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    return True, (
        f"OpenClaw wrapped successfully.\n"
        f"  Config: {config_path}\n"
        f"  Backup: {backup_path}\n"
        f"  Original endpoint: {original_endpoint or '(none)'}\n"
        f"  Now routing through: {CLAWSAFE_PROXY_ENDPOINT}"
    )


def unwrap(explicit_config_path: str = "") -> tuple[bool, str]:
    """Restore OpenClaw to its original config."""
    config_path = find_gateway_config(explicit_config_path)

    if not config_path:
        return False, "OpenClaw gateway config not found."

    backup_path = config_path.with_suffix(BACKUP_EXTENSION)
    if backup_path.exists():
        shutil.copy2(backup_path, config_path)
        backup_path.unlink()
        return True, f"OpenClaw restored from backup: {config_path}"

    with open(config_path) as f:
        data = yaml.safe_load(f) or {}

    if not data.get("tools", {}).get("_clawsafe_wrapped"):
        return False, "OpenClaw does not appear to be wrapped by ClawSafe."

    original_endpoint = data["tools"].pop("_clawsafe_original_endpoint", "")
    data["tools"].pop("_clawsafe_wrapped", None)
    data["tools"].pop("_clawsafe_wrapped_at", None)
    data["tools"]["endpoint"] = original_endpoint

    with open(config_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    return True, (
        f"OpenClaw restored.\n"
        f"  Config: {config_path}\n"
        f"  Restored endpoint: {original_endpoint or '(none)'}"
    )


def get_original_endpoint(explicit_config_path: str = "") -> str:
    """Read the original endpoint from a wrapped config."""
    config_path = find_gateway_config(explicit_config_path)
    if not config_path:
        return ""

    with open(config_path) as f:
        data = yaml.safe_load(f) or {}

    return data.get("tools", {}).get("_clawsafe_original_endpoint", "")
