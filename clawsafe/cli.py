"""
ClawSafe CLI — all user-facing commands.

Commands:
  install          Full onboarding: molting sequence + config + daemon setup
  start            Start the proxy (foreground)
  stop             Stop the daemon
  status           Show running status + recent decisions
  wrap [agent]     Patch agent config to route through ClawSafe
  unwrap           Restore original agent config
  doctor           Run health checks
  logs             Show recent audit log
  rules list       List loaded rules
  rules add        Add a custom rule
  allow-once       Manually allow a held action
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from rich.text import Text

from .config import Config
from .daemon import install_daemon, uninstall_daemon
from .onboard import run_molting_sequence
from .openclaw import find_gateway_config, wrap, unwrap

console = Console()


@click.group()
@click.version_option(version="0.1.0", prog_name="ClawSafe")
def main() -> None:
    """\U0001F99E ClawSafe — The AI agent safety firewall."""
    pass


# ─── INSTALL ──────────────────────────────────────────────────────────────────

@main.command()
@click.option("--no-daemon", is_flag=True, help="Skip daemon installation")
def install(no_daemon: bool) -> None:
    """Run full onboarding: molting sequence + config + daemon setup."""
    run_molting_sequence()

    config = Config.load()
    config.config_dir.mkdir(parents=True, exist_ok=True)

    rules_dir = config.config_dir / "rules"
    rules_dir.mkdir(exist_ok=True)

    if not config.cloud_api_key:
        config.generate_api_key()
        console.print("[dim]API key generated. Keep this safe.[/dim]")

    config.save()

    console.print(f"[green]Config created:[/green] {config.config_dir / 'config.yaml'}")
    console.print(f"[green]Rules directory:[/green] {rules_dir}")
    console.print()

    if not no_daemon:
        console.print("[bold]Installing daemon...[/bold]")
        success, message = install_daemon()
        if success:
            console.print(f"[green]\u2705  {message}[/green]")
        else:
            console.print(f"[yellow]\u26A0\uFE0F  Daemon install: {message}[/yellow]")
            console.print("[dim]You can start manually with: clawsafe start[/dim]")

    console.print()
    console.print("[bold]Next step:[/bold] [cyan]clawsafe wrap openclaw[/cyan]")
    console.print()
    console.print("To connect Telegram notifications:")
    console.print("  1. Message @BotFather on Telegram")
    console.print("  2. Create a new bot, copy the token")
    console.print("  3. Edit ~/.clawsafe/config.yaml and set notifications.telegram.bot_token")


# ─── WRAP / UNWRAP ────────────────────────────────────────────────────────────

@main.command("wrap")
@click.argument("agent", default="openclaw")
@click.option("--config", "config_path", default="", help="Path to agent gateway config")
def wrap_cmd(agent: str, config_path: str) -> None:
    """Wrap an agent to route tool calls through ClawSafe."""
    if agent.lower() != "openclaw":
        console.print(f"[red]Unknown agent: {agent}[/red]")
        console.print("Currently supported: openclaw")
        sys.exit(1)

    with console.status("[bold]Patching OpenClaw gateway config...[/bold]"):
        success, message = wrap(config_path)

    if success:
        console.print(f"[green]\u2705[/green]  {message}")
        console.print()
        console.print("Restart OpenClaw for changes to take effect.")
        console.print("Run [cyan]clawsafe doctor[/cyan] to verify everything is connected.")
    else:
        console.print(f"[red]\u274C[/red]  {message}")
        sys.exit(1)


@main.command("unwrap")
@click.option("--config", "config_path", default="")
def unwrap_cmd(config_path: str) -> None:
    """Restore original agent config (remove ClawSafe proxy)."""
    success, message = unwrap(config_path)
    if success:
        console.print(f"[green]\u2705[/green]  {message}")
    else:
        console.print(f"[red]\u274C[/red]  {message}")
        sys.exit(1)


# ─── START / STOP ─────────────────────────────────────────────────────────────

@main.command()
def start() -> None:
    """Start the ClawSafe proxy in the foreground."""
    from .proxy import ClawSafeProxy

    config = Config.load()
    proxy = ClawSafeProxy(config)

    console.print(
        f"[bold]\U0001F99E ClawSafe[/bold] listening on "
        f"[cyan]ws://localhost:{config.proxy_port}[/cyan]"
    )
    console.print("[dim]Press Ctrl+C to stop[/dim]")
    console.print()

    try:
        asyncio.run(proxy.start())
    except KeyboardInterrupt:
        console.print("\n[dim]ClawSafe stopped.[/dim]")
    except Exception as e:
        console.print(f"\n[red]ClawSafe crashed: {e}[/red]")
        sys.exit(1)


@main.command()
def stop() -> None:
    """Stop the ClawSafe daemon."""
    success, message = uninstall_daemon()
    if success:
        console.print(f"[green]\u2705[/green]  {message}")
    else:
        console.print(f"[yellow]\u26A0\uFE0F[/yellow]  {message}")


# ─── STATUS ───────────────────────────────────────────────────────────────────

@main.command()
def status() -> None:
    """Show ClawSafe daemon status and recent activity."""
    import socket

    config = Config.load()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        running = s.connect_ex(("127.0.0.1", config.proxy_port)) == 0

    console.print(f"\n[bold]\U0001F99E ClawSafe Status[/bold]\n")
    console.print(
        f"  Proxy:         "
        f"{'[green]running[/green]' if running else '[red]stopped[/red]'} "
        f"[dim](localhost:{config.proxy_port})[/dim]"
    )
    console.print(
        f"  Cloud AI:      "
        f"{'[green]enabled[/green]' if config.cloud_enabled else '[dim]disabled (free tier)[/dim]'}"
    )
    console.print(
        f"  Notifications: "
        f"{'[green]telegram[/green]' if config.telegram_bot_token else '[dim]not configured[/dim]'}"
    )

    gw = find_gateway_config(config.openclaw_gateway_config)
    if gw:
        import yaml
        with open(gw) as f:
            data = yaml.safe_load(f) or {}
        wrapped = data.get("tools", {}).get("_clawsafe_wrapped", False)
        console.print(
            f"  OpenClaw:      "
            f"{'[green]wrapped[/green]' if wrapped else '[yellow]not wrapped[/yellow] (run: clawsafe wrap openclaw)'}"
        )

    async def get_stats():
        from .audit import AuditLog
        audit = AuditLog(config.config_dir / "audit.db")
        await audit.initialize()
        s = await audit.stats()
        r = await audit.recent(limit=5)
        await audit.close()
        return s, r

    try:
        stats, recent = asyncio.run(get_stats())
        console.print()
        console.print(
            f"  [green]{stats['allow']} allowed[/green]  "
            f"[red]{stats['block']} blocked[/red]  "
            f"[yellow]{stats['gray']} flagged[/yellow]  "
            f"(total: {stats['total']})"
        )

        if recent:
            console.print()
            table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
            table.add_column("Time", style="dim", width=10)
            table.add_column("Tool", width=25)
            table.add_column("Verdict", width=8)
            table.add_column("Reason")

            for event in recent:
                ts = time.strftime("%H:%M:%S", time.localtime(event["timestamp"]))
                v = event["verdict"]
                verdict_text = Text(
                    v, style={"allow": "green", "block": "red", "gray": "yellow"}.get(v, "white")
                )
                table.add_row(ts, event["tool"], verdict_text, (event.get("reason") or "")[:60])

            console.print(table)
    except Exception:
        pass

    console.print()


# ─── DOCTOR ───────────────────────────────────────────────────────────────────

@main.command()
def doctor() -> None:
    """Run health checks on ClawSafe configuration."""
    import socket

    console.print("\n[bold]\U0001F9BA ClawSafe Doctor[/bold]\n")
    config = Config.load()
    all_ok = True

    def check(name: str, ok: bool, detail: str = "", fix: str = "") -> None:
        nonlocal all_ok
        if ok:
            console.print(f"  [green]\u2705[/green]  {name}" + (f" [dim]({detail})[/dim]" if detail else ""))
        else:
            all_ok = False
            console.print(f"  [red]\u274C[/red]  {name}" + (f" [dim]({detail})[/dim]" if detail else ""))
            if fix:
                console.print(f"         [dim]Fix: {fix}[/dim]")

    # Python version
    v = sys.version_info
    check(
        "Python 3.10+",
        v.major == 3 and v.minor >= 10,
        f"Python {v.major}.{v.minor}.{v.micro}"
    )

    # Config file
    config_file = config.config_dir / "config.yaml"
    check("Config file exists", config_file.exists(), str(config_file), "Run: clawsafe install")

    # Proxy running
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        proxy_running = s.connect_ex(("127.0.0.1", config.proxy_port)) == 0
    check(
        "Proxy is running",
        proxy_running,
        f"localhost:{config.proxy_port}",
        "Run: clawsafe start"
    )

    # OpenClaw config found
    gw = find_gateway_config(config.openclaw_gateway_config)
    check("OpenClaw config found", gw is not None, str(gw) if gw else "Not found")

    # OpenClaw wrapped
    if gw:
        import yaml
        with open(gw) as f:
            data = yaml.safe_load(f) or {}
        wrapped = data.get("tools", {}).get("_clawsafe_wrapped", False)
        check(
            "OpenClaw is wrapped",
            wrapped,
            "Routing through ClawSafe" if wrapped else "Not wrapped",
            "Run: clawsafe wrap openclaw"
        )

    # Notifications
    has_telegram = bool(config.telegram_bot_token and config.telegram_chat_id)
    has_email = bool(config.resend_api_key and config.notification_email)
    check(
        "Notifications configured",
        has_telegram or has_email,
        "telegram" if has_telegram else ("email" if has_email else "none"),
        "Edit ~/.clawsafe/config.yaml to set notifications.telegram.bot_token"
    )

    # Rule engine
    from .rules.engine import RuleEngine
    engine = RuleEngine(config.config_dir, config)
    check("Rule engine loaded", engine.rule_count > 0, f"{engine.rule_count} rules")

    console.print()
    if all_ok:
        console.print("  [bold green]All checks passed. ClawSafe is ready.[/bold green]")
    else:
        console.print("  [bold yellow]Some checks failed. See fixes above.[/bold yellow]")
    console.print()


# ─── LOGS ─────────────────────────────────────────────────────────────────────

@main.command()
@click.option("--limit", default=50, help="Number of events to show")
@click.option("--verdict", default=None, type=click.Choice(["allow", "block", "gray"]))
def logs(limit: int, verdict: str | None) -> None:
    """Show recent audit log."""
    config = Config.load()

    async def get_recent():
        from .audit import AuditLog
        audit = AuditLog(config.config_dir / "audit.db")
        await audit.initialize()
        events = await audit.recent(limit=limit, verdict_filter=verdict)
        await audit.close()
        return events

    events = asyncio.run(get_recent())

    if not events:
        console.print("[dim]No events yet. Is ClawSafe running?[/dim]")
        return

    table = Table(
        title="\U0001F99E ClawSafe Audit Log", show_header=True, box=None, padding=(0, 2)
    )
    table.add_column("Timestamp", style="dim")
    table.add_column("Tool")
    table.add_column("Verdict", width=8)
    table.add_column("Rule")
    table.add_column("Reason")

    for event in events:
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(event["timestamp"]))
        v = event["verdict"]
        verdict_text = Text(
            v, style={"allow": "green", "block": "red", "gray": "yellow"}.get(v, "white")
        )
        table.add_row(
            ts,
            event["tool"],
            verdict_text,
            event.get("rule_name", ""),
            (event.get("reason") or "")[:60],
        )

    console.print(table)


# ─── RULES ────────────────────────────────────────────────────────────────────

@main.group()
def rules() -> None:
    """Manage ClawSafe rules."""
    pass


@rules.command(name="list")
def rules_list() -> None:
    """List all loaded rules."""
    config = Config.load()
    from .rules.engine import RuleEngine
    engine = RuleEngine(config.config_dir, config)
    summary = engine.get_rules_summary()

    table = Table(
        title="\U0001F99E ClawSafe Rules", show_header=True, box=None, padding=(0, 2)
    )
    table.add_column("#", width=4)
    table.add_column("Name")
    table.add_column("Source", width=10)
    table.add_column("Description")

    for i, rule in enumerate(summary, 1):
        source_text = Text(
            rule["source"], style="green" if rule["source"] == "user" else "dim"
        )
        table.add_row(str(i), rule["name"], source_text, rule["docstring"])

    console.print(table)
    console.print(
        f"\n[dim]{len(summary)} rules total. "
        f"Add custom rules to: {config.config_dir / 'rules'}[/dim]\n"
    )


@rules.command(name="add")
@click.argument("name")
@click.option("--file", "rule_file", default=None, help="Path to Python rule file")
def rules_add(name: str, rule_file: str | None) -> None:
    """Add a custom rule. Opens a template if no --file given."""
    config = Config.load()
    rules_dir = config.config_dir / "rules"
    rules_dir.mkdir(exist_ok=True)

    target = rules_dir / f"{name}.py"

    if rule_file:
        import shutil
        shutil.copy(rule_file, target)
        console.print(f"[green]\u2705[/green]  Rule copied to: {target}")
    else:
        template = f'''"""
