# ADR 002: registry-backed HTTP contracts and downstream SDK artifacts

## Decision

Retain the CLI/router command boundary and canonicalize the tool manifest in
`registry.py`. CLI tools/schema, MCP discovery and the OpenAPI emitter consume
that registry. Domain paths under `/v1` are explicit metadata, not arbitrary
router-endpoint forwarding. Local filesystem/stream tools are classified rather
than remotely exposed. The registry contains extensible response models where
firmware-specific fields cannot be promised.

Use a serialized authenticated HTTP listener with server-selected policy.
Explicit remote binding is opt-in. Separate API authentication from mutation
authorization: plans are in-memory, time-bounded, single-use capabilities tied to
actor/profile/operation/normalized arguments and the observed target/state.
Consume before upstream access; recheck freshness in one locked router session.
No automatic retries or transactional rollback claims. Keep CLI/MCP confirmation
semantics; HTTP adds the stricter plan artifact requirement.

Use pinned Cloudflare Forge only downstream. Validate the bundled OAS and JSON
Schema locally, then generate on Linux with Docker, compile TypeScript and invoke
a real generated read method against an authenticated mock server. Promote output
atomically only after schema/map/compile/smoke checks. Reports contain safe phase
categories, not arbitrary upstream logs.

## Issue acceptance evidence

- **#8 HTTP API:** `tplinkctl-api` startup/help; default loopback/read-only;
  domain routes, Bearer auth and server policy. The read-route integration test
  exercises registered GET routes through actual CLI handlers and a synthetic
  router. README, AGENTS and HTTP_API document the boundary. No live mutation.
- **#9 safety:** HTTP tests cover missing/false/wrong-type confirmation, expired
  plans, actor/profile/operation/argument mismatch, target drift, concurrent
  replays, uncertain outcomes, manual rollback limits and redacted audit.
- **#10 generated spec:** deterministic `openapi.py`, checked-in artifact,
  local-only classifications, risk/profile/plan/rollback extensions; OAS 3.1.2
  validation and parameter/schema parity tests. The CLI's existing missing
  `wireguard` operation mapping caused read-profile HTTP 403 and was fixed at
  its CLI owner, not bypassed in HTTP. The regression was reproduced before fix.
- **#11 Forge:** Linux generation against the real bundled document reached
  generation, TypeScript compile and generated-client mock HTTP successfully.
  The first full-spec smoke exposed a missing SDK bearer credential; supplying
  an ephemeral synthetic token and checking its request header fixed it. Pins,
  image digest and narrow upstream packager adjustments are documented in
  `docs/forge.md`. A real ungrouped-spec failure verifies no partial output.
- **#12 contracts:** metadata/parameter/safety parity across discovery surfaces,
  fake-router reads and planned mutations through real HTTP, schema validation,
  generated-client compile/smoke and CI artifact workflow. An invalid-schema
  negative fixture exposed the OAS validator accepting an invalid `type` value;
  explicit JSON Schema checking now rejects it.

Local recovery validation passed 109 Python unit tests on macOS and Linux;
Linux additionally passed all five Forge CLI tests including actual Docker
failure cleanup. Forge validated/generated 29 HTTP operations from input SHA256
`f8892e979bf4eb42ee4d51276ee7a7da2a32a1f2eb38db901e2746df00a4152b`.
These are local verification results, not a claim of published CI or a release.
These figures describe the initial implementation checkpoint, not the final release.
The later implementation head `d42cb80` passed 115 tests and exact-head Python
3.10/3.11/3.12 plus Forge CI (runs 40169773418 and 40169773614). Release changes
must pass those gates again; release status is recorded on GitHub.

## Independent review hardening

Five defects were reproduced through the real loopback HTTP boundary before
repair; the new regressions failed in seven subcases on the original code:

1. Nested Wi-Fi error dictionaries carried raw exception diagnostics. HTTP now
   redacts every diagnostic descendant while preserving container shape; injected
   synthetic secret/path values are absent from the returned body.
2. An enforcement plan missed same-count policy membership changes. Plans now
   bind the full sorted blacklist and whitelist when changing global enforcement
   and expose those affected policies with the target. Replacing a member yields
   conflict before any write.
3. Wi-Fi settings, LED schedule times and Access Control mode/enabled could be
   acknowledged without taking effect. Their CLI owners now compare read-back
   fields before returning success. HTTP records failed/unknown outcome and keeps
   the consumed plan unusable when read-back disagrees.
4. Random plan IDs could begin with a hyphen and fail the CLI-option guard. The
   guard now excludes the server-only plan identifier, which is never forwarded
   to argparse. A deterministic leading-hyphen plan executes once.
5. Missing blacklist entries raised an untyped exit and MCP discarded semantic
   kinds. The CLI owner now raises `not_found`; HTTP maps to 404 and MCP returns
   the safe JSON error envelope while retaining `isError: true`.

The repaired suite passed 114 Python tests on macOS and Linux; the Linux
installed-package startup and wheel build also passed. Exact-head CI remains a
publication closeout gate.

A subsequent hosted review identified a separate authentication-boundary defect:
missing server-side router credentials challenged a valid API bearer with 401.
The actual missing-password path was reproduced in a failing HTTP test. Router
credential errors now retain semantic `auth` but return 502 without a Bearer
challenge; invalid caller credentials remain 401. OpenAPI explicitly documents
this upstream-status override. The regression verifies no SDK construction occurs.

## Release packaging and documentation audit

The release audit reproduced missing HTTP fixtures and contract tooling in the
source archive. `MANIFEST.in` now includes documentation, examples, fixtures and
validation tools; a clean wheel install and extracted-source tests verify the
artifact rather than relying on the checkout. Requirements-file dependencies
match the package runtime dependencies.

Legacy key material and identifying network fixtures were replaced with explicit
synthetic values. This change does not erase prior Git history or establish
whether legacy material was ever used on a router. CLI/MCP profile restrictions
are opt-in; HTTP alone defaults to read-only. No live mutation was performed.

## Constraints

Plans disappear on restart. Router firmware and independent admin/UI users are
outside the local lock; fresh reads reduce but cannot eliminate external races.
Once an attempt has begun, a failed response does not prove no router change.
A response schema is a compatibility contract, not an automatic privacy filter:
operational device/network data stays private and must not become public test
fixtures. Only synthetic data is used in CI.

## References

- https://spec.openapis.org/oas/v3.1.2.html
- https://cheatsheetseries.owasp.org/cheatsheets/Transaction_Authorization_Cheat_Sheet.html
- https://github.com/cloudflare/forge/tree/cfe397c296a5e6d9fce01eb335ed805821e5547c
