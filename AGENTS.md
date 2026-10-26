# Agent Playbook

This repo is meant to let local agents manage a TP-Link router without scraping the browser UI. Treat the router as shared infrastructure: read first, mutate only with explicit intent, and always prefer JSON.

## Default Invocation

```bash
tplinkctl --json --no-input <command>
```

Set these in the agent environment:

```bash
TPLINK_HOST=http://192.168.0.1
TPLINK_USERNAME=admin
TPLINK_CLIENT=sg
TPLINK_PASSWORD=...
TPLINK_MCP_PROFILE=device-admin
```

Do not echo `TPLINK_PASSWORD` in logs, reports, prompts, or shell snippets.

## Discovery Flow

1. Run `tplinkctl schema` for the clispec v0.2 machine-readable command/error contract, generated from the real parser (every command, flag, type and choice). Narrow with `tplinkctl schema device`. `docs/commands.md` is the rendered copy; regenerate with `make docs` after changing any parser.
2. Run `tplinkctl --json capabilities` to inspect available commands, risks, rollback hints, and known firmware issues.
3. Run `tplinkctl --json tools` to discover the local tool surface and command mappings.
4. Run `tplinkctl --json demo` for a compact workflow report.
5. Start `tplinkctl-mcp` when the agent framework supports stdio JSON-RPC tools.
6. Run `tplinkctl --json --no-input doctor --deep` to verify web UI reachability, authentication, and read-only endpoint health.
7. Run `tplinkctl --json --no-input status` for a human-sized router summary.
8. Run `tplinkctl --json --no-input firmware-check` to audit update availability without installing firmware.
9. Run `tplinkctl --json --no-input led status` before planning an LED change.
10. Run `tplinkctl --json --no-input devices --active` before making device decisions.
11. Use `tplinkctl --json --no-input device <query>` to resolve an exact hostname, IP, or MAC before mutating.
12. Save state before meaningful changes: `tplinkctl --json --no-input state save --name before-change`.

## Guardrails

Use allowlists for agents with narrow jobs:

```bash
tplinkctl --json --no-input --enable-commands status,devices,device device Pixel
```

Use denylists for broad agents that must not disrupt connectivity:

```bash
tplinkctl --json --no-input --disable-commands reboot,wifi,vpn,vpn-client,raw status
```

Prefer profile envelopes for long-running agents:

```bash
TPLINK_PROFILE=read-only tplinkctl --json --no-input status
TPLINK_PROFILE=device-admin tplinkctl --json --no-input device block Pixel --plan
TPLINK_PROFILE=device-admin tplinkctl --json --no-input device block Pixel --dry-run
TPLINK_PROFILE=network-admin tplinkctl --json --no-input wifi guest_2g on
```

Profiles:

- `read-only`: discovery and read-only inspection, no mutations.
- `device-admin`: device inventory, DHCP reservations, access-control block/unblock, no router-wide toggles.
- `network-admin`: device administration plus Wi-Fi/VPN/reboot, no raw endpoint experiments.
- `dangerous`: no profile-level restrictions.

Profile definitions live in `src/tplink_admin/profiles/*.json`. Changing them changes what agents may do: keep `read-only` free of mutations, keep profiles nested from narrowest to widest, and keep the registry's per-tool `profiles` in agreement (`tests/test_profiles.py` enforces all three).

Mutating commands should include a rollback in the agent plan:

```bash
tplinkctl --json --reason "pause network access" --no-input device block Pixel --plan --enforce
tplinkctl --json --reason "pause network access" --no-input device block Pixel --yes
tplinkctl --json --reason "restore network access" --no-input device unblock Pixel --yes
```

After mutating, verify and inspect the audit log:

```bash
tplinkctl --json --no-input device Pixel
tplinkctl --json events --tail 20
tplinkctl --json --no-input state save --name after-change
tplinkctl --json state diff --before before-change --after after-change
```

The default `state diff` filters rate/counter/timestamp noise so a no-op diff
returns zero changes and a real mutation surfaces cleanly. Use `--raw` to see
every field, `--only <prefix>` to scope to a subtree, or `--ignore <path>`
(repeatable) to add additional dotted paths to skip.

## Agent-Oriented Capabilities

High confidence:

- `router.status`: summary, WAN, Wi-Fi, devices, health
- `router.firmware.audit`: current firmware, update availability, and auto-update configuration; never installs firmware
- `device.list`: connected device inventory with IP, MAC, speed, usage, connection type
- `device.show`: exact device lookup
- `device.reserve`: live verified DHCP reservation
- `device.release`: live verified reservation removal
- `device.block`: live verified access-control blacklist insert
- `device.unblock`: live verified blacklist removal
- `wifi.info`: SSIDs, bands, channel state, redacted secrets
- `router.led.status`: LED state and nightly LED-off schedule
- `internet.speed`: current router-reported device throughput
- `internet.speedtest`: external Cloudflare speed test
- `agent.tools`: local tool schemas for agent wrappers
- `agent.schema`: clispec v0.2 CLI contract (`tplinkctl schema`)
- `agent.watch`: repeated read-only monitoring samples
- `agent.events`: append-only local audit log for plans and mutations
- `agent.state`: redacted local state snapshots and diffs
- `nat.port_forward`, `nat.status`, `network.ports`, `internet.ipv6`, `mesh.topology`, `qos.status`, `storage.status`, `system.time`, `system.power`, `wifi.advanced`, `network.ddns`, `network.iptv`, `vpn.wireguard`

