# Audit Trail Investigation and Forensic Tool

> **Navigation**: [User Guide](USER-GUIDE.md) | [Financial Strategy](STRATEGY.md) | [Risk Controls](RISK.md) | [Terminal UI](TERMINAL-UI.md) | [Web UI](WEB-UI.md) | [Feature Catalog](FEATURES.md) | [Replay Engine](REPLAY-ENGINE.md)

The audit trail tool lets you inspect the bot's JSONL event stream for state transitions, trade records, alerts, and operational events. It is designed for post-mortem review, incident analysis, and runtime debugging.

## What is recorded

The bot writes structured records to the configured audit log path (default: a temp file, or the path set with `PUMPFUN_AUDIT_LOG`). Each line is a JSON object containing:

- `timestamp`: Unix time when the record was written
- `type`: record category (`trade`, `state_transition`, `event`, `metric`, `run_started`)
- `state`: the bot state at the time of the record
- `payload`: the record-specific details

Trade records include:

- `trade_id`
- `position_id`
- `action` (`buy` / `sell` / `reconciled_closed`)
- `mint_name` / `token_name`
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

Run records (`run_started`, FEAT-68, one per start) hold the run's provenance stamp: `package_version`, `git_commit` / `git_branch` / `git_dirty` / `git_source`, `mode`, `strategy_preset`, `entry_mode`, `config_path`, `config_file_sha256`, `config_sha256` (effective config, URLs redacted), `fee_model_bps`, `fee_launch_bps`, `fee_tiers`, `cost_env` (Jito switches and tip sizes only), `python_version`, `platform`, `pid` and `started_at` / `started_at_utc`. List them with `pumpfun-audit --path audit_trail.jsonl --record-type run_started --json`, and copy the commit and hashes into the release record.

## CLI usage

The tool is exposed through the dedicated `pumpfun-audit` CLI entry point:

```bash
pumpfun-audit --path /path/to/audit.jsonl
```

### Filtering

```bash
pumpfun-audit --path /path/to/audit.jsonl --record-type trade
pumpfun-audit --path /path/to/audit.jsonl --state holding
pumpfun-audit --path /path/to/audit.jsonl --mint <mint-address>
pumpfun-audit --path /path/to/audit.jsonl --mint-name <token-name>
pumpfun-audit --path /path/to/audit.jsonl --token-name <token-name>
pumpfun-audit --path /path/to/audit.jsonl --reason take_profit
pumpfun-audit --path /path/to/audit.jsonl --status success
pumpfun-audit --path /path/to/audit.jsonl --date-from 2026-01-01 --date-to 2026-01-31
pumpfun-audit --path /path/to/audit.jsonl --limit 50
```

### Summary output

```bash
pumpfun-audit --path /path/to/audit.jsonl --summary
```

This prints aggregate counts by:

- record type
- state
- reason
- status

### JSON output

```bash
pumpfun-audit --path /path/to/audit.jsonl --json
```

This emits the filtered records as pretty JSON.

### Exporting results

```bash
pumpfun-audit --path /path/to/audit.jsonl --reason risk_kill --export ./risk_kill.json
```

This writes the filtered set to a JSON file for later review, automation, or sharing.

### Table output

If you do not specify `--summary`, `--json`, or `--export`, the tool renders a Rich table with:

- Time
- Type
- State
- Mint Name
- Mint
- Reason
- Status

### Net PnL and entry rules

```bash
# Net PnL per lane, and per UTC hour of the buy (time-of-day check)
pumpfun-audit pnl --path capture/audit_trail.jsonl --group-by strategy
pumpfun-audit pnl --path capture/audit_trail.jsonl --group-by hour

# Would a filter on the recorded entry metrics have helped? (random-cut test)
pumpfun-audit cuts --path capture/audit_trail.jsonl --strategy momentum \
  --split-at mid --keep 'top_buyer_share<0.3'
```

`cuts` compares the net of the closed positions a rule keeps with the same share of all positions' net, in each half of the run. A rule shows an edge only when it beats that random cut in both halves. For a trail written before v0.3.0-rc.2, add `--capture capture/replay_capture.jsonl` to rebuild the FEAT-55/56/57 metrics (`top_buyer_share`, `wallet_diversity`, `round_trip_share`, `quick_flips`, `early_sol`, `creator_prior_loss`, …) from the trades recorded before each buy. See [CLI-COMMANDS.md](CLI-COMMANDS.md) (Recipe 5b).

### Go / no-go verdict (FEAT-67)

```bash
pumpfun-audit verdict --path capture/audit_trail.jsonl --rules configs/verdict_rules.json --strategy momentum
```

`verdict` judges a paper run with a rule fixed before the run (`configs/verdict_rules.json`; `bot/verdict.py`), so the result cannot be tuned after the fact. It prints the rule's SHA-256: record it in the release record when the run starts and check it matches at the verdict.

Every closed position's net (buy plus sells, all recorded fees, tips and rent) is adjusted for what paper does not pay: `exit_haircut_bps` of each sell's proceeds (a margin on top of `paper_exit_slippage_bps`) and a top-up of every transaction's tip to `tip_lamports`. The run is **GO** only when every check passes:

| Check | Passes when | Rule keys |
| :--- | :--- | :--- |
| `min_positions` | at least this many closed positions | `min_positions` (100) |
| `net_positive` | adjusted net above the minimum | `min_net_sol` (0) |
| `halves_positive` | both halves (by entry time) positive | `split_at` (`mid`, a Unix time, or `null` for no split) |
| `positive_days` | share of UTC days with a positive adjusted net | `min_positive_day_share` (0.5) |
| `without_top_winners` | still positive without the best positions | `drop_top` (3) |
| `bootstrap_lower_bound` | the lower bound of the bootstrap interval of the mean per position is above 0 | `bootstrap_samples` (10,000), `confidence` (0.90, two-sided), `seed` (7) |

The report also lists per-day nets and the net without the best 0–5 positions. `--json` prints it all; the exit code is 0 on GO, 1 on NO-GO and 2 on a bad rule. Judge each lane on its own with `--strategy` (or a `strategy` key in the rule file). Command-line overrides (`--exit-haircut-bps`, `--drop-top`, …) change the hash, so they show up as a different rule. Full flag list: [`CLI-COMMANDS.md` §5](CLI-COMMANDS.md#5-forensic-audit-inspector-pumpfun-audit--pumpfun-audit).

## Example workflow

```bash
# See all bot activity for a mint
pumpfun-audit --path .data/pumpfun_trading_audit.jsonl --mint So11111111111111111111111111111111111111112

# Filter activity by mint / token name
pumpfun-audit --path .data/pumpfun_trading_audit.jsonl --mint-name SolCat

# Inspect only exit events
pumpfun-audit --path .data/pumpfun_trading_audit.jsonl --record-type trade --reason take_profit

# Produce a summary of recent system health events
pumpfun-audit --path .data/pumpfun_trading_audit.jsonl --summary
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

