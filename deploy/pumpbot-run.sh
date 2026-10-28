#!/usr/bin/env bash
# Starts pumpbot headless from a runtime directory (Sprint 24D, RUNBOOK §8).
#
# Used by the systemd unit and the launchd agent in this folder. Copy it into the
# runtime directory next to `.envrc` (chmod 700). The `.envrc` is sourced with
# `set -a`, so lines with or without `export` both reach the bot.
#
#   PUMPBOT_RUNTIME_DIR  runtime directory (default: this script's directory)
#   PUMPBOT_BIN          pumpbot executable (default: pumpbot on PATH)
#   PUMPBOT_CONFIG       config file (default: configs/canary.json)
#   PUMPBOT_EXTRA_ARGS   extra flags, e.g. "--paper-trade --record-replay data/replay_capture.jsonl"
set -euo pipefail

RUNTIME_DIR="${PUMPBOT_RUNTIME_DIR:-$(cd "$(dirname "$0")" && pwd)}"
cd "$RUNTIME_DIR"

if [[ ! -f .envrc ]]; then
  echo "pumpbot-run: no .envrc in $RUNTIME_DIR" >&2
  exit 78  # EX_CONFIG: systemd/launchd will not hot-loop on a missing file
fi
set -a
# shellcheck disable=SC1091
source ./.envrc
set +a

mkdir -p data
# shellcheck disable=SC2086
exec "${PUMPBOT_BIN:-pumpbot}" \
  --config "${PUMPBOT_CONFIG:-configs/canary.json}" \
  --headless ${PUMPBOT_EXTRA_ARGS:-}
