# ClawSafe

Reversibility firewall for AI agents.

## Install

```bash
pip install clawsafe
```

## Usage

```bash
clawsafe start          # Start proxy daemon
clawsafe stop           # Stop proxy daemon
clawsafe status         # Show status and stats
clawsafe wrap openclaw  # Route OpenClaw through ClawSafe
clawsafe unwrap         # Restore original config
clawsafe logs           # Show recent audit log
clawsafe rules          # Show active rules
```
