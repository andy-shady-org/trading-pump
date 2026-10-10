import nox


@nox.session(python=["3.11"])
def tests(session):
    session.install("-e", ".[dev]")
    session.run("pytest", "-q")


@nox.session(python=["3.11"])
def lint(session):
    session.install("-e", ".[dev]")
    session.run("ruff", "check", ".")
    session.run("black", "--check", ".")


@nox.session(python=["3.11"])
def audit(session):
    session.install("-e", ".[dev]")
    session.run("pip-audit")


@nox.session(python=["3.11"])
def format(session):
    session.install("-e", ".[dev]")
    session.run("black", ".")

