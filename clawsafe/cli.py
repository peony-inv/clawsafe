"""CLI for ClawSafe."""

import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt, Confirm
import yaml

from .config import load_config, save_config, config_dir, expand_path
from .rules import (
    RuleConfig, RuleEngine, Verdict, ToolCall,
    CustomRule, load_custom_rules, add_custom_rule, remove_custom_rule,
    set_rule_enabled, rules_file_path, BUILTIN_RULES
)
from .proxy import ClawSafeProxy
from .audit import AuditStore
from .notify import TelegramBot
from .daemon import autostart_enable, autostart_disable, autostart_status

app = typer.Typer(
    name="clawsafe",
    help="ClawSafe - Reversibility firewall for AI agents",
    no_args_is_help=True,
)

rules_app = typer.Typer(help="Manage rules")
app.add_typer(rules_app, name="rules")

autostart_app = typer.Typer(help="Manage auto-start on boot")
app.add_typer(autostart_app, name="autostart")

console = Console()


def get_pid_file() -> Path:
    """Get the PID file path."""
    return config_dir() / "clawsafe.pid"


def print_block(tool: str, reason: str):
    """Print a block notification to console."""
    console.print()
    console.print("[bold red]BLOCKED[/bold red] ClawSafe blocked action")
    console.print(f"   Tool: {tool}")
    console.print(f"   Reason: {reason}")
    console.print()


@app.command()
def install(
    autostart: bool = typer.Option(False, "--autostart", "-a", help="Enable auto-start on boot"),
):
    """Initial setup with the molting sequence."""
    import time

    steps = [
        ("🦞", "molting the shell..."),
        ("🔍", "sniffing for claws..."),
        ("🪤", "laying the trap..."),
        ("🛡️", "hardening the carapace..."),
        ("⛓️", "chaining the rules..."),
        ("🌊", "testing the tides..."),
    ]

    console.print()
    for emoji, message in steps:
        console.print(f"  {emoji}  {message}")
        time.sleep(0.7)

    console.print()
    console.print("  [green]✅  shell secured. claw safe.[/green]")
    console.print()

    # Create config directory
    cfg_dir = config_dir()
    cfg_dir.mkdir(parents=True, exist_ok=True)

    # Save default config
    cfg = load_config()
    save_config(cfg)

    console.print(f"  Config: {cfg_dir}/config.yaml")
    console.print(f"  Rules:  {cfg_dir}/rules.yaml")
    console.print(f"  Logs:   {cfg_dir}/audit.db")
    console.print()

    if autostart:
        from .daemon import autostart_enable
        success, message = autostart_enable()
        if success:
            console.print(f"  [green]Auto-start enabled[/green]")
        else:
            console.print(f"  [yellow]Auto-start failed: {message}[/yellow]")
        console.print()

    console.print("[bold]Next steps:[/bold]")
    console.print("  1. clawsafe setup-telegram   # Get notifications")
    console.print("  2. clawsafe start            # Start the proxy")
    console.print("  3. clawsafe wrap openclaw    # Route your agent through ClawSafe")
    console.print()


@app.command()
def start(
    foreground: bool = typer.Option(False, "--foreground", "-f", help="Run in foreground"),
):
    """Start the ClawSafe proxy daemon."""
    cfg = load_config()

    # Check if already running
    pid_file = get_pid_file()
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)  # Check if process exists
            console.print(f"[yellow]ClawSafe already running (PID {pid})[/yellow]")
            return
        except (ProcessLookupError, ValueError):
            pid_file.unlink()  # Stale PID file

    # Write PID file
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(os.getpid()))

    # Create proxy
    proxy = ClawSafeProxy(
        port=cfg.proxy.port,
        rule_config=RuleConfig(
            bulk_delete_limit=cfg.rules.bulk_delete_limit,
            bulk_send_limit=cfg.rules.bulk_send_limit,
            allow_shell_exec=cfg.rules.allow_shell_exec,
        ),
        target_endpoint=cfg.openclaw.original_endpoint,
        on_block=print_block,
    )

    console.print(f"[green]ClawSafe proxy starting on 127.0.0.1:{cfg.proxy.port}[/green]")
    console.print("Press Ctrl+C to stop")

    def cleanup(signum, frame):
        console.print("\n[yellow]Shutting down...[/yellow]")
        pid_file.unlink(missing_ok=True)
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    try:
        proxy.run()
    finally:
        pid_file.unlink(missing_ok=True)


