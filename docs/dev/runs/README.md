# Run records

A run record is the file that fixes, **before a run starts**, what the run
is for and how it will be judged, and then holds its read-out when it ends.
One file per run, named after the run: `pump-12.md` for the run `pump-12`.
The format is trading-core's `docs/dev/DOCUMENTATION.md` §8.2.

## 1. What goes in a record

```markdown
# Run pump-12

## Pre-registration (written YYYY-MM-DD HH:MM UTC, before the start)
- Question: what the run decides, in one sentence
- Code: trading-core vA.B.C (<commit>), trading-pump vX.Y.Z (<commit>)
- Config: configs/pump-12.json, sha256 <hash>
- Verdict rules: one file per lane, sha256 <hash> each, with the rule in words
- Started: <UTC>; planned end: <UTC>
- Stage: the stage each lane is at, and what GO and NO-GO lead to

## Read-out (added at the end)
- Ran: <UTC> to <UTC>; gaps: none, or what and why
- Per lane: positions, net, win rate, verdict (GO / NO-GO / INCONCLUSIVE) and the checks that failed
- What it means, and what happens next
```

- **The pre-registration is committed before the start and never edited
  after.** A mistake found later is a new dated line under it, not an edit.
  Take the hashes in the runtime folder:
  `shasum -a 256 configs/pump-12.json configs/verdict-pump-12-*.json`.
- **The read-out is added when the run ends**, from
  `trading-core-audit verdict` and `trading-core-audit pnl` on the run's
  audit trail ([`RUNBOOK.md` §3](../RUNBOOK.md#3-a-paper-run-that-counts)).
  The same numbers go into a new section of
  [`RESULTS.md`](../RESULTS.md) and the record links it.
- **Names** follow the standard's §7: `pump-<n>` for a run of the lanes,
  counting on from rc.11 (the next counted run is `pump-12`), or what a
  record-only run is for (`pools-1`). A number is never reused, even for a
  run that was stopped. Names given before 2026-10-31 (rc.9, rc.11,
  rc.11-tp20) stay as they were.

## 2. Which runs get one

| Kind | Record | Verdict |
|---|---|---|
| **Counted run**: pre-registered, from tagged code, unchanged while it runs | Always | GO, NO-GO or INCONCLUSIVE per lane |
| **Exploratory run**: started to measure something, not pre-registered in time | When it is worth finding again; the record says why it is not counted | None |
| **Record-only run**: every lane off, only the capture | When its data will be read out; the record says what it records | None |
| **Smoke run**: about 30 minutes, checks a runtime sees live data | No (the release record says it passed) | None |

## 3. The records

| Run | Kind | Code | Started (UTC) | Record |
|---|---|---|---|---|
| v0.2.0 Stage 0 pilot (pumpbot) | Counted, paper | pumpfun-trading `v0.2.0` | 2026-10-16 | [`v0.2.0-stage0.md`](v0.2.0-stage0.md) |
| v0.2.1 Stage 0 pilot (pumpbot) | Counted, paper | pumpfun-trading `v0.2.1` | 2026-10-17 | [`v0.2.1-stage0.md`](v0.2.1-stage0.md) |
| rc.11 | Counted, paper, both lanes | `v0.4.0rc4` on trading-core `v0.2.2` | 2026-10-30 18:58:56 | [`rc11.md`](rc11.md) |
| rc.11-tp20 | Exploratory, paper | `v0.4.0rc4` on trading-core `v0.2.2` | 2026-10-31 06:00:15 | [`rc11-tp20.md`](rc11-tp20.md) |
| pools-1 | Record-only | `v0.4.0rc5` on trading-core `v0.2.2` | 2026-10-31 07:29:11 | [`pools-1.md`](pools-1.md) |

The two pumpbot pilot logs moved here from `releases/` on 2026-10-31,
unedited. They were written as running checkpoint logs, not in this format,
and their "Stage 0" is the paper stage, now Stage 1
([`RELEASE-GATE.md` §3](../RELEASE-GATE.md#3-capital-gate)).

The runs before rc.11 on the new stack (rc.9 on `v0.4.0rc2`, rc.10 on
`v0.4.0rc3`) have no file here: their pre-registration is in their
`CHANGELOG.md` release records and their read-out in
[`RESULTS.md` §6.19](../RESULTS.md#619-rc9-and-rc10-stopped-early-why-the-instant-lane-crashed-2026-10-31).
pumpfun-trading's rc.1 to rc.8 runs are in `RESULTS.md` §6.3–§6.13.