Known risky or experimental:

- `router.reboot`: requires `--yes`, interrupts the network.
- `router.led.set`: requires `--yes`; use `--plan` first and verify after changing state or schedule.
- `wifi.toggle`: can disconnect agents if they are on that network.
- `advanced.raw`: escape hatch for endpoint experiments.
- `vpn.client_status`: live-verified read on BE3500 firmware 1.3.5; use `vpn-client-status` for client enablement, profile connections, and device access. A device bypassing VPN does not prove the client is disabled.
- `device.vpn`: experimental. Device-list reads work; routing mutations have not been live revalidated.
- SG VPN requests use URL-encoded plaintext inside encryption, not JSON. See `docs/adr/001-vpn-client-form-encoding.md`; do not diagnose a firmware defect from `no such callback` without checking request encoding.

## Output Contract

All commands should keep useful data on stdout. With `--json`, output is valid JSON and secrets are redacted where the CLI controls serialization. Installed entry points (`tplinkctl`, `tpadmin`) print a clispec error envelope as the last line of stderr and use semantic exit codes: `0` success, `2` usage, `3` not_found, `4` permission, `5` confirmation_required, `6` auth, `1` router/conflict/internal.

The machine-readable CLI contract is:

```bash
tplinkctl schema
tplinkctl schema device
```

`--dry-run` is an alias for `--plan` on mutating commands.

The capability manifest is intentionally stable enough for agents to parse:

```bash
tplinkctl --json capabilities | jq '.capabilities[] | {id, command, type, status, risk}'
```

The tool manifest is intended for wrappers that want MCP-like metadata without importing Python:

```bash
tplinkctl --json tools | jq '.tools[] | {name, read_only, command, risk}'
```

`tplinkctl-mcp` exposes the same tool surface over stdio JSON-RPC:

```bash
TPLINK_MCP_PROFILE=device-admin tplinkctl-mcp
```

MCP tools:

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
- `wifi_config_plan`
- `wifi_config`
- `port_forward_list`
- `port_speed`
- `ipv6_status`
- `mesh_devices`
- `wireguard_status`
- `nat_status`
- `qos_status`
- `storage_status`
- `time_status`
- `power_status`
- `wifi_advanced`
- `ddns_status`
- `iptv_status`
- `doctor_deep`
- `watch`
- `audit_tail`
- `state_snapshot`
- `state_diff`

Mutating MCP tools require `confirm=true`. Agents should call `device_plan` first, show the target MAC/IP and rollback, then call the mutation only when authorized.

`watch` can return an array or stream JSON Lines:

```bash
tplinkctl --json --no-input watch devices --active --count 3 --interval 2
tplinkctl --no-input watch speed --count 10 --interval 1 --stream
```

## HTTP transport and publication privacy

- `tplinkctl-api --help` documents the loopback listener, server-selected profile and explicit remote binding. `TPLINK_API_TOKEN` is a separate API credential; never echo it.
- Metadata is defined in `registry.tools()` and reused by CLI tools/schema, MCP and OpenAPI. Run `python -m tplink_admin.openapi --check docs/openapi.json` after metadata edits.
- HTTP mutations require an expiring, actor/profile/operation/target-bound single-use plan and `confirm=true`. Replan after drift, expiry, restart or uncertain failure; no automatic rollback is promised.
- Watch, audit, snapshots and local state diffs have no HTTP routes. No raw router API or reboot is exposed.
- Use `tests/http_router.py` for HTTP integration. Never perform live router mutations to test HTTP safety.
- Treat live network labels, VPN/provider/location choices, device identifiers, domains, addresses and local paths as private environment data even if they are not secrets. Public fixtures must be synthetic; keep raw probes outside the repo.
- Privacy-check outgoing commits, PR/issue text, reports and artifacts. Secret redaction alone does not make router responses public-safe. Do not upload raw audit or generator logs.
- See `docs/HTTP_API.md`, `docs/forge.md` and ADR 002.

## Commits, PRs and Releases

- Read `VISION.md` before triage or product decisions; it defines what fits and the merge bar.
- Conventional Commits with action-first subjects, e.g. `fix(mcp): reject batches outside 2025-03-26`.
- One coherent change per PR. Fill in `.github/pull_request_template.md`: problem and fix in prose, an exact `Validation:` line, and what was not tested.
- Add user-visible changes to `CHANGELOG.md` under `Unreleased` as they land, one line each, with the PR or issue reference.
- Real contributors keep `Co-authored-by:` credit; no agent attribution trailers.
- A version bump or tag is not a release until the GitHub Release and PyPI upload exist.

## Development Checks

```bash
make test
make smoke
make demo
tplinkctl schema
tplinkctl --json capabilities
tplinkctl --json tools
tplinkctl --json --no-input doctor --deep
```

See `examples/agent-runbook.md` for the full workflow and `examples/transcripts/` for redacted sample outputs.
See `docs/INSTALL_AGENT.md` for install steps, MCP config examples, and `make agent-doctor`.