@app.command()
def stop():
    """Stop the ClawSafe proxy daemon."""
    pid_file = get_pid_file()

    if not pid_file.exists():
        console.print("[yellow]ClawSafe is not running[/yellow]")
        return

    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        pid_file.unlink()
        console.print("[green]ClawSafe stopped[/green]")
    except ProcessLookupError:
        pid_file.unlink()
        console.print("[yellow]ClawSafe was not running (stale PID file removed)[/yellow]")
    except ValueError:
        console.print("[red]Invalid PID file[/red]")


@app.command()
def status():
    """Show daemon status and recent decisions."""
    pid_file = get_pid_file()
    cfg = load_config()

    # Check if running
    running = False
    pid = None

    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)
            running = True
        except (ProcessLookupError, ValueError):
            pid_file.unlink(missing_ok=True)

    if running:
        console.print(f"[green]Status: Running (PID {pid})[/green]")
        console.print(f"Port: {cfg.proxy.port}")
    else:
        console.print("[red]Status: Not running[/red]")

    # Show stats
    try:
        store = AuditStore()
        allowed, blocked, gray = store.get_stats()
        store.close()

        console.print()
        console.print("[bold]Stats:[/bold]")
        console.print(f"  [green]Allowed:[/green] {allowed}")
        console.print(f"  [red]Blocked:[/red] {blocked}")
        console.print(f"  [yellow]Gray:[/yellow] {gray}")
    except Exception:
        pass


@app.command()
def wrap(agent: str):
    """Patch an agent's config to route through ClawSafe."""
    if agent != "openclaw":
        console.print(f"[red]Unsupported agent: {agent}[/red]")
        console.print("Only 'openclaw' is currently supported")
        raise typer.Exit(1)

    cfg = load_config()
    gateway_path = expand_path(cfg.openclaw.gateway_config)

    if not gateway_path.exists():
        console.print(f"[red]OpenClaw gateway config not found at {gateway_path}[/red]")
        console.print("Make sure OpenClaw is installed and configured")
        raise typer.Exit(1)

    # Read gateway config
    with open(gateway_path) as f:
        gateway = yaml.safe_load(f) or {}

    # Get tools section
    tools = gateway.get("tools", {})
    if not isinstance(tools, dict):
        tools = {}
        gateway["tools"] = tools

    # Check if already wrapped
    if "_clawsafe_original" in tools:
        console.print("[yellow]OpenClaw is already wrapped with ClawSafe[/yellow]")
        return

    # Store original and patch
    original_endpoint = tools.get("endpoint", "https://api.openclaw.ai/tools")
    tools["_clawsafe_original"] = original_endpoint
    tools["endpoint"] = f"http://localhost:{cfg.proxy.port}"

    # Save gateway config
    with open(gateway_path, "w") as f:
        yaml.dump(gateway, f, default_flow_style=False)

    # Update ClawSafe config
    cfg.openclaw.original_endpoint = original_endpoint
    save_config(cfg)

    console.print("[green]OpenClaw wrapped with ClawSafe[/green]")
    console.print(f"   Original endpoint saved: {original_endpoint}")
    console.print(f"   Now routing through: localhost:{cfg.proxy.port}")


