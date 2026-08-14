# Changelog

## [Unreleased]

### Changed

- Update `KNOWN_QUIRKS` and doctor probe baselines to track Archer BE3500 firmware `1.3.3 Build 20260618 rel.36036(5553)` alongside `1.1.3 Build 20251120`.

## v0.4.1 - 2026-08-12

### Fixed

- `state diff` now ignores the derived `usage` sibling of `usage_bytes`.
- Device lists with unique `mac` values are matched by identity, so a reorder is not reported as field mutations.
- `--ignore signal_dbm` is treated as a leaf name and actually filters nested paths such as `devices[0].signal_dbm`.
- `--ignore devices` or `--ignore foo` suppresses top-level sections, added/removed fields, and array contents.
- `--only devices[0].hostname` now recurses into added/removed list items to project matching nested paths.
- MCP `state_diff` exposes `raw`, `only`, and `ignore`.

## v0.4.0 - 2026-08-12

### Added

- `wifi-config` command (`wifi.config` operation) to configure Wi-Fi radio parameters (`--channel`, `--width`/`--htmode`, `--txpower`, `--ssid`) for network bands (`host_2g`, `host_5g`, etc.).
- `--plan` preview support for `wifi-config` mutations.
- `wifi_config_plan` and `wifi_config` stdio JSON-RPC MCP tools in `tplinkctl-mcp`.

## v0.3.0 - 2026-07-20

### Added

- Guarded LED status, on/off, and nightly schedule commands with planning, confirmation, rollback guidance, live verification, and MCP tools.
- Read-only firmware update audit with normalized availability, auto-update status, and MCP access.

### Changed

- Migrate CI from Travis to GitHub Actions (test matrix on Python 3.10–3.12).
- Publish to PyPI automatically on GitHub Release via trusted publishing (OIDC).

### Fixed

- Place `operation=read` in both the URL and encrypted payload for BE-series endpoints that require it.
- Report the live BE3500 VPN client-status failure truthfully in capability and doctor output.

## v0.1.0 - 2026-05-05

Initial public release.

### Added

- `tplinkctl` CLI for local TP-Link router administration.
- JSON-first status, health, WAN, Wi-Fi, device, speed, route, and endpoint commands.
- Device management for DHCP reservations and access-control block/unblock flows.
- Agent capability manifest via `tplinkctl capabilities`.
- Agent tool manifest via `tplinkctl tools`.
- Read-only deep health probe via `tplinkctl doctor --deep`.
- Policy profiles: `read-only`, `device-admin`, `network-admin`, and `dangerous`.
- Device mutation planning with `--plan`.
- Append-only audit events via `tplinkctl events`.
- Redacted local state snapshots and diffs via `tplinkctl state`.
- Safe workflow demo via `tplinkctl demo`.
- Stdio JSON-RPC/MCP-style server via `tplinkctl-mcp`.
- Agent install doctor via `scripts/agent_doctor.py` and `make agent-doctor`.
- Docs, runbooks, redacted transcripts, and MCP config examples.

### Verified

- Live read-only checks against Archer BE3500.
- Live device reservation/block/unblock flows during development.
- Known firmware issue documented for `admin/vpn?form=vpn_user_list` on tested BE3500 firmware.

## Release Checklist

- [ ] Run `make test`.
- [ ] Run `make smoke`.
- [ ] Run `make demo`.
- [ ] Run `make agent-doctor`.
- [ ] Run live read-only doctor if router access is available:
  `PYTHONPATH=src .venv/bin/python scripts/agent_doctor.py --live --device Pixel-10-Pro`
- [ ] Confirm no real secrets are present:
  `rg -n "TPLINK_PASSWORD=|password|secret|token|api[_-]?key" .`
- [ ] Update `CHANGELOG.md`.
- [ ] Commit release changes.
- [ ] Create annotated tag, for example `git tag -a v0.1.0 -m "v0.1.0"`.
- [ ] Push branch and tag: `git push origin main --tags`.
