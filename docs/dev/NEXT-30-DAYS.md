# Next 30 Days: Execution Plan

This document is the active execution plan for the next 30 days. It complements the historical backlog in `TODO.md` and is intended to drive the next phase of delivery.

## Goal

Bring the project to a validated internal deployment candidate without treating it as a public or funded live-launch system.

This means the project should demonstrate:
- strategy performance across historical data and walk-forward validation
- stable runtime behavior in dry-run or paper mode
- secure configuration and deployment hygiene
- clear operator handoff and incident response procedures

## Scope

In scope for the next 30 days:
- historical and walk-forward validation of strategy logic
- operational readiness and deployment controls
- reproducible operator runbook and release gates
- focused pilot testing in dry-run / paper mode

Out of scope for the next 30 days:
- broad feature expansion
- public release or funded live trading
- large refactors for code cleanliness alone
- non-essential dashboard or UX polishing

## Guiding principle

The project is not yet a public live-trading system. The next 30 days should prove the bot is disciplined, observable, and defensible before any real-money or broader launch step is considered.

## Sprint plan

### Sprint 1: Strategy validation and benchmark proof (Days 1-10)

Objective:
- determine whether the current strategy logic has credible performance before any operational expansion.

Workstreams:
- build a representative historical replay dataset
- run strategy benchmark across multiple market regimes
- capture metrics for win rate, profit factor, max drawdown, average return, and trade count
- run walk-forward / out-of-sample validation
- compare conservative, balanced, and aggressive presets

Key outputs:
- benchmark report
- out-of-sample validation report
- strategy risk-adjusted summary
- decision to continue, tune, or stop the current strategy

Definition of done:
- baseline performance is documented
- at least one out-of-sample validation has been run
- metrics are reviewed with risk-adjusted context, not just raw profit
- a decision is recorded: continue, refine, or stop

Exit criteria:
- strategy is not being advanced on raw profit alone
- known failure modes are documented
- minimum quality thresholds are established before continuing to pilot work

### Sprint 2: Release hardening and deployment readiness (Days 11-20)

Objective:
- tighten the operational controls needed for a controlled internal deployment.

Workstreams:
- final review of environment and secrets handling
- validate audit log retention and review workflow
- confirm health checks, kill-switches, and alerting are active
- verify startup, shutdown, and restart behavior
- complete runbook and incident response steps
- confirm bot status snapshot and metrics file paths are stable and monitored

Key outputs:
- deployment checklist
- runbook for startup / shutdown / restart / emergency stop
- incident response checklist
- signed-off secrets and environment policy

Definition of done:
- operator can start and stop the bot without ambiguity
- emergency actions are documented and repeatable
- alerting and log review are tested
- “no-go” conditions are explicit and documented

Exit criteria:
- the runtime passes operator-level dry-run checks
- each safety gate is documented with expected behavior
- no unreviewed or undocumented secrets or wallet assumptions remain

### Sprint 3: Controlled dry-run / paper pilot (Days 21-30)

Objective:
- prove the system remains stable under realistic conditions without taking real capital risk.

Workstreams:
- run the bot in dry-run or paper mode for a sustained period
- verify reconnects, stale-data handling, and recovery flows
- monitor trade decisions and audit logs for anomalies
- review state restoration and health-check behavior after simulated failures
- perform a lightweight go/no-go review

Key outputs:
- pilot summary report
- incident review notes
- release recommendation
- approval / hold / reject decision

Definition of done:
- the bot remains stable and observable during the pilot window
- failures are handled gracefully and logged
- the team can explain why the run was acceptable or not acceptable

Exit criteria:
- a documented recommendation is made for the next phase
- if the pilot is successful, the next step is a tightly scoped live rehearsal or a controlled dry-run extension
- if the pilot fails, the project reverts to a tuned strategy / operational repair cycle

## Decision gates

The project should not move forward on intuition alone. Use these decision gates:

### Gate 1: Strategy gate
Proceed only if strategy performance is consistent across benchmark and walk-forward checks, with risk-adjusted metrics reviewed.

### Gate 2: Ops gate
Proceed only if startup, shutdown, secret handling, and health checks are documented and repeatable.

### Gate 3: Pilot gate
Proceed only if dry-run or paper mode demonstrates stable behavior under realistic conditions.

## Success metrics

For an internal deployment candidate, the project should show:
- stable trade and lifecycle logging
- no unexplained crashes or state-loss events
- risk guards triggered as expected
- consistent replay / benchmarking behavior
- no operator confusion during startup or shutdown

## Not a release yet

This plan does not authorize a public or funded launch. It is designed to validate the project as a controlled internal candidate with operational discipline and measurable strategy evidence.

## Related reference

- `TODO.md` - historical backlog and completed implementation record
- `RUNBOOK.md` - operational runbook for startup, shutdown, and incident response
- `RELEASE-GATE.md` - release gate checklist and signoff criteria
- `../USER-GUIDE.md` - central user guide and operational portal

