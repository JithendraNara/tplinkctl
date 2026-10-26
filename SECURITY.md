# Security Policy

`tplinkctl` controls local router state. Treat router credentials and device identifiers as sensitive operational data.

## Router Password Rules

- Do not commit real router passwords, session tokens, exported config files, or shell history.
- Prefer `TPLINK_PASSWORD` from a local shell, password manager, or agent secret store.
- Avoid `--password` in commands because it can appear in shell history and process lists.
- Do not paste real passwords into issues, pull requests, transcripts, screenshots, or agent prompts.
- Use placeholders such as `TPLINK_PASSWORD=...` or `set-this-in-your-agent-secret-store` in docs and examples.
- Rotate the router admin password immediately if it is exposed.

## Agent Safety Rules

- `tplinkctl-mcp` defaults to `read-only`. Grant an agent more only by setting `TPLINK_MCP_PROFILE` explicitly (prefer `device-admin` over broader profiles).
- MCP tool results never include upstream exception text; `TPLINK_MCP_DEBUG=1` logs it to stderr with router session tokens redacted. Leave it off unless debugging, because client hosts often persist server stderr.
- Require a plan before mutation: `device_plan` or `tplinkctl device ... --plan`.
- MCP mutation tools require `confirm=true`; agents should show the target hostname, IP, MAC, risk, and rollback before requesting confirmation.
- Use `--reason` on plans and mutations so audit events explain why a change happened.
- Inspect `tplinkctl events --tail 20` after any mutation.

## HTTP Boundary

- `tplinkctl-api` defaults to loopback and a read-only server profile. Use a separate random `TPLINK_API_TOKEN`; never reuse router credentials.
- HTTP mutations require an expiring, state-bound, single-use plan plus explicit confirmation. A failed response may follow a partial router change; inspect state and replan rather than blindly retrying.
- CLI/MCP confirmation rules are unchanged; their plan previews are not the HTTP single-use authorization mechanism.
- Public reports must use synthetic network labels, device identifiers and addresses. Redacted operational responses can still identify a private environment.

## What To Report

Please open a private security report or contact the maintainer before public disclosure if you find:

- Credential leakage in logs, errors, docs, examples, or audit/state files.
- A command that mutates router state without `--yes` or equivalent confirmation.
- MCP tools that bypass profile restrictions or mutation confirmation.
- Sensitive Wi-Fi keys or router secrets leaking through JSON output.

## Non-Sensitive Reports

Normal router compatibility problems, endpoint failures, and command bugs can use the public issue templates.
