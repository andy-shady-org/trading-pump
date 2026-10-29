"""Guards for the test-suite layout and regression tagging (docs/dev/TESTING.md).

These tests read the source tree, the tests tree and ``docs/dev/BUGS.md``
statically, so they work the same for any pytest selection.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

TESTS_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = TESTS_ROOT.parent
BUGS_MD = PACKAGE_ROOT.parent / "docs" / "dev" / "BUGS.md"

# Resolved bugs with no tagged test yet. This list may only shrink: tag a
# test (or add one) and remove the ID here. Reasons are kept next to each ID.
KNOWN_UNTAGGED: dict[str, str] = {
    "BUG-09": "pytest addopts packaging issue; process fix, not runtime behaviour",
    "BUG-31": "zero-reserve quoting superseded by BUG-101 (tagged)",
}
# BUGS.md "Where each fix lives" lists the resolved bugs whose fix (and test)
# is in trading-core or left with code that was not ported; they need no tag
# here.
ELSEWHERE_LINE = re.compile(r"^\* \*\*(trading-core|Retired)[^*]*\*\*:(.*)$", re.M)

COVERAGE_NAMED = re.compile(r"^test_(coverage_.*|.*boost.*|.*_full)\.py$")
STATUS_ROW = re.compile(
    r"^\| \*\*(BUG-\d+)\*\* \|[^|]*\|[^|]*\| \*\*([A-Z ]+)\*\*", re.M
)


def _source_modules() -> list[Path]:
    return sorted(
        path
        for path in PACKAGE_ROOT.rglob("*.py")
        if path.name != "__init__.py"
        and "tests" not in path.relative_to(PACKAGE_ROOT).parts
    )


def _mirror(module: Path) -> Path:
    relative = module.relative_to(PACKAGE_ROOT)
    return TESTS_ROOT / "unit" / relative.parent / f"test_{module.name}"


def _test_files() -> list[Path]:
    return sorted(TESTS_ROOT.rglob("test_*.py"))


def _regression_tags() -> set[str]:
    tags: set[str] = set()
    for path in _test_files():
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and ast.unparse(node.func).endswith(
                "mark.regression"
            ):
                tags.update(
                    arg.value
                    for arg in node.args
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                )
    return tags


def _bug_statuses() -> dict[str, str]:
    return dict(STATUS_ROW.findall(BUGS_MD.read_text()))


@pytest.mark.parametrize(
    "module",
    _source_modules(),
    ids=lambda p: p.relative_to(PACKAGE_ROOT).as_posix(),
)
def test_layout_every_source_module_has_mirrored_unit_test(module: Path) -> None:
    mirror = _mirror(module)
    assert mirror.is_file(), f"missing {mirror.relative_to(TESTS_ROOT)}"


def _elsewhere() -> set[str]:
    found: set[str] = set()
    for _, ids in ELSEWHERE_LINE.findall(BUGS_MD.read_text()):
        found.update(re.findall(r"BUG-\d+", ids))
    return found


def test_layout_tests_root_holds_only_conftest() -> None:
    stray = sorted(p.name for p in TESTS_ROOT.glob("*.py") if p.name != "conftest.py")
    assert stray == []


def test_layout_every_unit_package_is_importable_package() -> None:
    missing = [
        d.relative_to(TESTS_ROOT).as_posix()
        for d in (TESTS_ROOT / "unit").iterdir()
        if d.is_dir() and d.name != "__pycache__" and not (d / "__init__.py").exists()
    ]
    assert missing == []


def test_layout_no_coverage_named_test_files() -> None:
    offenders = [
        p.relative_to(TESTS_ROOT).as_posix()
        for p in _test_files()
        if COVERAGE_NAMED.match(p.name)
    ]
    assert offenders == []


def test_regression_every_resolved_bug_has_a_tagged_test() -> None:
    statuses = _bug_statuses()
    resolved = {bug for bug, status in statuses.items() if status == "RESOLVED"}
    untagged = resolved - _regression_tags() - _elsewhere()
    assert sorted(untagged - set(KNOWN_UNTAGGED)) == []


def test_regression_a_bug_tested_here_is_not_listed_as_elsewhere() -> None:
    assert sorted(_regression_tags() & _elsewhere()) == []


def test_regression_known_untagged_list_only_shrinks() -> None:
    tags = _regression_tags()
    statuses = _bug_statuses()
    stale = sorted(
        bug for bug in KNOWN_UNTAGGED if bug in tags or statuses.get(bug) != "RESOLVED"
    )
    assert stale == [], "remove these from KNOWN_UNTAGGED"


def test_regression_tags_name_real_bugs() -> None:
    unknown = sorted(_regression_tags() - set(_bug_statuses()))
    assert unknown == []


# -- documentation links ------------------------------------------------------
REPO_ROOT = PACKAGE_ROOT.parent
_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*#*\s*$")
_SKIP_DIRS = {".git", ".nox", ".venv", "node_modules", "site-packages"}


def _outside_fences(text: str) -> list[str]:
    lines, fenced = [], False
    for line in text.splitlines():
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced:
            lines.append(line)
    return lines


def _slug(heading: str) -> str:
    """GitHub's heading anchor: lower case, formatting and punctuation dropped."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading.strip().lower())
    text = re.sub(r"[`*~]", "", text)
    return "".join(c for c in text if c.isalnum() or c in "-_ ").replace(" ", "-")