@app.command()
def unwrap():
    """Restore original agent config."""
    cfg = load_config()
    gateway_path = expand_path(cfg.openclaw.gateway_config)

    if not gateway_path.exists():
        console.print("[yellow]Gateway config not found[/yellow]")
        return

    with open(gateway_path) as f:
        gateway = yaml.safe_load(f) or {}

    tools = gateway.get("tools", {})

    if "_clawsafe_original" not in tools:
        console.print("[yellow]OpenClaw is not wrapped with ClawSafe[/yellow]")
        return

    # Restore original
    original = tools.pop("_clawsafe_original")
    tools["endpoint"] = original

    with open(gateway_path, "w") as f:
        yaml.dump(gateway, f, default_flow_style=False)

    # Clear from ClawSafe config
    cfg.openclaw.original_endpoint = ""
    save_config(cfg)

    console.print("[green]OpenClaw unwrapped[/green]")
    console.print(f"   Restored endpoint: {original}")


@app.command()
def logs(limit: int = typer.Option(20, "--limit", "-n", help="Number of events to show")):
    """Show recent audit log."""
    try:
        store = AuditStore()
        events = store.get_recent_events(limit)
        store.close()
    except Exception as e:
        console.print(f"[red]Failed to open audit store: {e}[/red]")
        raise typer.Exit(1)

    if not events:
        console.print("[yellow]No events recorded yet[/yellow]")
        return

    console.print("[bold]Recent Events:[/bold]")
    console.print()

    for event in events:
        if event.verdict == "allow":
            icon = "[green]ALLOW[/green]"
        elif event.verdict == "block":
            icon = "[red]BLOCK[/red]"
        else:
            icon = "[yellow]GRAY[/yellow]"

        ts = event.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        console.print(f"{icon} {ts} {event.tool}")

        if event.reason:
            console.print(f"      {event.reason}")

        # Show key arguments
        try:
            args = json.loads(event.arguments)
            if args:
                arg_strs = []
                for k, v in list(args.items())[:3]:
                    if isinstance(v, list):
                        arg_strs.append(f"{k}=[{len(v)} items]")
                    elif isinstance(v, str) and len(v) > 20:
                        arg_strs.append(f"{k}={v[:17]}...")
                    else:
                        arg_strs.append(f"{k}={v}")
                console.print(f"      Args: {', '.join(arg_strs)}")
        except json.JSONDecodeError:
            pass

        console.print()


# ============== Setup Commands ==============

@app.command("setup-telegram")
def setup_telegram():
    """Set up Telegram notifications."""
    import asyncio

    console.print("[bold]Telegram Setup[/bold]")
    console.print()
    console.print("To receive notifications, you need:")
    console.print("  1. A Telegram bot (create one via @BotFather)")
    console.print("  2. Your chat ID (send /start to your bot, then check)")
    console.print()

    bot_token = Prompt.ask("Bot token (from @BotFather)")

    # Test the token
    bot = TelegramBot(bot_token=bot_token)
    success, message = asyncio.run(bot.test_connection())

    if not success:
        console.print(f"[red]Failed to connect: {message}[/red]")
        raise typer.Exit(1)

    console.print(f"[green]{message}[/green]")
    console.print()

    console.print("Now send any message to your bot, then enter your chat ID.")
    console.print("[dim]To find your chat ID: send a message to the bot, then visit:[/dim]")
    console.print(f"[dim]https://api.telegram.org/bot{bot_token}/getUpdates[/dim]")
    console.print()

    chat_id = Prompt.ask("Chat ID")

    # Save config
    cfg = load_config()
    cfg.notifications.telegram.bot_token = bot_token
    cfg.notifications.telegram.chat_id = chat_id
    save_config(cfg)

    # Test sending a message
    bot = TelegramBot(bot_token=bot_token, chat_id=chat_id)
    sent = asyncio.run(bot.send_message("ClawSafe connected! You'll receive notifications here."))

    if sent:
        console.print()
        console.print("[green]Telegram configured successfully![/green]")
        console.print("You should have received a test message.")
    else:
        console.print()
        console.print("[yellow]Config saved, but test message failed.[/yellow]")
        console.print("Check your chat ID and try again.")


