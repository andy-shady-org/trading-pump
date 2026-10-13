import nox


@nox.session(python=["3.14"])
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


@nox.session(python=["3.14"])
def lint(session):
    session.install("-e", ".[dev]")
    session.run("ruff", "check", ".")
    session.run("black", "--check", ".")


@nox.session(python=["3.14"])
def audit(session):
    session.install("-e", ".[dev]")
    session.run("pip-audit")


@nox.session(python=["3.14"])
def mypy(session):
    session.install("-e", ".[dev]")
    session.run("mypy", "pumpfun_trading")


@nox.session(python=["3.14"])
def format(session):
    session.install("-e", ".[dev]")
    session.run("black", ".")
