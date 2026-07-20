# Contributing

This repo is intentionally small and tool-shaped.

## Development

```bash
python3 -m venv .venv
.venv/bin/python -m pip install .
make test
make smoke
```

## Safety Rules

- Read-only commands should work with `--json --no-input`.
- Mutating commands must be explicit and discoverable.
- Dangerous commands must require `--yes` or another clear confirmation.
- Do not store router passwords in config files.
- Prefer adding a high-level command over making users reach for `raw`.

## Endpoint Promotion

Before turning a discovered endpoint into a first-class command:

1. Capture where it appears with `tplinkctl endpoints`.
2. Verify it live with `tplinkctl read` or `tplinkctl raw`.
3. Add a unit test with mocked router behavior.
4. Document the command in `README.md`.
