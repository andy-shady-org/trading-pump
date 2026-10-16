import zipfile
from pathlib import Path

import nox

# Supported interpreters (pyproject `requires-python = ">=3.11"`). Tooling-only
# sessions run on the newest one. Locally, missing interpreters are skipped; on CI
# (`CI` set) nox treats them as errors.
PYTHON_VERSIONS = ["3.11", "3.12", "3.13", "3.14"]
TOOLING_PYTHON = "3.14"


@nox.session(python=PYTHON_VERSIONS)
def tests(session):
    session.install("-e", ".[dev]")
    session.run(
        "pytest",
        "-q",
        "--cov=pumpfun_trading",
        "--cov-report=term-missing",
        "--cov-report=xml",
        "--cov-fail-under=95",
    )


@nox.session(name="tests-fast", python=[TOOLING_PYTHON], default=False)
def tests_fast(session):
    """Quick feedback loop: unit tests only, no coverage gate (Sprint 26)."""
    session.install("-e", ".[dev]")
    session.run("pytest", "-q", "-m", "not slow and not integration", *session.posargs)


@nox.session(python=[TOOLING_PYTHON])
def lint(session):
    session.install("-e", ".[dev]")
    session.run("ruff", "check", ".")
    session.run("black", "--check", ".")


@nox.session(python=[TOOLING_PYTHON])
def audit(session):
    session.install("-e", ".[dev]")
    session.run("pip-audit")


@nox.session(python=[TOOLING_PYTHON])
def mypy(session):
    session.install("-e", ".[dev]")
    session.run("mypy", "pumpfun_trading")


@nox.session(python=[TOOLING_PYTHON])
def format(session):
    session.install("-e", ".[dev]")
    session.run("black", ".")


@nox.session(python=[TOOLING_PYTHON])
def package(session):
    """Build the wheel and check it is private and ships no tests (Sprint 25, T8)."""
    session.install("build")
    out_dir = Path(session.create_tmp()) / "dist"
    for stale in out_dir.glob("*"):
        stale.unlink()
    # sdist first, then the wheel from the unpacked sdist: a stale local `build/`
    # directory can never leak old files (e.g. tests) into the checked wheel.
    session.run("python", "-m", "build", "--outdir", str(out_dir))
    wheels = sorted(out_dir.glob("*.whl"))
    if len(wheels) != 1:
        session.error(f"expected one wheel in {out_dir}, found {len(wheels)}")
    with zipfile.ZipFile(wheels[0]) as wheel:
        names = wheel.namelist()
        metadata_name = next(n for n in names if n.endswith(".dist-info/METADATA"))
        metadata = wheel.read(metadata_name).decode("utf-8")
    leaked = [n for n in names if n.startswith("pumpfun_trading/tests/")]
    if leaked:
        session.error(f"wheel ships {len(leaked)} test files, e.g. {leaked[0]}")
    if "Classifier: Private :: Do Not Upload" not in metadata:
        session.error("wheel metadata lacks the 'Private :: Do Not Upload' classifier")
    session.log(f"{wheels[0].name}: {len(names)} files, no tests, private")
