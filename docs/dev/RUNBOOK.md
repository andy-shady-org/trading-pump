# Operations Runbook

This runbook covers the release gates for a controlled production-ready bot deployment. The project is not a public launch target yet; use this as the operational checklist before running live or funded workflows.

## 1. Preflight checks

- Confirm the wallet private key is present in a secure environment source and not committed to source control.
- Confirm `PUMPFUN_RPC_URL` and any alert/webhook configuration are populated only in local or deployment-managed env files.
- Verify the bot is running in a safe mode for the first deployment window (dry-run or paper mode when possible).
- Confirm the audit log and bot status paths are writable and backed up by the host environment.
- Validate `PUMPFUN_ALERT_PROVIDER` is set only when the required secret values are present.

## 2. Startup procedure

1. Load environment variables from a secure secret manager or local `.envrc` that is excluded from version control.
2. Start the bot using the supported CLI or `TradingBot.from_env()`.
3. Verify startup logs show:
   - logger initialized
   - bot startup configuration
   - health state initialized
4. Confirm the JSON status snapshot is created and contains the current state, recent events, and active positions.
5. Verify the audit log is receiving state and trade entries.

## 3. Normal runtime checks

- Monitor the bot status snapshot for state transitions, health flags, and wallet reserve guard status.
- Watch for disconnect/reconnect loops and stale-data or RPC failures.
- Review recent trade logs and account health before letting the bot remain active for extended periods.
- Keep an eye on rate limit and timeout recoveries from the API client and market-data service.

## 4. Shutdown / emergency stop

- Trigger an orderly shutdown by sending SIGINT or SIGTERM.
- Confirm the bot writes final state and audit events before exit.
- If abnormal behavior is detected, stop the process immediately and preserve the audit trail and status snapshot for review.
- In a no-connection or stuck-state scenario, restart only after verifying the logged failure reason and status snapshot.

## 5. Incident response

If the bot fails a safety gate or produces unexpected trade activity:

1. Halt the process immediately.
2. Review the audit log and bot status snapshot for the last valid state transition and event.
3. Verify wallet balance, reserve thresholds, and active positions before resuming.
4. Re-check environment variables, RPC access, and alert configuration.
5. Only restart in dry-run or paper mode until the issue is resolved.

## 6. Deployment hardening checklist

- Use a minimal privilege runtime account.
- Keep secrets in a dedicated secret manager, not in code or tracked config files.
- Separate the hot wallet from treasury or operational wallet controls.
- Require operator review before any production action outside a dry-run or test environment.
- Keep the bot status snapshot and audit log in a monitored filesystem path.

## 7. Release gate summary

The following release gates must be passed before a live-funds launch:

- environment and secret validation passes
- structured logging is active and reviewable
- status snapshot and audit trail are available
- health and risk kill switches are verified
- alerting path is configured and tested
- replay/backtest validation demonstrates acceptable risk-adjusted behavior
- security review confirms secrets and wallet isolation are in place

