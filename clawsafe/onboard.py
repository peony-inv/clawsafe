"""
ClawSafe onboarding sequence.
The molting sequence is a brand moment — make it feel alive.
"""

import time
from rich.console import Console

console = Console()

STEPS = [
    (0.0,  "\U0001F99E", "molting the shell..."),
    (0.7,  "\U0001F50D", "sniffing for claws..."),
    (1.4,  "\U0001FA24", "laying the trap..."),
    (2.1,  "\U0001F6E1\uFE0F",  "hardening the carapace..."),
    (2.8,  "\u26D3\uFE0F",  "chaining the rules..."),
    (3.5,  "\U0001F30A", "testing the tides..."),
]


def run_molting_sequence() -> None:
    """Display the molting animation sequence."""
    console.print()
    start = time.time()

    for delay, emoji, message in STEPS:
        elapsed = time.time() - start
        if delay > elapsed:
            time.sleep(delay - elapsed)
        console.print(f"  {emoji}  [dim]{message}[/dim]")

    time.sleep(0.5)
    console.print()
    console.print("  [bold green]\u2705  shell secured. claw safe.[/bold green]")
    console.print()
