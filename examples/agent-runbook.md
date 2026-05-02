# Agent Router Runbook

This runbook shows the safe operating loop for an AI agent managing a local TP-Link router with `tplinkctl`.

## 1. Discover

```bash
tplinkctl --json capabilities
tplinkctl --json tools
tplinkctl --json demo
```

Use `capabilities` for policy/risk metadata, `tools` for MCP-style wrappers, and `demo` for a compact workflow report.

## 2. Verify Readiness

```bash
tplinkctl --json --no-input doctor --deep
tplinkctl --json --no-input status
tplinkctl --json --no-input devices --active
```

The agent should stop if required doctor probes fail.

## 3. Save State

```bash
tplinkctl --json --no-input state save --name before-change
```

Snapshots are local and redacted. They are useful for before/after comparisons.

## 4. Plan First

```bash
tplinkctl --json --reason "demo plan only" --no-input device block Pixel --plan --enforce
```

The agent should show the target hostname, IP, MAC, risk, and rollback before executing any mutation.

## 5. Execute Only When Authorized

```bash
tplinkctl --json --profile device-admin --reason "authorized pause" --no-input device block Pixel --yes --enforce
tplinkctl --json --profile device-admin --reason "restore access" --no-input device unblock Pixel --yes
```

Use `--profile` or `TPLINK_PROFILE` to keep autonomous sessions bounded.

## 6. Verify And Audit

```bash
tplinkctl --json --no-input device Pixel
tplinkctl --json --no-input state save --name after-change
tplinkctl --json state diff --before before-change --after after-change
tplinkctl --json events --tail 20
```

Audit events are append-only JSONL at `~/.config/tplink-admin/events.jsonl`.

## 7. MCP Mode

```bash
export TPLINK_PASSWORD=...
export TPLINK_MCP_PROFILE=device-admin
tplinkctl-mcp
```

Agents should call `device_plan` before `device_block` or `device_unblock`. Mutating MCP tools require `confirm=true`.