def _anchors(path: Path) -> set[str]:
    found: set[str] = set()
    counts: dict[str, int] = {}
    for line in _outside_fences(path.read_text(encoding="utf-8")):
        match = _HEADING.match(line)
        if match:
            slug = _slug(match.group(1))
            count = counts.get(slug, 0)
            counts[slug] = count + 1
            found.add(slug if count == 0 else f"{slug}-{count}")
    return found


def _broken_links(root: Path) -> list[str]:
    broken: list[str] = []
    anchors: dict[Path, set[str]] = {}
    docs = sorted(
        path for path in root.rglob("*.md") if not _SKIP_DIRS & set(path.parts)
    )
    for doc in docs:
        for line in _outside_fences(doc.read_text(encoding="utf-8")):
            for target in _LINK.findall(line):
                if _link_broken(doc, target, anchors):
                    broken.append(f"{doc.relative_to(root)} -> {target}")
    return broken


def _link_broken(doc: Path, target: str, anchors: dict[Path, set[str]]) -> bool:
    """A relative link whose file, or heading in a Markdown file, is missing."""
    if re.match(r"^[a-z]+:", target):
        return False
    path, _, fragment = target.partition("#")
    dest = (doc.parent / path).resolve() if path else doc
    if not dest.exists():
        return True
    if not fragment or dest.suffix != ".md":
        return False
    if dest not in anchors:
        anchors[dest] = _anchors(dest)
    return fragment.lower() not in anchors[dest]


def test_docs_relative_links_and_anchors_resolve() -> None:
    """Every relative link in the docs points at a file and heading that exist.

    pumpfun-trading's documents were archived and split on 2026-10-28; this
    keeps every cross-reference in the kept history working.
    """
    assert _broken_links(REPO_ROOT) == []


def test_the_link_check_finds_missing_files_and_headings(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.md").write_text(
        "# A Title\n## Same\n## Same\n```\n[fenced](missing.md)\n```\n"
        "[ok](b.md#b-title) [dup](#same-1) [web](https://example.com)\n"
        "[gone](c.md) [bad anchor](b.md#nope) [here](#nope)\n",
        encoding="utf-8",
    )
    (tmp_path / "docs" / "b.md").write_text("# B `Title`\n", encoding="utf-8")
    assert _broken_links(tmp_path) == [
        "docs/a.md -> c.md",
        "docs/a.md -> b.md#nope",
        "docs/a.md -> #nope",
    ]
