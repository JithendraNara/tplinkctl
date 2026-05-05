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

- Start autonomous agents with `TPLINK_MCP_PROFILE=read-only` or `device-admin`.
- Require a plan before mutation: `device_plan` or `tplinkctl device ... --plan`.
- MCP mutation tools require `confirm=true`; agents should show the target hostname, IP, MAC, risk, and rollback before requesting confirmation.
- Use `--reason` on plans and mutations so audit events explain why a change happened.
- Inspect `tplinkctl events --tail 20` after any mutation.

## What To Report

Please open a private security report or contact the maintainer before public disclosure if you find:

- Credential leakage in logs, errors, docs, examples, or audit/state files.
- A command that mutates router state without `--yes` or equivalent confirmation.
- MCP tools that bypass profile restrictions or mutation confirmation.
- Sensitive Wi-Fi keys or router secrets leaking through JSON output.

## Non-Sensitive Reports

Normal router compatibility problems, endpoint failures, and command bugs can use the public issue templates.
