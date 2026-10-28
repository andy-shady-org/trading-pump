# Contributing to trading-pump

trading-pump is a proprietary module for trading-core (see `LICENSE`). The
guidelines below are pumpfun-trading's, carried over
([archived](docs/archive/pumpfun-trading/CONTRIBUTING.md)), with the commands
of this repository.

## Issues

Search for an existing issue first. A new one gives the Python, trading-core
and trading-pump versions, a minimal reproducible example where possible,
what actually happened (with the full traceback), and what you expected.

## Pull requests

* Open an issue first and discuss the change.
* Work on a branch named `fix/<short-description>` or
  `feature/<short-description>`; PRs from `main` are not accepted.
* New behaviour comes with tests (mirrored layout, [`docs/dev/TESTING.md`](docs/dev/TESTING.md));
  a bug fix comes with a `BUGS.md` entry and a `@pytest.mark.regression("BUG-xx")` test.
* CI must pass: Black, Ruff, flake8, mypy, pip-audit, and the tests with
  100% statement and branch coverage on Python 3.11–3.14.
* Reference the issue in the description (`fixes #23`).
* If `main` moved on, **rebase**, don't merge.
* An engine change belongs in trading-core, not here.

## Setup

```bash
git clone https://github.com/andy-shady-org/trading-core.git
git clone https://github.com/andy-shady-org/trading-pump.git
python -m venv .venv && source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e trading-core -e 'trading-pump[dev]'
```

## Commands

```bash
nox -s tests          # every installed interpreter of 3.11–3.14 (missing ones are skipped locally)
nox -s tests-3.14     # one interpreter
nox -s tests-fast     # unit and property tests, no coverage gate
nox -s lint           # ruff, black --check, flake8
nox -s mypy
nox -s format
nox -s audit          # pip-audit
nox -s package        # builds the wheel; checks it is private and ships no tests
```

Every session installs trading-core from `TRADING_CORE_SOURCE` (default
`../trading-core`). Ruff, Black and mypy target Python 3.11, so newer-only
syntax fails even on 3.14 (trading-core TC-3).

## CI

`.github/workflows/tests.yml` runs on push and pull request: `nox -s
tests-<version>` on 3.11, 3.12, 3.13 and 3.14, and `nox -s lint mypy audit
package` on 3.14. It checks out trading-core with the `TRADING_CORE_TOKEN`
secret ([`docs/dev/TESTING.md`](docs/dev/TESTING.md#ci)).

There is no release workflow and nothing is ever published to PyPI or
another index. A release is an annotated **private** git tag on the release
commit, with its `CHANGELOG.md` entry and release record
([`docs/dev/RELEASE-GATE.md` §6](docs/dev/RELEASE-GATE.md#6-versioning-policy)).
Don't create GitHub Releases.

```bash
git tag -a v0.4.0 -m "v0.4.0"
git push origin v0.4.0
```
