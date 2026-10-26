# Releasing

A release is two small PRs around one workflow run. Nothing is released until
the GitHub Release exists and the version installs from PyPI; a version bump
or a tag alone is not a release.

## 1. Prepare (PR)

From an up-to-date `main` with user-visible changes listed under
`## [Unreleased]` in `CHANGELOG.md`:

```bash
git switch -c chore/release-X.Y.Z
python scripts/release.py prepare X.Y.Z      # --date YYYY-MM-DD to override today
make smoke
python scripts/release.py check X.Y.Z
```

`prepare` is all-or-nothing. It:

- renames `## [Unreleased]` to `## vX.Y.Z - DATE`;
- bumps `pyproject.toml`, `tplink_admin.__version__` and the README badge;
- regenerates `docs/openapi.json` and `docs/commands.md`.

It refuses a version that is not greater than the current one, and it refuses
an empty `Unreleased` section.

Review the changelog section as release notes: it becomes the GitHub Release
body verbatim (`python scripts/release.py notes X.Y.Z`). Open the PR as
`chore(release): prepare X.Y.Z`, and merge it when CI is green.

## 2. Dry run, then release (workflow)

Actions → **Release** → Run workflow on `main`:

1. `version: X.Y.Z`, `dry_run: true` (the default). This applies `prepare` in
   the runner if needed and builds the same assets as a real release, without
   tagging or publishing:
   - the sdist and wheel (reusable `dist.yml`: twine check, archive contracts,
     clean-venv install of every entry point and an MCP `initialize`);
   - the Forge HTTP SDK archive (reusable `forge.yml`);
   - checksums.

   The run summary shows the checksums and the notes.
2. Run it again with `dry_run: false`. Preflight requires `main`, an absent tag
   and a clean `release.py check`. The workflow creates the tag and the GitHub
   Release with all assets, then dispatches **Publish to PyPI**.
   `publish.yml` uploads with trusted publishing, then installs
   `tplink-admin-cli==X.Y.Z` from PyPI and checks `tplinkctl --version`.

The PyPI trusted publisher is bound to `publish.yml`; do not rename that file.

## 3. Verify

```bash
gh release view vX.Y.Z --json tagName,assets -q '.tagName, [.assets[].name]'
curl -fsS https://pypi.org/pypi/tplink-admin-cli/X.Y.Z/json | python -c 'import json,sys; print(json.load(sys.stdin)["info"]["version"])'
```

The Release body must match the `vX.Y.Z` changelog section. The Homebrew
formula in `JithendraNara/homebrew-tap` picks up the new PyPI version on its
scheduled bump; check that `brew upgrade tplinkctl` reports X.Y.Z.

## 4. Open the next Unreleased section (PR)

```bash
git switch main && git pull --ff-only && git switch -c chore/open-unreleased
python scripts/release.py open
```

Open `chore: open next Unreleased section` and merge it. New work lands under
`## [Unreleased]` until the next prepare.

## Before tagging a release that changes router behavior

- `make demo` and `make agent-doctor` pass.
- A live read-only check passes on hardware you own:
  `PYTHONPATH=src .venv/bin/python scripts/agent_doctor.py --live --device <device>`.
- No secrets or private network data in the diff since the last tag:
  `git diff vPREVIOUS -- . ':!docs/openapi.json' | rg -n "TPLINK_PASSWORD=|password|secret|token|api[_-]?key"`.
