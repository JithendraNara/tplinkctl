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

1. Run `tplinkctl --json capabilities` to inspect available commands, risks, rollback hints, and known firmware issues.
2. Run `tplinkctl --json tools` to discover the local tool surface and command mappings.
3. Start `tplinkctl-mcp` when the agent framework supports stdio JSON-RPC tools.
4. Run `tplinkctl --json --no-input doctor --deep` to verify web UI reachability, authentication, and read-only endpoint health.
5. Run `tplinkctl --json --no-input status` for a human-sized router summary.
6. Run `tplinkctl --json --no-input devices --active` before making device decisions.
7. Use `tplinkctl --json --no-input device <query>` to resolve an exact hostname, IP, or MAC before mutating.

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
TPLINK_PROFILE=network-admin tplinkctl --json --no-input wifi guest_2g on
```

Profiles:

- `read-only`: discovery and read-only inspection, no mutations.
- `device-admin`: device inventory, DHCP reservations, access-control block/unblock, no router-wide toggles.
- `network-admin`: device administration plus Wi-Fi/VPN/reboot, no raw endpoint experiments.
- `dangerous`: no profile-level restrictions.

Mutating commands should include a rollback in the agent plan:

```bash
tplinkctl --json --no-input device block Pixel --plan --enforce
tplinkctl --json --no-input device block Pixel --yes
tplinkctl --json --no-input device unblock Pixel --yes
```

## Agent-Oriented Capabilities

High confidence:

- `router.status`: summary, WAN, Wi-Fi, devices, health
- `device.list`: connected device inventory with IP, MAC, speed, usage, connection type
- `device.show`: exact device lookup
- `device.reserve`: live verified DHCP reservation
- `device.release`: live verified reservation removal
- `device.block`: live verified access-control blacklist insert
- `device.unblock`: live verified blacklist removal
- `wifi.info`: SSIDs, bands, channel state, redacted secrets
- `internet.speed`: current router-reported device throughput
- `internet.speedtest`: external Cloudflare speed test
- `agent.tools`: local tool schemas for agent wrappers
- `agent.watch`: repeated read-only monitoring samples

Known risky or experimental:

- `router.reboot`: requires `--yes`, interrupts the network.
- `wifi.toggle`: can disconnect agents if they are on that network.
- `advanced.raw`: escape hatch for endpoint experiments.
- `device.vpn`: currently marked `firmware_error` on the tested BE3500 firmware.

## Output Contract

All commands should keep useful data on stdout. With `--json`, output is valid JSON and secrets are redacted where the CLI controls serialization. Errors exit non-zero and print the reason.

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
- `device_list`
- `device_show`
- `device_plan`
- `device_block`
- `device_unblock`
- `doctor_deep`
- `watch`

Mutating MCP tools require `confirm=true`. Agents should call `device_plan` first, show the target MAC/IP and rollback, then call the mutation only when authorized.

`watch` can return an array or stream JSON Lines:

```bash
tplinkctl --json --no-input watch devices --active --count 3 --interval 2
tplinkctl --no-input watch speed --count 10 --interval 1 --stream
```

## Development Checks

```bash
make test
make smoke
tplinkctl --json capabilities
tplinkctl --json tools
tplinkctl --json --no-input doctor --deep
```
