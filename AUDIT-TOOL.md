# Audit Trail Investigation and Forensic Tool

The audit trail tool lets you inspect the bot's JSONL event stream for state transitions, trade records, alerts, and operational events. It is designed for post-mortem review, incident analysis, and runtime debugging.

## What is recorded

The bot writes structured records to the configured audit log path (default: a temp file, or the path set with `PUMPFUN_AUDIT_LOG`). Each line is a JSON object containing:

- `timestamp`: Unix time when the record was written
- `type`: record category (`trade`, `state_transition`, `event`, `metric`)
- `state`: the bot state at the time of the record
- `payload`: the record-specific details

Trade records include:

- `trade_id`
- `position_id`
- `action` (`buy` / `sell`)
- `mint`
- `entry`
- `exit`
- `reason`

State transition records include:

- previous state
- new state
- transition reason

Event records include:

- a human-readable message payload

## CLI usage

The tool is exposed through the package CLI entry point:

```bash
pumpbot audit --path /path/to/audit.jsonl
```

### Filtering

```bash
pumpbot audit --path /path/to/audit.jsonl --record-type trade
pumpbot audit --path /path/to/audit.jsonl --state holding
pumpbot audit --path /path/to/audit.jsonl --mint <mint-address>
pumpbot audit --path /path/to/audit.jsonl --reason take_profit
pumpbot audit --path /path/to/audit.jsonl --status success
pumpbot audit --path /path/to/audit.jsonl --date-from 2026-01-01 --date-to 2026-01-31
```

### Summary output

```bash
pumpbot audit --path /path/to/audit.jsonl --summary
```

This prints aggregate counts by:

- record type
- state
- reason
- status

### JSON output

```bash
pumpbot audit --path /path/to/audit.jsonl --json
```

This emits the filtered records as pretty JSON.

### Exporting results

```bash
pumpbot audit --path /path/to/audit.jsonl --reason risk_kill --export ./risk_kill.json
```

This writes the filtered set to a JSON file for later review, automation, or sharing.

### Table output

If you do not specify `--summary`, `--json`, or `--export`, the tool renders a Rich table with:

- time
- record type
- state
- mint
- reason
- status

## Example workflow

```bash
# See all bot activity for a mint
pumpbot audit --path .data/pumpfun_trading_audit.jsonl --mint So11111111111111111111111111111111111111112

# Inspect only exit events
pumpbot audit --path .data/pumpfun_trading_audit.jsonl --record-type trade --reason take_profit

# Produce a summary of recent system health events
pumpbot audit --path .data/pumpfun_trading_audit.jsonl --summary
```

## Operational value

This tool is useful when you need to:

- investigate a failed trade or unexpected exit reason
- confirm whether a bot state transition happened as expected
- audit recent failures and retries
- review a mint-specific decision history
- export a filtered record set for incident analysis

## Configuration

The bot reads the audit path from the environment variable:

```bash
export PUMPFUN_AUDIT_LOG="${PWD}/.data/pumpfun_trading_audit.jsonl"
```

You can also pass an explicit path when constructing the bot or when running the CLI.