@app.command("doctor")
def doctor():
    """Check ClawSafe configuration and connectivity."""
    import asyncio

    console.print("[bold]ClawSafe Doctor[/bold]")
    console.print()

    cfg = load_config()
    all_ok = True

    # Check config file
    from .config import config_path
    path = config_path()
    if path.exists():
        console.print(f"[green]Config file:[/green] {path}")
    else:
        console.print(f"[yellow]Config file:[/yellow] Not found (using defaults)")

    # Check proxy
    pid_file = get_pid_file()
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)
            console.print(f"[green]Proxy:[/green] Running (PID {pid}) on port {cfg.proxy.port}")
        except (ProcessLookupError, ValueError):
            console.print("[yellow]Proxy:[/yellow] Not running (stale PID file)")
            all_ok = False
    else:
        console.print("[yellow]Proxy:[/yellow] Not running")

    # Check Telegram
    if cfg.notifications.telegram.bot_token:
        bot = TelegramBot()
        success, message = asyncio.run(bot.test_connection())
        if success:
            console.print(f"[green]Telegram:[/green] {message}")
        else:
            console.print(f"[red]Telegram:[/red] {message}")
            all_ok = False
    else:
        console.print("[dim]Telegram:[/dim] Not configured")

    # Check audit database
    try:
        store = AuditStore()
        allowed, blocked, gray = store.get_stats()
        store.close()
        console.print(f"[green]Audit DB:[/green] {allowed + blocked + gray} events recorded")
    except Exception as e:
        console.print(f"[red]Audit DB:[/red] Error - {e}")
        all_ok = False

    # Check custom rules
    custom_rules = load_custom_rules()
    if custom_rules:
        enabled = sum(1 for r in custom_rules if r.enabled)
        console.print(f"[green]Custom rules:[/green] {len(custom_rules)} total, {enabled} enabled")
    else:
        console.print("[dim]Custom rules:[/dim] None")

    console.print()
    if all_ok:
        console.print("[green]All checks passed![/green]")
    else:
        console.print("[yellow]Some issues found. See above for details.[/yellow]")


# ============== Rules Commands ==============

@rules_app.callback(invoke_without_command=True)
def rules_list(ctx: typer.Context):
    """List all rules (built-in and custom)."""
    if ctx.invoked_subcommand is not None:
        return

    cfg = load_config()
    custom_rules = load_custom_rules()

    # Built-in rules table
    console.print("[bold]Built-in Rules:[/bold]")
    console.print()

    table = Table(show_header=True, header_style="bold")
    table.add_column("Name", style="cyan")
    table.add_column("Type", width=6)
    table.add_column("Description")
    table.add_column("Tools")

    for rule in BUILTIN_RULES:
        type_style = "[red]BLOCK[/red]" if rule["type"] == "block" else "[yellow]GRAY[/yellow]"
        tools = ", ".join(rule["tools"][:3])
        if len(rule["tools"]) > 3:
            tools += f" (+{len(rule['tools']) - 3})"
        table.add_row(rule["name"], type_style, rule["description"], tools)

    console.print(table)
    console.print()

    # Custom rules
    if custom_rules:
        console.print("[bold]Custom Rules:[/bold]")
        console.print()

        table = Table(show_header=True, header_style="bold")
        table.add_column("Name", style="cyan")
        table.add_column("Type", width=6)
        table.add_column("Enabled", width=8)
        table.add_column("Reason")
        table.add_column("Tools")

        for rule in custom_rules:
            type_style = "[red]BLOCK[/red]" if rule.action == Verdict.BLOCK else "[yellow]GRAY[/yellow]"
            enabled = "[green]Yes[/green]" if rule.enabled else "[dim]No[/dim]"
            tools = ", ".join(rule.tools[:3]) if rule.tools else "[dim]any[/dim]"
            if len(rule.tools) > 3:
                tools += f" (+{len(rule.tools) - 3})"
            table.add_row(rule.name, type_style, enabled, rule.reason[:40], tools)

        console.print(table)
    else:
        console.print("[dim]No custom rules defined.[/dim]")
        console.print("[dim]Use 'clawsafe rules add' to create one.[/dim]")

    console.print()
    console.print(f"[dim]Rules file: {rules_file_path()}[/dim]")