Custom ClawSafe rule: {name}
"""

from clawsafe.rules.models import Decision


def rule(tool: str, args: dict) -> Decision | None:
    """TODO: describe what this rule does"""
    # Return None to pass to the next rule (no opinion)
    # Return Decision.block("reason", "{name}") to block
    # Return Decision.gray("reason", "{name}") to escalate to cloud AI

    return None  # no opinion
'''
        target.write_text(template)
        console.print(f"[green]\u2705[/green]  Rule template created: {target}")
        console.print("[dim]Edit the file, then restart ClawSafe for it to take effect.[/dim]")

        editor = os.environ.get("EDITOR", "")
        if editor:
            import subprocess
            subprocess.run([editor, str(target)])


# ─── ALLOW-ONCE ───────────────────────────────────────────────────────────────

@main.command("allow-once")
@click.argument("action_id")
def allow_once(action_id: str) -> None:
    """Manually allow a held GRAY action (use the 8-character ID from the notification)."""
    import httpx

    try:
        response = httpx.post(
            "http://localhost:18791/override",
            json={"action_id": action_id, "verdict": "allow"},
            timeout=5.0
        )
        if response.status_code == 200:
            console.print(f"[green]\u2705[/green]  Action {action_id} allowed.")
        else:
            console.print(
                f"[yellow]\u26A0\uFE0F[/yellow]  Action not found (may have already timed out)."
            )
    except Exception as e:
        console.print(f"[red]\u274C[/red]  Could not reach proxy: {e}")
        console.print("[dim]Is ClawSafe running? Check: clawsafe status[/dim]")
