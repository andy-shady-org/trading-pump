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
* Work on a branch named `fix/<short-description>`,
  `feature/<short-description>`, `docs/<short-description>` or, for a
  release, `release/vX.Y.Z`; PRs from `main` are not accepted.
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

## Releases

Versions are plain semantic versions, `vX.Y.Z`, with **no pre-releases**
(no `rc`, `alpha` or `beta`): `v0.4.0rc1` to `v0.4.0rc5` were the last, and
the next release is `v0.4.0`. The policy is
[`docs/dev/RELEASE-GATE.md` §6](docs/dev/RELEASE-GATE.md#6-versioning-policy).
There is no release workflow: a release is made by hand, in five steps.

1. **Gate and branch.** Run the release gate
   ([`docs/dev/RELEASE-GATE.md` §2](docs/dev/RELEASE-GATE.md#2-release-gate-every-release)). On a `release/vX.Y.Z` branch:
   the version in `pyproject.toml` and `trading_pump/__init__.py` (`__version__`),
   and the `CHANGELOG.md` entry with its release record. Open a pull request.
2. **Merge** the pull request in the GitHub UI.
3. **Sign and push the tag on the Mac.** Never create the tag in the GitHub
   UI: a tag GitHub creates (a new name typed in "Draft a new release") is
   unsigned, and every runtime refuses it.

   ```bash
   git switch main && git pull
   git tag -s v0.4.0 -m "v0.4.0"
   git tag -v v0.4.0        # Good "git" signature for andy@shady.org ...
   git push origin v0.4.0
   ```

4. **Publish the GitHub Release** (optional) in the UI: Releases → Draft a
   new release → **Choose a tag** → pick the existing `v0.4.0` (do not type a
   new name) → title `v0.4.0` → paste the notes from its `CHANGELOG.md` entry
   → Publish release. GitHub shows the tag as Verified when the signing key
   is on the account (trading-core's `SECURITY.md`, "Signed releases").
5. **Install it** in the runtime with `bin/install-release.sh`, which checks
   both tags' signatures before it builds anything.

A tagged version that needs a fix gets a new PATCH, never a re-tag. Nothing
is published to PyPI or any other package index: the code is proprietary
([`LICENSE`](LICENSE)), and a signature does not stop anyone who has a copy
from running it (trading-core's `SECURITY.md`, "Distribution").

**Protect the release tags** (once per repository): GitHub → Settings →
Rules → Rulesets → New ruleset → **New tag ruleset**; target tags matching
`v*`; turn on **Restrict updates** and **Restrict deletions**, with no bypass.
A signed tag can then never be moved or removed, from the UI or a push.
Rulesets on a private repository need a paid GitHub plan (Pro or Team).
