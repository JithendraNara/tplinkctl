# tplinkctl

Tiny, scriptable CLI for a local TP-Link router admin page such as `http://192.168.0.1/webpages/index.html#/internetAdv`.

This wrapper uses [`tplinkrouterc6u`](https://pypi.org/project/tplinkrouterc6u/), which currently lists Archer BE220 v1.0 support and handles TP-Link's login encryption/session flow.

## Why

Router admin pages are slow, stateful, and annoying to automate. `tplinkctl` turns the useful parts into a local-first command line:

- JSON-first output for `jq`, agents, and scripts
- Safe defaults: no password stored, no overlapping sessions, dangerous commands require confirmation
- Real router UI discovery: extract routes and API endpoints from TP-Link's bundled JavaScript
- Escape hatches: `read` and `raw` for endpoint experiments

## Install

Use Python 3.10+.

```bash
/Users/jithendranara/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m venv .venv
.venv/bin/python -m pip install .
```

## Quick Start

```bash
tplinkctl config set --host http://192.168.0.1 --username admin --client sg
export TPLINK_PASSWORD='your-local-router-password'

tplinkctl doctor
tplinkctl --json health
tplinkctl --json status
tplinkctl devices --active
tplinkctl device Pixel
tplinkctl speed
tplinkctl wifi-info
tplinkctl speedtest --skip-upload
tplinkctl --json wan
tplinkctl --json firmware
```

Prefer `TPLINK_PASSWORD` or the interactive password prompt over `--password`, so the password is not left in shell history.

## Commands

```bash
tplinkctl firmware
tplinkctl health
tplinkctl status
tplinkctl snapshot
tplinkctl wan
tplinkctl devices --active --sort usage
tplinkctl devices --connection host_5g --sort signal
tplinkctl device 192.168.0.40
tplinkctl speed --top 10
tplinkctl speedtest
tplinkctl wifi-info
tplinkctl wifi-info --group guest
tplinkctl wifi-status
tplinkctl ipv4
tplinkctl leases
tplinkctl reservations
tplinkctl clients --active
tplinkctl wifi guest_2g on
tplinkctl wifi guest_2g off
tplinkctl vpn-status
tplinkctl vpn-client-status
tplinkctl reboot --yes
```

## Config

```bash
tplinkctl config path
tplinkctl config show
tplinkctl config set --host http://192.168.0.1 --client sg --timeout 30
```

Config stores non-secret defaults in `~/.config/tplink-admin/config.json`. Environment variables override config:

```bash
TPLINK_HOST=http://192.168.0.1
TPLINK_USERNAME=admin
TPLINK_CLIENT=sg
TPLINK_TIMEOUT=30
TPLINK_PASSWORD=...
TPLINK_JSON=1
TPLINK_ENABLE_COMMANDS=status,clients,leases
TPLINK_DISABLE_COMMANDS=reboot,wifi
```

## Agent-Friendly Use

Data goes to stdout. Use `--json` for machine-readable output and `--no-input` when an agent should fail instead of prompting:

```bash
tplinkctl --json --no-input health
tplinkctl --json --no-input status | jq '.router, .wan, .wifi.networks, .devices[] | {hostname, ip, connection, active, down, up, usage}'
tplinkctl --json --enable-commands status,devices devices --active
tplinkctl --disable-commands reboot,wifi status
```

`doctor` checks that the router web UI is reachable and reports page metadata without logging in:

```bash
tplinkctl --json doctor
```

Authenticated commands are serialized with a local lock by default because the router login flow can reject overlapping sessions. Use `--no-lock` only when you are deliberately testing concurrency.

## UI Discovery

Map router pages and mine API-looking endpoints from downloaded bundles:

```bash
scripts/mirror_ui.py --host http://192.168.0.1 --out .
tplinkctl --json routes --name internet
tplinkctl --json endpoints --form network
```

On this router, `#/internetAdv` maps to `index-BOBVatjl.js`, which exposes internet-related endpoints like port speed, WAN flow control, and IPv4 status. See [docs/ENDPOINTS.md](docs/ENDPOINTS.md).

## Raw Mode

The `raw` command is for experiments with endpoint paths discovered from the router's JavaScript bundle:

```bash
tplinkctl --json read '/admin/network?form=status_ipv4'
tplinkctl --json raw '/admin/network?form=status_ipv4' --data 'operation=read'
```

Quote endpoint paths in shells like `zsh`, because `?` is a glob character.

## Development

```bash
make test
make smoke
make doctor
```

## Prior Art

The project shape follows the “small sharp CLI” style used across Peter Steinberger's tools: short command name, direct install path, config/env support, scriptable stdout, agent-safe flags, and an escape hatch for power users.

Relevant TP-Link libraries/projects:

- [`tplinkrouterc6u`](https://pypi.org/project/tplinkrouterc6u/) / [`TP-Link-Archer-C6U`](https://github.com/AlexandrErohin/TP-Link-Archer-C6U)
- [`node-tplink-api`](https://github.com/hertzg/node-tplink-api)
- [`tplink-wr-api`](https://pypi.org/project/tplink-wr-api/)
