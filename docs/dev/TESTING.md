# Testing

## The gate

```bash
nox -s lint mypy tests          # trading-core comes from ../trading-core by default
```

| Session | Runs | Must |
|---|---|---|
| `lint` (3.14) | `ruff check .`, `black --check .`, `flake8 .` (McCabe complexity ≤ 7) | pass |
| `mypy` (3.14, checks as 3.11) | `mypy` on the package and tests, against trading-core's types (`py.typed`) | no issues |
| `tests-3.11` … `tests-3.14` | `pytest --cov=trading_pump --cov-fail-under=100` | pass with 100% **statement and branch** coverage on every version |
| `tests-fast` | unit and property tests, no coverage | quick loop |
| `format` | `ruff --select I --fix`, `black` | — |
| `audit` | `pip-audit` | no known vulnerability |
| `package` | build; the wheel ships no tests and is `Private :: Do Not Upload` | — |

Every session first installs trading-core from `TRADING_CORE_SOURCE`: a
checkout path (default `../trading-core`) or any pip requirement, e.g.
`TRADING_CORE_SOURCE=git+ssh://git@github.com/andy-shady-org/trading-core.git@main nox -s tests`.
Outside nox, with trading-core installed editable, mypy needs
`MYPYPATH=../trading-core`.

The suite (789 tests) runs in about 10 seconds and **never touches the
network**. pumpbot's suite had 2,208 tests at v0.3.0rc8; the difference is
the retired runtime and lanes (their tests are in the history at that tag,
and the bugs they guarded are accounted for in
[`BUGS.md`](BUGS.md#where-each-fix-lives-after-the-move-to-trading-core)).

## CI

`.github/workflows/tests.yml` checks out this repository **and** the private
`andy-shady-org/trading-core` side by side and runs nox with
`TRADING_CORE_SOURCE` pointing at the checkout. It needs one repository
secret, **`TRADING_CORE_TOKEN`**: a fine-grained personal access token with
*Contents: read* on `andy-shady-org/trading-core`, stored under this
repository's Settings → Secrets and variables → Actions.
`TRADING_CORE_REF` (workflow env, default `main`) picks the trading-core
branch or tag; pin it to a tag for releases.

## Layout

Tests stay inside the package (`trading_pump/tests/`) and are excluded from
the wheel (`MANIFEST.in` prune; checked by `nox -s package`). ADR-008.

```text
trading_pump/tests/
├── conftest.py          markers by directory + isolation, nothing else
├── support/
│   ├── constants.py     SAMPLE_PRIVATE_KEY, SAMPLE_MINT, SAMPLE_PUMP_MINT, WSOL_MINT, curve reserves
│   ├── factories.py     make_screening, make_reading, GRADUATION_BASE_RESERVE / QUOTE_RESERVE
│   ├── fakes.py         FakeClock, FakeRpc, FakeCurves, FakeJito, FakeAlertSink,
│   │                    FakePoolSource (readings, refusals, fee errors), FakeHost (a ModuleHost)
│   └── payloads.py      curve account bytes, real mainnet pool / vault / global-config accounts
├── unit/                one file per source module, mirrored: unit/<pkg>/test_<module>.py
├── integration/
│   └── test_module_plugin.py   entry point; trading-core's engine + this module: a paper buy and
│                               take profit end to end (dashboard, audit, capture, status);
│                               no RPC means no entries (BUG-149)
└── property/
    └── test_curve.py    curve maths: bounds, monotonicity, fees, no free money on a round trip
```

`unit/test_suite_layout.py` enforces:

* a mirrored test for every source module (every depth);
* only `conftest.py` in the tests root, an `__init__.py` in every unit
  package, no coverage-named files (`test_coverage_*`, `*_boost*`, `*_full`);
* every **RESOLVED** bug in `BUGS.md` has a test tagged
  `@pytest.mark.regression("BUG-xx")`, unless `BUGS.md` lists it under
  "Where each fix lives" (trading-core or retired) or it is in
  `KNOWN_UNTAGGED` (shrink-only: BUG-09, BUG-31);
* a tag names a real bug, and a bug tested here is not also listed as
  elsewhere;
* every file parses as the oldest supported Python (`requires-python`'s
  floor).

`test_docs_relative_links_and_anchors_resolve` (same file) fails on a
relative link in any Markdown file, archive included, whose file or heading
does not exist.

`unit/config/test_env.py` fails when `docs/ENVIRONMENT.md` §1 does not list
exactly the variables the code reads, with their aliases, and when a
variable the archived pumpbot manual documented has no replacement hint.

## Isolation (`tests/conftest.py`)

* **No network.** DNS is blocked for every non-local host for the whole
  session, not only inside a test (a background thread can outlive its
  test), and proxy variables are removed, or a client would send the request
  to a local proxy past the guard (BUG-143).
* **No operator shell.** Every `PUMPFUN_*` and `TRADING_CORE_*` variable is
  deleted before each test; set what a test needs with `monkeypatch.setenv`.
* **No stray files.** Every test runs in its own `tmp_path` (it is the
  working directory).
* **No cost RPC.** `PumpFunExecutionClient.get_transaction_costs` fails fast
  unless the test module sets `USES_REAL_TRANSACTION_COSTS = True`.
* **No real backoff.** API and RPC-pool retries still happen and are counted,
  without waiting (`instant_retry_backoff`; opt out with
  `USES_REAL_RETRY_BACKOFF = True`).
* `offline_trade_rpc` stubs the token-program and curve lookups that the
  transaction builders refuse to guess (BUG-68, BUG-69).

## Markers

| Marker | Applied |
|---|---|
| `unit`, `integration`, `property` | automatically, by directory; never by hand |
| `regression("BUG-<n>")` | on the test that guards a fixed bug |
| `slow` | tests that need real waiting (none today) |

`--strict-markers` is on; `asyncio_mode = "auto"`, so no
`@pytest.mark.asyncio`.

## Writing tests

* Drive the module through its public seams: `PumpModule` with a
  `FakePoolSource` and a `FakeHost`, the executors with a `FakePoolSource`
  and a `FakeClock`, the lane with a real `GraduateTracker` fed
  `make_reading(...)`. Nothing reaches mainnet.
* Pin on-chain layouts to real mainnet account bytes (`support/payloads.py`),
  as BUG-123 did, not to bytes the test builds itself.
* Time is injected (`clock=`, `sleep=`): no real sleeps, no wall clock.
* One behaviour per test; `@pytest.mark.parametrize` for tables;
  Arrange / Act / Assert.
* A bug fix gets a `BUGS.md` row and section, a tagged test, and a Learnings
  Log entry in `AGENTS.md` when the lesson is general.
* Coverage is 100%. Prefer code that needs no pragma; the only
  `# pragma: no cover` lines are the two `__main__` guards and two
  defensive checks in `strategies/enrichment.py` that callers rule out.

The plan that built this layout in pumpfun-trading (findings T1–T9, Sprints
26–27) is [archived](../archive/pumpfun-trading/dev/TESTING.md).