@rules_app.command("add")
def rules_add(
    file: Path = typer.Option(None, "--file", "-f", help="Add rule from YAML file"),
):
    """Add a new custom rule (interactive or from file)."""
    if file:
        # Load from file
        if not file.exists():
            console.print(f"[red]File not found: {file}[/red]")
            raise typer.Exit(1)

        with open(file) as f:
            data = yaml.safe_load(f)

        if "rules" in data:
            # Multiple rules in file
            for rule_data in data["rules"]:
                _add_rule_from_dict(rule_data)
        else:
            # Single rule
            _add_rule_from_dict(data)

        console.print("[green]Rules added successfully[/green]")
        return

    # Interactive mode
    console.print("[bold]Create a new rule[/bold]")
    console.print()

    # Rule name
    name = Prompt.ask("Rule name", default="my_rule")

    # Tools to match
    console.print()
    console.print("[dim]Which tool(s) should this rule match?[/dim]")
    console.print("[dim]Enter comma-separated tool names, or leave blank for all tools[/dim]")
    tools_input = Prompt.ask("Tools", default="")
    tools = [t.strip() for t in tools_input.split(",") if t.strip()]

    # Conditions
    console.print()
    console.print("[bold]Argument conditions[/bold]")
    console.print("[dim]Define conditions on tool arguments. Leave blank to skip.[/dim]")
    console.print()
    console.print("Available operators:")
    console.print("  equals, not_equals, contains, not_contains")
    console.print("  startswith, endswith, matches (regex)")
    console.print("  gt, gte, lt, lte (numbers)")
    console.print("  in, not_in (lists)")
    console.print()

    conditions = {}
    while True:
        arg_name = Prompt.ask("Argument name (or Enter to finish)", default="")
        if not arg_name:
            break

        console.print("Operators: equals, contains, startswith, gt, lt, in, matches")
        operator = Prompt.ask("Operator", default="contains")
        value = Prompt.ask("Value")

        # Parse value
        try:
            # Try to parse as JSON for lists/numbers
            parsed_value = json.loads(value)
        except json.JSONDecodeError:
            parsed_value = value

        conditions[arg_name] = {operator: parsed_value}

    # Action
    console.print()
    action_str = Prompt.ask("Action", choices=["block", "gray"], default="block")
    action = Verdict.BLOCK if action_str == "block" else Verdict.GRAY

    # Reason
    reason = Prompt.ask("Reason message", default=f"Blocked by {name} rule")

    # Create and save rule
    rule = CustomRule(
        name=name,
        tools=tools,
        conditions=conditions,
        action=action,
        reason=reason,
        enabled=True,
    )
    add_custom_rule(rule)

    console.print()
    console.print(f"[green]Rule '{name}' added successfully![/green]")
    console.print()

    # Show the YAML
    console.print("[dim]Added to ~/.clawsafe/rules.yaml:[/dim]")
    rule_yaml = {
        "name": name,
        "match": {"tools": tools, "arguments": conditions} if tools or conditions else {},
        "action": action.value,
        "reason": reason,
    }
    console.print(f"[dim]{yaml.dump(rule_yaml, default_flow_style=False)}[/dim]")


def _add_rule_from_dict(data: dict):
    """Add a rule from a dictionary."""
    tools = data.get("match", {}).get("tools", [])
    if isinstance(tools, str):
        tools = [tools]

    action_str = data.get("action", "block").lower()
    action = Verdict.BLOCK if action_str == "block" else Verdict.GRAY

    rule = CustomRule(
        name=data.get("name", "unnamed"),
        tools=tools,
        conditions=data.get("match", {}).get("arguments", {}),
        action=action,
        reason=data.get("reason", "custom rule triggered"),
        enabled=data.get("enabled", True),
        priority=data.get("priority", 0),
    )
    add_custom_rule(rule)
    console.print(f"  Added rule: {rule.name}")


