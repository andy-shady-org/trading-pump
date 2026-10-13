# Welcome to PumpFun Trading Contribution Guidelines

Thank you for taking the time to contribute to the PumpFun Trading project!

## Issues

When you discover a problem with Pumpfun Trading, search for an existing issue first. If there isn't a related issue, you can open a new one.

Include the following information in your post:

* Use the issue template provided by GitHub when starting a new issue
* Specify your Python and PumpFun Trading versions. If possible, check if this issue has been fixed in a later release
* Whenever possible, include a [minimal reproducible example](https://stackoverflow.com/help/minimal-reproducible-example) to help identify the problem
* Describe what actually happened. Include the full traceback if an exception occurred.

## Submitting Pull Requests

* Exceptions should be rare and be accompanied by a good explanation.
* Make sure to open an issue before starting work on a pull request, and discuss your idea with the PumpFun Trading community before starting work.
* Create a new branch, ideally with a name like `fix/short-description-of-the-fix` or `feature/short-description-of-the-feature` to make the project history more readable. PRs based on your `main` branch will not be accepted
* All new functionality must be accompanied by relevant tests where possible
* All code submissions should meet the following criteria, which are automatically checked by the GitHub CI workflow:
    * Python syntax is valid
    * `black` code formatting is enforced
    * `ruff` linting passes
    * `pip-audit` security scan passes
    * all tests successful
* Include a reference to the fixed bug or feature request in the description of the pull request, e.g. `fixes #23`. See the [GitHub documentation](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/using-keywords-in-issues-and-pull-requests) for details
* If the main branch has moved on while you were working on a pull request, please __do not merge but rebase__ your branch. Merging normally isn't usually necessary, and it creates merge commits that unnecessarily clutter the project's history

## First Time Setup

* Download and install the latest version of `git`
* Configure git with your username and email:

```bash
$ git config --global user.name 'your name'
$ git config --global user.email 'your email'
```

* Fork `pumpfun-trading` to your GitHub account by clicking the __Fork__ button.
* Clone your forked repository locally:

```bash
$ git clone https://github.com/YOUR-GITHUB-USERNAME/pumpfun-trading.git
```

* Use the main project's `main` repository as upstream remote:

```bash
$ cd pumpfun-trading
$ git remote add upstream https://github.com/andy-shady-org/pumpfun-trading.git
```

* Create a virtual environment and install the project in editable mode with dev tools:

```bash
$ python -m venv .venv
$ source .venv/bin/activate
$ python -m pip install --upgrade pip
$ python -m pip install -e '.[dev]'
```

After these steps are completed successfully, you're all set up.

## Local development commands

This project uses `nox` to manage the standard development tasks. The repository defines these sessions:

```bash
$ nox -s tests
$ nox -s lint
$ nox -s audit
$ nox -s mypy
$ nox -s format
```

Useful one-off checks:

```bash
$ pytest -q
$ ruff check .
$ black --check .
$ pip-audit
```

## Formatting and linting

To achieve a consistent coding style, all code in the project is formatted with `black` and linted with `ruff`.

```bash
$ black .
$ ruff check .
```

## Running the tests

Go to the project directory and run:

```bash
$ pytest
```

Or use the standard nox session:

```bash
$ nox -s tests
```

## CI and release automation

The repository includes GitHub Actions workflows for validation and release:

* `tests.yml` runs automatically on push and pull request to `main` and `master`
* it executes the nox checks for tests, lint, and security audit
* `release.yml` runs when a version tag like `v0.1.0` is pushed
* the release workflow builds the project and publishes to PyPI using the `PYPI_API_TOKEN` secret

To publish a release:

```bash
$ git tag v0.1.0
$ git push origin v0.1.0
```

Then GitHub Actions will build the package and upload to PyPI.

Before creating a release, make sure the `PYPI_API_TOKEN` repository secret is configured in GitHub.

## Final notes

We expect contributors to maintain the repo’s testing, formatting, and security standards before opening a PR. If you run the nox sessions locally and keep the code clean, the CI checks should pass without surprises.
