# Changelog

## [Unreleased]

### Added

- `port-forward` command and `port_forward_list` MCP tool to list active NAT virtual servers / port forwarding rules.
- `nat` command and `nat_status` MCP tool to inspect NAT ALG passthroughs, DMZ, and UPnP enablement.
- `ports` command and `port_speed` MCP tool to inspect physical Ethernet port link negotiation and supported speeds.
- `ipv6` command and `ipv6_status` MCP tool to inspect dual-stack WAN/LAN IPv6 configurations (SLAAC, prefix delegation, gateway, DNS).
- `mesh` command and `mesh_devices` MCP tool to list EasyMesh network topology, node roles, and client counts.
- `qos` command and `qos_status` MCP tool to inspect Quality of Service (QoS) bandwidth limits and priority splits.
- `storage` command and `storage_status` MCP tool to inspect USB storage disks, Samba/FTP sharing, and Time Machine status.
- `time` command and `time_status` MCP tool to inspect router system date, time, timezone, and NTP configuration.
- `power` command and `power_status` MCP tool to inspect eco mode, power profile, and smart power-saving state.
- `wifi-advanced` command and `wifi_advanced` MCP tool to inspect OFDMA, OFDMA MIMO, TWT, Smart Connect, DFS channel availability, radio schedule, and region.
- `ddns` command and `ddns_status` MCP tool to inspect the configured dynamic DNS provider.
- `iptv` command and `iptv_status` MCP tool to inspect IPTV/VLAN mode, IGMP snooping, and LAN port assignments.
- `schema` command emitting a clispec v0.2 machine-readable CLI contract (`name`, `version`, commands, error kinds, mutating flags). Offline, no auth.
- `--dry-run` as an alias for `--plan` on mutating commands.
- `wireguard` command and `wireguard_status` MCP tool to inspect WireGuard VPN server configuration and status while preserving public key availability and redacting sensitive keys.

### Changed

- Installed entry points (`tplinkctl`, `tpadmin`) now go through `run()`, which prints a clispec error envelope on stderr and returns semantic exit codes: `2` usage, `3` not_found, `4` permission, `5` confirmation_required, `6` auth, `1` router/conflict/internal.
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
