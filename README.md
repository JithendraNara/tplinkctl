# tplinkctl

[![CI](https://github.com/JithendraNara/tplinkctl/actions/workflows/ci.yml/badge.svg)](https://github.com/JithendraNara/tplinkctl/actions/workflows/ci.yml)
[![Version](https://img.shields.io/badge/release-v0.5.0-blue.svg)](https://github.com/JithendraNara/tplinkctl/releases/tag/v0.5.0)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)](https://www.python.org/)
[![CLI Spec](https://img.shields.io/badge/clispec-v0.2-emerald)](https://clispec.dev/)
[![License](https://img.shields.io/badge/license-GPL--3.0--or--later-blue.svg)](LICENSE)

**Autonomous agent-ready CLI and stdio FastMCP server for local TP-Link router management.**

`tplinkctl` turns stateful, slow, and browser-dependent router admin interfaces into a high-speed, local-first API interface designed for humans, shell scripts, and autonomous AI coding agents (Hermes, Claude Code, Cursor, Codex, OpenClaw).

---

## Key Highlights

- 🛡️ **Autonomous Mutation Safety:** Plan-before-execute via `--plan` / `--dry-run`, mandatory `--yes` confirmations on destructive actions, noise-filtered state snapshot diffing (`state diff`), and rollback contracts.
- 🤖 **Agent-First Discovery:** Full [CLI Spec v0.2](https://clispec.dev/) compliance via `tplinkctl schema`, structured semantic exit codes, JSON error envelopes on `stderr`, and built-in `capabilities`, `AGENTS.md`, and `llms.txt`.
- ⚡ **Dual Transport (CLI + MCP):** 50+ CLI subcommands paired with 30 stdio JSON-RPC MCP tools in `tplinkctl-mcp` with zero heavy SDK dependencies.
- 🔒 **Granular Policy Profiles:** 4 security tiers (`read-only`, `device-admin`, `network-admin`, `dangerous`) to safely constrain autonomous agents in long-running sessions.
- 📡 **Deep Hardware Coverage:** 55+ reverse-engineered endpoints covering Wi-Fi 7 (OFDMA, TWT, DFS, Smart Connect), EasyMesh, WireGuard VPN, QoS bandwidth limits, NAT ALG/DMZ/UPnP, IPTV/VLAN, USB storage sharing, and power eco schedules.

---

## Quick Start

### 1. Install

```bash
# From source (or via uv / pip)
git clone https://github.com/JithendraNara/tplinkctl.git
cd tplinkctl
python3 -m venv .venv
.venv/bin/pip install -e .
```

### 2. Configure

Set non-secret router defaults and export your password in the environment:

```bash
tplinkctl config set --host http://192.168.0.1 --username admin --client sg
export TPLINK_PASSWORD="your-local-router-password"
```

### 3. Inspect

```bash
# Verify connection & readiness
tplinkctl doctor
tplinkctl --json status

# Introspect machine-readable CLI contract
tplinkctl schema
```

---

## Command Surface & Tool Matrix

| Category | CLI Command | MCP Tool | Description | Mutating |
|---|---|---|---|:---:|
| **System & Health** | `status` | `router_status` | Summary of router, WAN, Wi-Fi, speed, and clients | No |
| | `health` | — | Health analysis, memory/CPU load, WAN state | No |
| | `doctor [--deep]` | `doctor_deep` | Reachability probe & full authenticated API health | No |
| | `firmware` | — | Active firmware version & hardware model | No |
| | `firmware-check` | `firmware_audit` | Audit update availability without installing | No |
| | `power` | `power_status` | Eco mode status, power profile, and power-saving schedule | No |
| | `time` | `time_status` | System time, timezone, and NTP configuration | No |
| | `led status` | `led_status` | LED indicator state and nightly schedule | No |
| | `led on\|off\|schedule` | `led_plan` / `led_set` | Toggle LEDs or configure nightly schedule | ⚠️ Yes |
| | `reboot` | — | Reboot the router (`--yes` required) | ⚠️ Yes |
| **Devices & Access** | `devices [--active]` | `device_list` | Connected devices, IP/MAC, link rate, and usage | No |
| | `device <query>` | `device_show` | Search device by hostname, IP, or MAC | No |
| | `device reserve` | `device_plan` | Create permanent DHCP reservation | ⚠️ Yes |
| | `device release` | `device_plan` | Remove DHCP reservation | ⚠️ Yes |
| | `device block` | `device_block` | Add device to Access Control blacklist (`--enforce`) | ⚠️ Yes |
| | `device unblock` | `device_unblock` | Remove device from Access Control blacklist | ⚠️ Yes |
| | `device access` | — | Access Control mode (blacklist / whitelist) | ⚠️ Yes |
| | `speed` | — | Router-reported throughput per device | No |
| **Wi-Fi & Wireless** | `wifi-info` | — | SSIDs, bands, channel state, redacted keys | No |
| | `wifi-status` | — | Radio enablement for 2.4G / 5G / 6G / Guest / IoT | No |
| | `wifi-advanced` | `wifi_advanced` | OFDMA, TWT, DFS channel availability, schedule | No |
| | `wifi-config` | `wifi_config_plan` / `wifi_config` | Configure radio channel, width, txpower, SSID | ⚠️ Yes |
| | `wifi <net> on\|off` | — | Toggle Wi-Fi band or guest network | ⚠️ Yes |
| **Network & NAT** | `wan` | — | WAN IP, gateway, DNS, uptime, connection type | No |
| | `ipv4` | — | WAN and LAN IPv4 network status | No |
| | `ipv6` | `ipv6_status` | Dual-stack WAN/LAN IPv6 configurations | No |
| | `leases` | — | Active DHCP leases | No |
| | `reservations` | — | Current DHCP address reservations | No |
| | `port-forward` | `port_forward_list` | NAT virtual servers / port forwarding rules | No |
| | `nat` | `nat_status` | NAT ALG passthrough, DMZ, and UPnP status | No |
| | `ports` | `port_speed` | Physical Ethernet link speed & capabilities | No |
| | `qos` | `qos_status` | Quality of Service bandwidth limits and priorities | No |
| | `ddns` | `ddns_status` | Dynamic DNS provider configuration & status | No |
| | `iptv` | `iptv_status` | IPTV/VLAN, IGMP snooping, and port mapping | No |
| | `storage` | `storage_status` | USB disks, Samba/FTP sharing, Time Machine | No |
| **Mesh & VPN** | `mesh` | `mesh_devices` | EasyMesh network topology and node roles | No |
| | `wireguard` | `wireguard_status` | WireGuard server configuration & status | No |
| | `vpn-status` | — | OpenVPN / PPTP VPN server status | No |
| | `vpn-client-status` | — | VPN client routing status | No |
| **Agent & Ops** | `schema` | — | Machine-readable [clispec v0.2](https://clispec.dev/) contract | No |
| | `capabilities` | — | Agent capability manifest with risks & quirks | No |
| | `tools` | — | JSON tool schemas for CLI wrappers | No |
| | `events` | `audit_tail` | Append-only local audit log for agent actions | No |
| | `state save\|diff` | `state_snapshot` / `state_diff` | Redacted router state snapshots and noise-filtered diffs | No |
| | `watch` | `watch` | Repeated read-only monitoring samples | No |
| | `demo` | — | Safe agent workflow demo report | No |

---

## Agent Safety & Policy Profiles

`tplinkctl` provides four security profile envelopes to restrict agent execution permissions:

| Profile | Allowed Commands | Allowed Operations | Denied Operations |
|---|---|---|---|
| `read-only` | All read commands | Discovery & inspection | All mutations (`device.*`, `wifi.*`, `reboot`) |
| `device-admin` *(Default)* | Read + `device` | Inventory, DHCP reservations, Blacklist block/unblock | Router-wide toggles (`wifi.*`, `vpn.*`, `reboot`, `raw`) |
| `network-admin` | Read + `device`, `wifi`, `vpn`, `reboot` | Everything except raw escape hatches | `advanced.raw` |
| `dangerous` | All (`*`) | All (`*`) | None (unrestricted) |

Set policy profiles via CLI flag or environment variable:

```bash
# Per-command profile
tplinkctl --json --profile read-only status
tplinkctl --json --profile device-admin device block Pixel --dry-run

# Session-wide profile
export TPLINK_PROFILE=device-admin
```

### The Plan → Execute → Verify → Audit Loop

Autonomous agents should follow this standard mutation lifecycle:

```bash
# 1. Plan the change (dry-run preview with rollback instructions)
tplinkctl --json --reason "pause guest device" --no-input device block Pixel --plan --enforce

# 2. Execute with explicit confirmation
tplinkctl --json --reason "pause guest device" --no-input device block Pixel --yes --enforce

# 3. Verify state diff (rate/timestamp noise is filtered automatically)
tplinkctl --json --no-input state save --name after-block
tplinkctl --json state diff --before before-block --after after-block

# 4. Review audit trail
tplinkctl --json events --tail 5
```

---

## FastMCP Server Integration

`tplinkctl-mcp` exposes 30 router tools over standard JSON-RPC stdio. Mutating MCP tools require `confirm=true` in tool arguments.

Add `tplinkctl-mcp` to your agent configuration:

### Claude Desktop (`claude_desktop_config.json`)
```json
{
  "mcpServers": {
    "tplink": {
      "command": "tplinkctl-mcp",
      "env": {
        "TPLINK_HOST": "http://192.168.0.1",
        "TPLINK_USERNAME": "admin",
        "TPLINK_PASSWORD": "your-router-password",
        "TPLINK_CLIENT": "sg",
        "TPLINK_MCP_PROFILE": "device-admin"
      }
    }
  }
}
```

### Hermes Agent / Cursor / OpenClaw
```yaml
mcp_servers:
  tplink:
    command: "tplinkctl-mcp"
    env:
      TPLINK_HOST: "http://192.168.0.1"
      TPLINK_PASSWORD: "${TPLINK_PASSWORD}"
      TPLINK_MCP_PROFILE: "device-admin"
```

---

## The CLI Spec (clispec v0.2) & Exit Codes

`tplinkctl` fully implements [The CLI Spec v0.2](https://clispec.dev/):

### Introspection
Agents can discover all commands, arguments, types, defaults, and mutation contracts offline without executing network calls:

```bash
# Entire command tree
tplinkctl schema

# Subtree narrowing (token-efficient)
tplinkctl schema device
tplinkctl schema wifi-config
```

### Semantic Exit Codes
Failures write a single-line JSON error envelope as the **last line of stderr**:

```json
{"error": {"kind": "confirmation_required", "message": "Refusing to block without --yes.", "hint": "Re-run with --plan or --dry-run first, then add --yes."}}
```

| Exit Code | Error Kind | Description |
|:---:|---|---|
| `0` | `success` | Successful execution |
| `1` | `router` / `conflict` / `internal` | Router returned an error or unreadable payload |
| `2` | `usage` | Invalid arguments or unknown profile |
| `3` | `not_found` | Target device, MAC, or state snapshot not found |
| `4` | `permission` | Action blocked by policy profile or allowlist/denylist |
| `5` | `confirmation_required` | Mutating action invoked without `--yes` |
| `6` | `auth` | Password missing or authentication failed |

---

## Router & Hardware Compatibility

`tplinkctl` is built on [`tplinkrouterc6u`](https://pypi.org/project/tplinkrouterc6u/) (`>=5.30.0`) and includes an active payload normalizer for TP-Link's SG authentication protocol.

| Router Model | Firmware Tested | SG Protocol | Notes |
|---|---|:---:|---|
| **Archer BE3500 v1.0** | `1.3.3 Build 20260618` / `1.1.3 Build 20251120` | ✓ | Primary target; full 55+ endpoint coverage |
| **Archer BE220 / BE230 / BE3600** | SG-generation firmwares | ✓ | Compatible via `--client sg` |
| **Archer AX72 / AX12 / C6U** | Modern RSA-OAEP / SG firmwares | ✓ | Compatible |

---

## Development & Verification

```bash
# Run unit test suite (86 tests)
make test

# Run offline smoke suite
make smoke

# Run agent workflow demo
make demo

# Deep health verification against live router
tplinkctl --json --no-input doctor --deep
```

---

## Documentation Links

- [`AGENTS.md`](AGENTS.md) — Operational instructions, discovery guidelines, and playbooks for AI agents.
- [`llms.txt`](llms.txt) — LLM-optimized summary and context index.
- [`docs/ENDPOINTS.md`](docs/ENDPOINTS.md) — Complete reverse-engineered endpoint and payload reference.
- [`docs/INSTALL_AGENT.md`](docs/INSTALL_AGENT.md) — Detailed agent integration and MCP configuration guide.
- [`examples/agent-runbook.md`](examples/agent-runbook.md) — End-to-end agent operational runbook.
- [`CHANGELOG.md`](CHANGELOG.md) — Version history and release notes.

---

## License

GNU GPLv3 or later © [Jithendra Nara](https://github.com/JithendraNara)