@rules_app.command("edit")
def rules_edit():
    """Open rules file in your default editor."""
    path = rules_file_path()

    # Create file with example if it doesn't exist
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        example = """# ClawSafe Custom Rules
# See documentation at https://clawsafe.dev/docs/rules

rules:
  # Example: Block database queries to production
  # - name: block_prod_db
  #   match:
  #     tools: [db_query, sql_execute]
  #     arguments:
  #       host:
  #         contains: "prod"
  #   action: block
  #   reason: "Production database access blocked"

  # Example: Flag large file uploads for review
  # - name: review_large_uploads
  #   match:
  #     tools: [file_upload]
  #     arguments:
  #       size_mb:
  #         gt: 100
  #   action: gray
  #   reason: "Large file upload - please confirm"
"""
        path.write_text(example)

    # Get editor
    editor = os.environ.get("EDITOR", os.environ.get("VISUAL", "nano"))

    console.print(f"[dim]Opening {path} in {editor}...[/dim]")
    subprocess.run([editor, str(path)])


@rules_app.command("remove")
def rules_remove(name: str):
    """Remove a custom rule by name."""
    if remove_custom_rule(name):
        console.print(f"[green]Rule '{name}' removed[/green]")
    else:
        console.print(f"[red]Rule '{name}' not found[/red]")
        raise typer.Exit(1)


@rules_app.command("enable")
def rules_enable(name: str):
    """Enable a custom rule."""
    if set_rule_enabled(name, True):
        console.print(f"[green]Rule '{name}' enabled[/green]")
    else:
        console.print(f"[red]Rule '{name}' not found[/red]")
        raise typer.Exit(1)


@rules_app.command("disable")
def rules_disable(name: str):
    """Disable a custom rule."""
    if set_rule_enabled(name, False):
        console.print(f"[yellow]Rule '{name}' disabled[/yellow]")
    else:
        console.print(f"[red]Rule '{name}' not found[/red]")
        raise typer.Exit(1)


@rules_app.command("test")
def rules_test(
    tool: str = typer.Argument(..., help="Tool name to test"),
    args: str = typer.Option("{}", "--args", "-a", help="JSON arguments"),
):
    """Test rules against a sample tool call."""
    try:
        arguments = json.loads(args)
    except json.JSONDecodeError as e:
        console.print(f"[red]Invalid JSON arguments: {e}[/red]")
        raise typer.Exit(1)

    cfg = load_config()
    engine = RuleEngine(RuleConfig(
        bulk_delete_limit=cfg.rules.bulk_delete_limit,
        bulk_send_limit=cfg.rules.bulk_send_limit,
        allow_shell_exec=cfg.rules.allow_shell_exec,
    ))

    call = ToolCall(tool=tool, arguments=arguments)
    decision = engine.evaluate(call)

    console.print()
    console.print(f"[bold]Tool:[/bold] {tool}")
    console.print(f"[bold]Arguments:[/bold] {json.dumps(arguments, indent=2)}")
    console.print()

    if decision.verdict == Verdict.ALLOW:
        console.print("[green]Result: ALLOW[/green]")
    elif decision.verdict == Verdict.BLOCK:
        console.print("[red]Result: BLOCK[/red]")
    else:
        console.print("[yellow]Result: GRAY (needs review)[/yellow]")

    console.print(f"[bold]Rule:[/bold] {decision.rule or 'none'}")
    console.print(f"[bold]Reason:[/bold] {decision.reason}")


# ============== Autostart Commands ==============

@autostart_app.command("enable")
def autostart_enable_cmd():
    """Enable ClawSafe to start automatically on boot."""
    success, message = autostart_enable()

    if success:
        console.print(f"[green]{message}[/green]")
    else:
        console.print(f"[red]{message}[/red]")
        raise typer.Exit(1)


@autostart_app.command("disable")
def autostart_disable_cmd():
    """Disable auto-start on boot."""
    success, message = autostart_disable()

    if success:
        console.print(f"[green]{message}[/green]")
    else:
        console.print(f"[red]{message}[/red]")
        raise typer.Exit(1)


@autostart_app.command("status")
def autostart_status_cmd():
    """Check auto-start status."""
    enabled, message = autostart_status()

    if enabled:
        console.print(f"[green]{message}[/green]")
    else:
        console.print(f"[yellow]{message}[/yellow]")


if __name__ == "__main__":
    app()
