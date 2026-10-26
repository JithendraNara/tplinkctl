# Vision

`tplinkctl` is a pragmatic local admin tool for TP-Link Archer BE-series routers,
built for humans, shell scripts and AI agents. The CLI is the product. The MCP
server and HTTP API are thin transports over the same command registry and the
same safety policy.

It should expose the router operations people actually need, with stable
scriptable output, predictable safety controls and errors that say what to do
next. It does not need to cover every endpoint the router's web UI can reach.

## What Fits

- Bug fixes, especially for commands that already exist.
- Small read-only commands for router areas the firmware already exposes and
  that have been verified on real hardware.
- Agent-friendly behavior: `--json`/`--plain`, `--no-input`, semantic exit
  codes, plans before mutations, and clear permission errors.
- Safety and reliability work: profiles, confirmation, audit, redaction,
  session handling and error sanitization.
- Protocol conformance for the MCP and HTTP transports, verified against the
  official schemas and real clients.
- Docs, tests and generated contracts that keep the CLI, MCP and HTTP surfaces
  in agreement.

## Discuss First

- New mutations. Each one needs a plan, a rollback contract, a profile
  placement and live proof on a router you own.
- Support for router families other than Archer BE-series, or a new SDK.
- Changes to profile semantics, defaults, or anything that widens what an
  agent can do without opting in.
- New dependencies, background daemons, or remote (non-loopback) exposure.
- Behavior changes that could break existing scripts or tool contracts.
- Anything that cannot be verified against real firmware when firmware
  behavior is the point of the change.

## Non-Goals

- Firmware flashing, shell or root access, and enabling hidden firmware
  features.
- Cloud (TP-Link ID / Deco app) management.
- A web UI.
- Reimplementing the router's full admin surface one endpoint at a time.

## Merge Bar

Small fixes and verified read-only commands merge after tests pass, the
changelog and docs are updated for user-visible changes, and the PR states how
it was validated. Mutations and transport changes also need proof at the real
boundary: a live router run for firmware behavior, and the official client or
schema for protocol behavior.

If live testing is blocked, say exactly what is missing (router model,
firmware, credential) instead of merging on unit tests alone.

## Privacy

This is a public repository. Real addresses, MAC addresses, device names, VPN
locations, paths and environment values never land in code, fixtures, issues
or PRs. Use synthetic data.
