#!/usr/bin/env bash
# Daily wallet reconciliation for the supervised bot (Sprint 24D, RUNBOOK §5.3).
#
# Writes data/reconcile_status.json; the running bot reads it, shows it on the
# dashboard and alerts on a GAP. Exit code 1 on a gap, so the timer shows failed.
#
#   PUMPBOT_RUNTIME_DIR    runtime directory (default: this script's directory)
#   PUMPBOT_AUDIT_BIN      pumpfun-audit executable (default: on PATH)
#   PUMPBOT_WALLET         trading wallet public key (required)
#   PUMPBOT_START_BALANCE  optional: wallet SOL at the start of the canary
set -euo pipefail

RUNTIME_DIR="${PUMPBOT_RUNTIME_DIR:-$(cd "$(dirname "$0")" && pwd)}"
cd "$RUNTIME_DIR"
set -a
# shellcheck disable=SC1091
source ./.envrc
set +a

: "${PUMPBOT_WALLET:?set PUMPBOT_WALLET to the trading wallet public key}"
args=(reconcile --path "${PUMPFUN_AUDIT_LOG_PATH:-data/audit_trail.jsonl}" --wallet "$PUMPBOT_WALLET")
if [[ -n "${PUMPBOT_START_BALANCE:-}" ]]; then
  args+=(--start-balance "$PUMPBOT_START_BALANCE")
fi
exec "${PUMPBOT_AUDIT_BIN:-pumpfun-audit}" "${args[@]}"
