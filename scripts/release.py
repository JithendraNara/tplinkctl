#!/usr/bin/env python3
"""Release bookkeeping for tplinkctl.

A release is two small PRs around one workflow run (see docs/RELEASING.md):

  prepare X.Y.Z   bump versions, finalize `## [Unreleased]` as `## vX.Y.Z - DATE`,
                  regenerate versioned artifacts      -> PR "chore(release): prepare X.Y.Z"
  (Release workflow builds, tags, publishes)
  open            add an empty `## [Unreleased]` section -> PR "chore: open next Unreleased section"

`check X.Y.Z` verifies the tree is ready to release that version and `notes X.Y.Z`
prints the changelog section used as the GitHub Release body.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
UNRELEASED = "## [Unreleased]"


class ReleaseError(Exception):
    pass


def _semver(version: str) -> tuple[int, int, int]:
    match = SEMVER.match(version)
    if not match:
        raise ReleaseError(f"`{version}` is not a plain X.Y.Z version")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def current_version(root: Path) -> str:
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"$', text, re.M)
    if not match:
        raise ReleaseError("pyproject.toml has no version")
    return match.group(1)


def package_version(root: Path) -> str:
    text = (root / "src/tplink_admin/__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "([^"]+)"$', text, re.M)
    if not match:
        raise ReleaseError("src/tplink_admin/__init__.py has no __version__")
    return match.group(1)


def _sections(changelog: str) -> list[tuple[str, int, int]]:
    """(heading, start, end) for each `## ` section; end is the next heading."""
    heads = [m for m in re.finditer(r"^## .*$", changelog, re.M)]
    return [(m.group(0), m.start(), heads[i + 1].start() if i + 1 < len(heads) else len(changelog))
            for i, m in enumerate(heads)]


def section_body(changelog: str, heading_prefix: str) -> str | None:
    for heading, start, end in _sections(changelog):
        if heading == heading_prefix or heading.startswith(heading_prefix + " "):
            return changelog[start + len(heading):end].strip()
    return None


def _replace_once(path: Path, pattern: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    new, count = re.subn(pattern, replacement, text, count=1, flags=re.M)
    if count != 1:
        raise ReleaseError(f"could not update the version in {path.name}")
    path.write_text(new, encoding="utf-8")


def regenerate_artifacts(root: Path) -> None:
    """Versioned generated files (docs/openapi.json embeds the version)."""
    env = {**os.environ, "PYTHONPATH": str(root / "src")}
    for module, target in (("tplink_admin.openapi", "docs/openapi.json"), ("tplink_admin.clidoc", "docs/commands.md")):
        output = subprocess.run([sys.executable, "-m", module], cwd=root, env=env,
                                check=True, capture_output=True, text=True).stdout
        (root / target).write_text(output, encoding="utf-8")


PREPARED_FILES = ("CHANGELOG.md", "pyproject.toml", "src/tplink_admin/__init__.py", "README.md",
                  "docs/openapi.json", "docs/commands.md")


def prepare(root: Path, version: str, date: str, regenerate: bool = True) -> None:
    """All-or-nothing: on any failure every touched file is restored."""
    snapshot = {name: (root / name).read_bytes() for name in PREPARED_FILES if (root / name).exists()}
    try:
        _prepare(root, version, date, regenerate)
    except BaseException:
        for name, data in snapshot.items():
            (root / name).write_bytes(data)
        raise


def _prepare(root: Path, version: str, date: str, regenerate: bool) -> None:
    old = current_version(root)
    if _semver(version) <= _semver(old):
        raise ReleaseError(f"{version} must be greater than the current version {old}")
    changelog_path = root / "CHANGELOG.md"
    changelog = changelog_path.read_text(encoding="utf-8")
    body = section_body(changelog, UNRELEASED)
    if body is None:
        raise ReleaseError("CHANGELOG.md has no `## [Unreleased]` section")
    if not re.search(r"^- ", body, re.M):
        raise ReleaseError("`## [Unreleased]` has no entries to release")
    if section_body(changelog, f"## v{version}") is not None:
        raise ReleaseError(f"CHANGELOG.md already has a v{version} section")
    changelog_path.write_text(changelog.replace(UNRELEASED, f"## v{version} - {date}", 1), encoding="utf-8")
    _replace_once(root / "pyproject.toml", r'^version = "[^"]+"$', f'version = "{version}"')
    _replace_once(root / "src/tplink_admin/__init__.py", r'^__version__ = "[^"]+"$', f'__version__ = "{version}"')
    readme = root / "README.md"
    text = readme.read_text(encoding="utf-8")
    readme.write_text(text.replace(f"release-v{old}-", f"release-v{version}-").replace(
        f"releases/tag/v{old}", f"releases/tag/v{version}"), encoding="utf-8")
    if regenerate:
        regenerate_artifacts(root)


def open_unreleased(root: Path) -> None:
    path = root / "CHANGELOG.md"
    changelog = path.read_text(encoding="utf-8")
    if UNRELEASED in changelog:
        raise ReleaseError("CHANGELOG.md already has an Unreleased section")
    sections = _sections(changelog)
    if not sections:
        raise ReleaseError("CHANGELOG.md has no version sections")
    start = sections[0][1]
    path.write_text(changelog[:start] + UNRELEASED + "\n\n" + changelog[start:], encoding="utf-8")


def check(root: Path, version: str) -> list[str]:
    problems = []
    _semver(version)
    for label, found in (("pyproject.toml", current_version(root)), ("tplink_admin.__version__", package_version(root))):
        if found != version:
            problems.append(f"{label} is {found}, expected {version}")
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    body = section_body(changelog, f"## v{version}")
    if body is None:
        problems.append(f"CHANGELOG.md has no `## v{version} - DATE` section")
    elif not re.search(r"^- ", body, re.M):
        problems.append(f"CHANGELOG.md v{version} section has no entries")
    unreleased = section_body(changelog, UNRELEASED)
    if unreleased:
        problems.append("CHANGELOG.md has unreleased entries; prepare moves them into the version section")
    spec_version = json.loads((root / "docs/openapi.json").read_text(encoding="utf-8"))["info"]["version"]
    if spec_version != version:
        problems.append(f"docs/openapi.json version is {spec_version}; run `make docs`")
    readme = (root / "README.md").read_text(encoding="utf-8")
    if f"releases/tag/v{version}" not in readme:
        problems.append("README.md release badge does not point at this version")
    return problems


def notes(root: Path, version: str) -> str:
    body = section_body((root / "CHANGELOG.md").read_text(encoding="utf-8"), f"## v{version}")
    if body is None:
        raise ReleaseError(f"CHANGELOG.md has no v{version} section")
    return f"# tplinkctl v{version}\n\n{body}\n\nPyPI: https://pypi.org/project/tplink-admin-cli/{version}/\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare", help="bump versions and finalize the Unreleased changelog section")
    p.add_argument("version")
    p.add_argument("--date", default=dt.date.today().isoformat(), help="release date (default: today)")
    sub.add_parser("open", help="add an empty Unreleased section after a release")
    c = sub.add_parser("check", help="verify the tree is ready to release VERSION")
    c.add_argument("version")
    n = sub.add_parser("notes", help="print the GitHub Release body for VERSION")
    n.add_argument("version")
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            prepare(args.root, args.version, args.date)
            print(f"Prepared {args.version}. Review the diff, run `make smoke`, then open "
                  f"`chore(release): prepare {args.version}`.")
        elif args.command == "open":
            open_unreleased(args.root)
            print("Opened `## [Unreleased]`.")
        elif args.command == "check":
            problems = check(args.root, args.version)
            for problem in problems:
                print(f"release check: {problem}", file=sys.stderr)
            if problems:
                return 1
            print(f"Ready to release {args.version}.")
        elif args.command == "notes":
            sys.stdout.write(notes(args.root, args.version))
    except ReleaseError as exc:
        print(f"release: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"release: regenerating artifacts failed ({' '.join(exc.cmd[1:])}); no files changed\n{exc.stderr}",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
