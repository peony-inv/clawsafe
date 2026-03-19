"""Daemon/autostart management for ClawSafe."""

import os
import platform
import subprocess
import sys
from pathlib import Path

from .config import config_dir


def get_system() -> str:
    """Get the current OS."""
    system = platform.system().lower()
    if system == "darwin":
        return "macos"
    elif system == "linux":
        return "linux"
    else:
        return "unsupported"


def get_clawsafe_path() -> str:
    """Get the path to the clawsafe executable."""
    # Try to find it in the current environment
    import shutil
    path = shutil.which("clawsafe")
    if path:
        return path

    # Fallback to python -m
    return f"{sys.executable} -m clawsafe.cli"


# ============== macOS launchd ==============

def get_launchd_plist_path() -> Path:
    """Get the path to the launchd plist file."""
    return Path.home() / "Library" / "LaunchAgents" / "dev.clawsafe.plist"


def generate_launchd_plist() -> str:
    """Generate the launchd plist content."""
    clawsafe_path = get_clawsafe_path()
    log_dir = config_dir()

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>dev.clawsafe</string>

    <key>ProgramArguments</key>
    <array>
        <string>{clawsafe_path}</string>
        <string>start</string>
        <string>--foreground</string>
    </array>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>{log_dir}/clawsafe.log</string>

    <key>StandardErrorPath</key>
    <string>{log_dir}/clawsafe.err</string>

    <key>WorkingDirectory</key>
    <string>{Path.home()}</string>
</dict>
</plist>
"""


def enable_launchd() -> tuple[bool, str]:
    """Enable launchd autostart on macOS."""
    plist_path = get_launchd_plist_path()

    # Create LaunchAgents directory if needed
    plist_path.parent.mkdir(parents=True, exist_ok=True)

    # Write plist
    plist_content = generate_launchd_plist()
    plist_path.write_text(plist_content)

    # Load the service
    result = subprocess.run(
        ["launchctl", "load", str(plist_path)],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        return False, f"Failed to load: {result.stderr}"

    return True, f"Autostart enabled. Plist: {plist_path}"


def disable_launchd() -> tuple[bool, str]:
    """Disable launchd autostart on macOS."""
    plist_path = get_launchd_plist_path()

    if not plist_path.exists():
        return True, "Autostart was not enabled"

    # Unload the service
    subprocess.run(
        ["launchctl", "unload", str(plist_path)],
        capture_output=True,
        text=True
    )

    # Remove plist
    plist_path.unlink()

    return True, "Autostart disabled"


def status_launchd() -> tuple[bool, str]:
    """Check launchd autostart status on macOS."""
    plist_path = get_launchd_plist_path()

    if not plist_path.exists():
        return False, "Autostart not configured"

    # Check if service is loaded
    result = subprocess.run(
        ["launchctl", "list", "dev.clawsafe"],
        capture_output=True,
        text=True
    )

    if result.returncode == 0:
        return True, "Autostart enabled and running"
    else:
        return True, "Autostart enabled (not currently running)"


# ============== Linux systemd ==============

def get_systemd_service_path() -> Path:
    """Get the path to the systemd service file."""
    return Path.home() / ".config" / "systemd" / "user" / "clawsafe.service"


def generate_systemd_service() -> str:
    """Generate the systemd service content."""
    clawsafe_path = get_clawsafe_path()

    return f"""[Unit]
Description=ClawSafe - Reversibility firewall for AI agents
After=network.target

[Service]
Type=simple
ExecStart={clawsafe_path} start --foreground
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
"""


def enable_systemd() -> tuple[bool, str]:
    """Enable systemd autostart on Linux."""
    service_path = get_systemd_service_path()

    # Create directory if needed
    service_path.parent.mkdir(parents=True, exist_ok=True)

    # Write service file
    service_content = generate_systemd_service()
    service_path.write_text(service_content)

    # Reload systemd
    subprocess.run(
        ["systemctl", "--user", "daemon-reload"],
        capture_output=True
    )

    # Enable the service
    result = subprocess.run(
        ["systemctl", "--user", "enable", "clawsafe.service"],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        return False, f"Failed to enable: {result.stderr}"

    # Start the service
    subprocess.run(
        ["systemctl", "--user", "start", "clawsafe.service"],
        capture_output=True
    )

    return True, f"Autostart enabled. Service: {service_path}"


def disable_systemd() -> tuple[bool, str]:
    """Disable systemd autostart on Linux."""
    service_path = get_systemd_service_path()

    if not service_path.exists():
        return True, "Autostart was not enabled"

    # Stop the service
    subprocess.run(
        ["systemctl", "--user", "stop", "clawsafe.service"],
        capture_output=True
    )

    # Disable the service
    subprocess.run(
        ["systemctl", "--user", "disable", "clawsafe.service"],
        capture_output=True
    )

    # Remove service file
    service_path.unlink()

    # Reload systemd
    subprocess.run(
        ["systemctl", "--user", "daemon-reload"],
        capture_output=True
    )

    return True, "Autostart disabled"


def status_systemd() -> tuple[bool, str]:
    """Check systemd autostart status on Linux."""
    service_path = get_systemd_service_path()

    if not service_path.exists():
        return False, "Autostart not configured"

    # Check service status
    result = subprocess.run(
        ["systemctl", "--user", "is-active", "clawsafe.service"],
        capture_output=True,
        text=True
    )

    if result.stdout.strip() == "active":
        return True, "Autostart enabled and running"
    else:
        return True, "Autostart enabled (not currently running)"


# ============== Public API ==============

def autostart_enable() -> tuple[bool, str]:
    """Enable autostart for the current platform."""
    system = get_system()

    if system == "macos":
        return enable_launchd()
    elif system == "linux":
        return enable_systemd()
    else:
        return False, f"Unsupported platform: {platform.system()}"


def autostart_disable() -> tuple[bool, str]:
    """Disable autostart for the current platform."""
    system = get_system()

    if system == "macos":
        return disable_launchd()
    elif system == "linux":
        return disable_systemd()
    else:
        return False, f"Unsupported platform: {platform.system()}"


def autostart_status() -> tuple[bool, str]:
    """Check autostart status for the current platform."""
    system = get_system()

    if system == "macos":
        return status_launchd()
    elif system == "linux":
        return status_systemd()
    else:
        return False, f"Unsupported platform: {platform.system()}"
