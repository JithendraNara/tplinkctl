# Forge SDK and documentation generation

Forge is downstream build tooling, not a runtime dependency or authorization
mechanism. `tooling/forge/pins.json` records the exact upstream source revision,
package-manager version and Fern generator image digest. Its source lockfile
pins build dependencies. Runtime authorization remains in `tplink_admin.api`.

## Validating locally without Docker

```sh
python -m pip install '.[test]'
python -m tplink_admin.openapi --check docs/openapi.json
python scripts/forge_generate.py validate --spec docs/openapi.json
python scripts/forge_test.py
```

Validation rejects external references before resolving schemas, invalid JSON
Schema, duplicate/missing operation IDs and ignored operations.

## Linux generation

Requirements: Linux, Git, Node 22+, npm/npx, Python with the test extra, and a
working Docker daemon. No cloud account, router credentials or production API
access is required. Use a fresh output path; existing output is never replaced.

```sh
mkdir -p artifacts
python scripts/forge_generate.py generate \
  --spec docs/openapi.json \
  --output artifacts/sdk \
  --report artifacts/forge-report.json
python scripts/forge_test.py --docker-failure
```

This fetches the pinned public Forge revision, installs using its frozen pnpm
lockfile, builds its TypeScript transformer, runs the actual Docker-backed Fern
generator, verifies every operation against `sdk-map.json`, compiles the generated
TypeScript, and calls generated `router_status` against an authenticated mock
HTTP server using an ephemeral synthetic credential. The returned data must
match the schema and synthetic response fixture. It is not a direct `fetch`
substitute for the generated client method.

Final output includes `openapi.json`, `sdk/` source and `sdk-map.json`, compiled
JavaScript, `api-reference.md`, and `evidence.json`. The reference is generated
from finalized operations and the Forge SDK map; it is not a hosted docs site.
The input SHA256 is recorded in the evidence report.

Generation uses an isolated environment and staging directory. Only fully
validated output is renamed into place. Failure leaves existing bundles intact
and no partial final directory. JSON reports include phase, exit code and bounded
diagnostic categories, not raw upstream logs, process environments or paths.
The CI workflow uploads the finalized artifact bundle and safe validation report.

## Narrow compatibility adjustments

The pinned Forge source expects internal fixture files in its packager. The
wrapper supplies the actual input document to both expected fixture locations,
never a Cloudflare baseline or a synthetic replacement. It also patches the
pinned image-building script to use the recorded image digest in every source
image reference while preserving upstream's local wrapper-tag convention.
Anchor checks fail closed if source layout changes.

The generated client still uses upstream's `CloudflareApiClient` class name.
No vendored runtime rename or generic generator substitution is performed.
The smoke test reads method/accessor names from `sdk-map.json`. Forge is currently
early-stage tooling; upgrades need a new source/image pin plus the full contract,
compile, mock-HTTP and failure-path suite, not just a successful install.

`tooling/forge/probe.json` is solely a synthetic failure-path fixture. CI success
requires generation against the real `docs/openapi.json`.

## References

- [Cloudflare Forge](https://github.com/cloudflare/forge)
- [Pinned Forge source](https://github.com/cloudflare/forge/tree/cfe397c296a5e6d9fce01eb335ed805821e5547c)
- [OpenAPI 3.1.2](https://spec.openapis.org/oas/v3.1.2.html)
