# HTTP API and contract

Start the optional HTTP transport with `tplinkctl-api --help` (equivalently,
`python -m tplink_admin.api --help`). CLI and stdio MCP remain available.

## Startup and authentication

Supply router configuration through the existing environment/config mechanism.
Supply a **separate**, randomly generated API credential through
`TPLINK_API_TOKEN` (at least 32 ASCII characters). Never reuse a router password,
put credentials in URLs, commit them, or paste them into logs.

```sh
tplinkctl-api --profile read-only
```

The default listener is `127.0.0.1:8765`. Each request, including
`GET /v1/openapi.json`, requires `Authorization: Bearer <credential>`.
The command-line profile is fixed server-side; request parameters cannot change
it. Use `device-admin` for device block/unblock or `network-admin` for LED and
radio configuration. The `dangerous` profile does not expose raw router APIs.

LAN/Tailscale listening requires an explicit numeric `--bind` and
`--allow-remote`. Use an encrypted tunnel or a trusted TLS reverse proxy when
credentials cross an untrusted network. The built-in transport is a serialized
local control service, not an Internet-facing multi-tenant server. Browser-origin
requests are rejected; no CORS integration is provided. Requests have bounded
body size and socket timeouts. Router sessions are serialized.

A local Python client can read without printing credentials:

```python
import os
import requests

client = requests.Session()
client.headers["Authorization"] = "Bearer " + os.environ["TPLINK_API_TOKEN"]
response = client.get("http://127.0.0.1:8765/v1/router/status", timeout=30)
response.raise_for_status()
status = response.json()["data"]
```

Responses are operational data, **not publishable fixtures**. Device identifiers,
network labels and other non-secret environment values may be needed by an
operator. Secret redaction does not make a response suitable for a public issue.
Use synthetic examples when reporting bugs.

## Resources and discovery

`registry.tools()` is the shared CLI-tool/MCP/OpenAPI metadata source. It defines
stable operation IDs, input/output schemas, domain routes, profiles, risk,
plan-operation and rollback metadata. `/v1` resources cover router status,
firmware audit, LED, devices, Wi-Fi, VPN, NAT, mesh, network, QoS, storage,
system time/power and health. See `docs/openapi.json` for exact paths and schemas.

Read operations return `{"data": ...}`. Local watch/audit/snapshot/diff tools are
explicitly classified in `x-tplinkctl-local-only`; they have no HTTP routes.
`--json tools`, `schema` and MCP retain their existing interfaces, with additive
metadata and read tools. Firmware-dependent fields remain extensible objects.

Generate or verify the bundled description without contacting a router:

```sh
python -m tplink_admin.openapi > docs/openapi.json
python -m tplink_admin.openapi --check docs/openapi.json
python scripts/forge_generate.py validate --spec docs/openapi.json
```

## Plan, confirm, execute

HTTP mutations are limited to LED changes, Wi-Fi radio configuration and device
block/unblock. The HTTP server does not expose reboot or raw writes.

1. Request the matching plan endpoint with the intended arguments.
2. Review target, normalized diff, risk, expiry and rollback limitations.
3. Send the **same operation arguments**, the returned `plan_id` and literal
   `confirm: true` to the execution endpoint.
4. Inspect returned state; after any uncertain upstream failure read state and
   obtain a fresh plan rather than retrying the mutation.

For example, plan an LED change with `POST /v1/router/led/plans` and
`{"action":"off"}`. After explicit operator approval, execute
`PUT /v1/router/led` with that action, returned plan ID and `confirm:true`.
A JSON confirmation boolean alone cannot authorize a write.

Plans are held in server memory, default to 120 seconds (maximum 600), and
bind actor, server profile, operation, normalized arguments and target/state.
Restart invalidates every plan. Execution consumes the plan before upstream
access, rechecks expiry and state within one router session, and pins a device
mutation to its previously resolved MAC. Replayed, expired, altered, wrong-actor
or changed-state requests are rejected. This provides **at-most-one execution
attempt per plan**, not exactly-once delivery to the router or transactional
rollback. Concurrent router UI users can still change state independently.

Rollback is manual guidance derived from observed state. An enforced device
block can change global Access Control; unblock alone does not restore global
policy, so that plan reports incomplete rollback support. Never treat the
metadata as automatic recovery.

Plans/attempts/results use the existing local JSONL event path with HTTP
operation, target, actor, profile, result and redacted reason. Free-form reasons,
API credentials and plan IDs are not written to audit. Audit and router outputs
are not uploaded as CI artifacts.

## Errors

The response body preserves `error.kind`: usage 400, authentication 401,
permission 403, not-found 404, confirmation/plan conflict 409, router/upstream
502, and internal 500. Untrusted router exception text is not returned.

## Verification and references

`tests/test_http.py` exercises a real loopback HTTP listener against the same CLI
commands and synthetic router protocol fixture used for authorization, planning,
execution, redaction and contract checks. CI uses no live router credentials.

- [OpenAPI 3.1.2](https://spec.openapis.org/oas/v3.1.2.html): schemas, parameters, operation IDs and extensions.
- [OWASP transaction authorization](https://cheatsheetseries.owasp.org/cheatsheets/Transaction_Authorization_Cheat_Sheet.html): server-side enforcement, bound transaction details, final execution checks, limited lifetime and unique credentials.
- [Forge integration](forge.md): downstream generation, pins and artifact checks.
