"""
Daemon management for ClawSafe proxy.

macOS: launchd plist at ~/Library/LaunchAgents/dev.clawsafe.plist
Linux: systemd user unit at ~/.config/systemd/user/clawsafe.service
"""

from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path


def install_daemon() -> tuple[bool, str]:
    """Install the daemon for the current platform."""
    system = platform.system()
    if system == "Darwin":
        return _install_macos()
    elif system == "Linux":
        return _install_linux()
    else:
        return False, f"Unsupported platform: {system}"


def uninstall_daemon() -> tuple[bool, str]:
    """Remove the daemon."""
    system = platform.system()
    if system == "Darwin":
        return _uninstall_macos()
    elif system == "Linux":
        return _uninstall_linux()
    else:
        return False, f"Unsupported platform: {system}"


def _clawsafe_binary() -> str:
    """Find the clawsafe executable path."""
    import shutil
    path = shutil.which("clawsafe")
    return path or sys.executable + " -m clawsafe"


MACOS_PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / "dev.clawsafe.plist"

MACOS_PLIST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
    "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>dev.clawsafe</string>
    <key>ProgramArguments</key>
    <array>
        <string>{binary}</string>
        <string>start</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{log_dir}/clawsafe.log</string>
    <key>StandardErrorPath</key>
    <string>{log_dir}/clawsafe-error.log</string>
</dict>
</plist>"""


def _install_macos() -> tuple[bool, str]:
    log_dir = Path.home() / ".clawsafe" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    plist_content = MACOS_PLIST_TEMPLATE.format(
        binary=_clawsafe_binary(),
        log_dir=log_dir,
    )

    MACOS_PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MACOS_PLIST_PATH.write_text(plist_content)

    result = subprocess.run(
        ["launchctl", "load", str(MACOS_PLIST_PATH)],
        capture_output=True, text=True
    )

    if result.returncode == 0:
        return True, f"macOS launch agent installed: {MACOS_PLIST_PATH}"
    else:
        return False, f"launchctl load failed: {result.stderr}"


def _uninstall_macos() -> tuple[bool, str]:
    if MACOS_PLIST_PATH.exists():
        subprocess.run(["launchctl", "unload", str(MACOS_PLIST_PATH)], capture_output=True)
        MACOS_PLIST_PATH.unlink()
        return True, "macOS launch agent removed"
    return False, "macOS launch agent not found"


LINUX_UNIT_PATH = Path.home() / ".config" / "systemd" / "user" / "clawsafe.service"

LINUX_UNIT_TEMPLATE = """[Unit]
Description=ClawSafe AI Agent Safety Firewall
After=network.target

[Service]
Type=simple
ExecStart={binary} start
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
"""


def _install_linux() -> tuple[bool, str]:
    LINUX_UNIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    LINUX_UNIT_PATH.write_text(LINUX_UNIT_TEMPLATE.format(binary=_clawsafe_binary()))

    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    result = subprocess.run(
        ["systemctl", "--user", "enable", "--now", "clawsafe"],
        capture_output=True, text=True
    )

    if result.returncode == 0:
        return True, f"systemd user service installed and started: {LINUX_UNIT_PATH}"
    else:
        return False, f"systemctl enable failed: {result.stderr}"


def _uninstall_linux() -> tuple[bool, str]:
    subprocess.run(["systemctl", "--user", "disable", "--now", "clawsafe"], capture_output=True)
    if LINUX_UNIT_PATH.exists():
        LINUX_UNIT_PATH.unlink()
    return True, "systemd user service removed"
