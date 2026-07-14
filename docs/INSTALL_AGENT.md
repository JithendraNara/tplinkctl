# Agent Install Guide

This guide wires `tplinkctl` into local AI agents through the CLI and the stdio MCP server.

## Install

```bash
python3 -m venv .venv
.venv/bin/python -m pip install .
```

If package installation is unavailable, run from source:

```bash
PYTHONPATH=src .venv/bin/python -m tplink_admin.cli --json demo
PYTHONPATH=src .venv/bin/python -m tplink_admin.mcp
```

## Environment

Set non-secret router defaults in config or environment:

```bash
tplinkctl config set --host http://192.168.0.1 --username admin --client sg
export TPLINK_HOST=http://192.168.0.1
export TPLINK_USERNAME=admin
export TPLINK_CLIENT=sg
export TPLINK_MCP_PROFILE=device-admin
```

Set `TPLINK_PASSWORD` in the agent secret store or shell environment. Do not put the real password in repo files.

## Recommended Profiles

- `read-only`: monitoring, status dashboards, diagnostics.
- `device-admin`: device lookup, DHCP reservations, access-control block/unblock.
- `network-admin`: device administration plus Wi-Fi/VPN/reboot.
- `dangerous`: trusted local operators only.

For most autonomous agents, start with:

```bash
export TPLINK_MCP_PROFILE=device-admin
```

## Agent Doctor

Run the local readiness check:

```bash
make agent-doctor
```

Live read-only router checks:

```bash
PYTHONPATH=src .venv/bin/python scripts/agent_doctor.py --live --device Pixel-10-Pro
```

The report checks source CLI commands, capability/tool manifests, MCP `tools/list`, config paths, and whether `TPLINK_PASSWORD` is set.

## MCP Server

Start the server directly:

```bash
PYTHONPATH=src .venv/bin/python -m tplink_admin.mcp
```

Installed console script:

```bash
tplinkctl-mcp
```

MCP methods:

- `initialize`
- `tools/list`
- `tools/call`
- `ping`

Tools:

- `router_status`
- `firmware_audit`
- `led_status`
- `led_plan`
- `led_set`
- `device_list`
- `device_show`
- `device_plan`
- `device_block`
- `device_unblock`
- `doctor_deep`
- `watch`
- `audit_tail`
- `state_snapshot`
- `state_diff`

Mutating tools require `confirm=true`. Agents should call `device_plan` or `led_plan` first and show the rollback command before calling a mutation tool.

## Config Examples

- Generic MCP client: [examples/mcp/generic.json](../examples/mcp/generic.json)
- Codex-style config: [examples/mcp/codex.json](../examples/mcp/codex.json)

Replace `/absolute/path/to/repo` with the local checkout path and keep `TPLINK_PASSWORD` in your secret manager.

## Safe Demo

```bash
make demo
tplinkctl --json demo
tplinkctl --json --no-input demo --live --device Pixel-10-Pro --save-state --state-name demo
```

The live demo performs read-only checks and plans a mutation without executing it.
