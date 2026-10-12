# Release Gate Checklist

This document defines the release gate for the next stage of the project. It is intentionally strict and conservative.

## Release status

Current intent:
- internal deployment candidate only
- not a public or funded launch
- not a release to end users outside a controlled operational environment

## Required conditions before any controlled launch

### 1. Strategy evidence
- historical benchmark has been run
- walk-forward or out-of-sample validation has been performed
- risk-adjusted metrics have been reviewed, not just raw return
- known strategy failure modes have been documented
- decision to proceed is recorded and signed off

### 2. Runtime safety
- risk limits are active and tested
- health checks are active and documented
- kill-switches are tested
- audit log writes are verified
- bot status snapshots are being written and reviewed

### 3. Environment and security
- secrets are handled via secure environment or secret manager
- no secrets are stored in tracked configuration files
- wallet isolation and approval boundaries are defined
- alerting and incident escalation paths are configured and tested

### 4. Operational readiness
- startup and shutdown are documented
- emergency stop procedures are known to the operator
- runbook has been followed in a test scenario
- restart and recovery logic has been verified

### 5. Pilot readiness
- dry-run or paper mode is the default execution mode for the pilot
- metrics and logs are retained for review
- no-go conditions are explicit
- incident review workflow is in place

## Gate checklist

### Preflight checklist
- [ ] environment variables are set from a secure source
- [ ] wallet keys are not hardcoded or committed
- [ ] bot status path is writable
- [ ] audit path is writable
- [ ] RPC endpoint is reachable and tested
- [ ] alert provider configuration is valid or disabled intentionally

### Runtime checklist
- [ ] bot starts cleanly
- [ ] metrics are updating
- [ ] audit log is writing records
- [ ] status snapshot is being updated
- [ ] risk guards are active
- [ ] stale-data and reconnect behavior is benign or recoverable

### Validation checklist
- [ ] strategy benchmark is completed
- [ ] walk-forward validation is completed
- [ ] known failure cases are documented
- [ ] public release criteria are explicitly not met
- [ ] operator signoff is obtained

### Launch decision checklist
- [ ] project is clearly labeled as internal / controlled deployment only
- [ ] risk team or operator approves launch conditions
- [ ] no-go triggers are documented
- [ ] health and operational review is scheduled
- [ ] launch plan is written and retained

## Go / no-go policy

Go only if:
- strategy evidence is acceptable
- runtime safety is verified
- secure config and wallet handling are in place
- pilot or dry-run run has been stable and reviewed

No-go if:
- strategy performance is not meaningfully validated
- audit trail or safety checks fail
- secret handling is unclear or noncompliant
- health or reconnect behavior is unstable
- operator cannot confidently explain shutdown and incident response

## Release recommendation

This project should be treated as a controlled internal deployment candidate, not a broad public launch, until historical evidence and pilot validation show it is consistently stable and risk-managed.

## Related reference

- `NEXT-30-DAYS.md` - active execution plan for the next 30 days
- `RUNBOOK.md` - operator procedures for runtime operations and incidents
- `TODO.md` - historical backlog and completed implementation record
- `../USER-GUIDE.md` - central user guide and operational portal

