"""Small stdio JSON-RPC tool server for tplinkctl.

This intentionally avoids an MCP SDK dependency. It implements the legacy
(initialize-handshake) MCP era, protocol revisions 2024-11-05 through
2025-11-25: `initialize`, `ping`, `tools/list` and `tools/call` over
newline-delimited JSON-RPC on stdio. Responses are shaped for the negotiated
revision. Content-Length (LSP-style) framed input from earlier builds of this
server is still accepted. Modern-era (2026-07-28) clients probing
`server/discover` receive -32601 and fall back to `initialize`, per that
revision's stdio backward-compatibility rules.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import sys
import time
from collections.abc import Callable
from typing import Any

from . import __version__, cli

SERVER_NAME = "tplinkctl-mcp"
# Newest first. 2026-07-28 (stateless, server/discover) is intentionally not
# claimed yet; see issue #17 for the recorded decision.
SUPPORTED_PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[0]
# Least privilege: without an explicit profile the MCP server is read-only.
DEFAULT_PROFILE = "read-only"

SERVER_INSTRUCTIONS = """\
tplinkctl manages one home TP-Link router. Rules for every tool call:
- Prefer the *_plan tool before any mutation tool, and show the plan to the user.
- Mutation tools require confirm=true, which means the user explicitly agreed
  after seeing the plan — never set it on the user's behalf.
- Tools are gated by the server's permission profile (read-only unless the
  operator configured another); a permission error means the operation is not
  allowed here, not that it should be retried differently.
- Do not surface device MAC addresses, credentials, or private keys unless the
  user explicitly asks for that specific value.
- Read-only status tools are safe to call whenever current router state matters;
  do not guess state from earlier calls."""


def base_argv() -> list[str]:
    argv = ["--json", "--no-input"]
    profile = os.getenv("TPLINK_MCP_PROFILE") or os.getenv(cli.PROFILE_ENV) or DEFAULT_PROFILE
    argv.extend(["--profile", profile])
    return argv


def bool_arg(arguments: dict[str, Any], name: str, default: bool = False) -> bool:
    value = arguments.get(name, default)
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return default
    return cli.bool_arg(str(value))


def positive_int(arguments: dict[str, Any], name: str, default: int) -> int:
    value = int(arguments.get(name, default))
    if value < 1:
        raise ValueError(f"{name} must be >= 1")
    return value


def string_arg(arguments: dict[str, Any], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value


def require_confirmation(arguments: dict[str, Any], action: str) -> None:
    if not bool_arg(arguments, "confirm", False):
        raise ValueError(f"{action} requires confirm=true")


def argv_status(_: dict[str, Any]) -> list[str]:
    return base_argv() + ["status"]


def argv_firmware_audit(_: dict[str, Any]) -> list[str]:
    return base_argv() + ["firmware-check"]


def argv_led_status(_: dict[str, Any]) -> list[str]:
    return base_argv() + ["led", "status"]


def led_change_argv(arguments: dict[str, Any], *, plan: bool) -> list[str]:
    action = string_arg(arguments, "action")
    if action not in {"on", "off", "schedule"}:
        raise ValueError("action must be one of: on, off, schedule")
    argv = base_argv() + ["led", action]
    if action == "schedule":
        if "enabled" not in arguments:
            raise ValueError("enabled is required for a schedule change")
        argv.append("on" if bool_arg(arguments, "enabled") else "off")
        if start := arguments.get("start"):
            argv.extend(["--start", str(start)])
        if end := arguments.get("end"):
            argv.extend(["--end", str(end)])
    argv.append("--plan" if plan else "--yes")
    return argv


def argv_led_plan(arguments: dict[str, Any]) -> list[str]:
    return led_change_argv(arguments, plan=True)


def argv_led_set(arguments: dict[str, Any]) -> list[str]:
    require_confirmation(arguments, "led_set")
    return led_change_argv(arguments, plan=False)


def argv_devices(arguments: dict[str, Any]) -> list[str]:
    argv = base_argv() + ["devices"]
    if bool_arg(arguments, "active", False):
        argv.append("--active")
    if sort := arguments.get("sort"):
        argv.extend(["--sort", str(sort)])
    if top := arguments.get("top"):
        argv.extend(["--top", str(positive_int(arguments, "top", int(top)))])
    return argv


def argv_device_show(arguments: dict[str, Any]) -> list[str]:
    return base_argv() + ["device", string_arg(arguments, "query")]


def argv_device_plan(arguments: dict[str, Any]) -> list[str]:
    action = string_arg(arguments, "action")
    if action not in {"reserve", "release", "block", "unblock"}:
        raise ValueError("action must be one of: reserve, release, block, unblock")
    argv = base_argv() + ["device", action, string_arg(arguments, "query"), "--plan"]
    if action == "block" and bool_arg(arguments, "enforce", False):
        argv.append("--enforce")
    if action == "reserve":
        if ip := arguments.get("ip"):
            argv.extend(["--ip", str(ip)])
        if name := arguments.get("name"):
            argv.extend(["--name", str(name)])
    return argv


def argv_device_block(arguments: dict[str, Any]) -> list[str]:
    require_confirmation(arguments, "device_block")
    argv = base_argv() + ["device", "block", string_arg(arguments, "query"), "--yes"]
    if bool_arg(arguments, "enforce", False):
        argv.append("--enforce")
    return argv


def argv_device_unblock(arguments: dict[str, Any]) -> list[str]:
    require_confirmation(arguments, "device_unblock")
    return base_argv() + ["device", "unblock", string_arg(arguments, "query"), "--yes"]


def argv_doctor_deep(_: dict[str, Any]) -> list[str]:
    return base_argv() + ["doctor", "--deep"]


def argv_watch(arguments: dict[str, Any]) -> list[str]:
    target = str(arguments.get("target", "devices"))
    if target not in {"status", "devices", "speed", "health"}:
        raise ValueError("target must be one of: status, devices, speed, health")
    argv = base_argv() + ["watch", target, "--count", str(positive_int(arguments, "count", 1))]
    if interval := arguments.get("interval"):
        argv.extend(["--interval", str(float(interval))])
    if target == "devices" and bool_arg(arguments, "active", False):
        argv.append("--active")
    if target in {"devices", "speed"} and (top := arguments.get("top")):
        argv.extend(["--top", str(positive_int(arguments, "top", int(top)))])
    return argv


def argv_audit_tail(arguments: dict[str, Any]) -> list[str]:
    argv = base_argv() + ["events", "--tail", str(positive_int(arguments, "tail", 20))]
    if operation := arguments.get("operation"):
        argv.extend(["--operation", str(operation)])
    return argv


def argv_state_snapshot(arguments: dict[str, Any]) -> list[str]:
    argv = base_argv() + ["state", "save"]
    if name := arguments.get("name"):
        argv.extend(["--name", str(name)])
    return argv


def argv_state_diff(arguments: dict[str, Any]) -> list[str]:
    argv = base_argv() + ["state", "diff"]
    if before := arguments.get("before"):
        argv.extend(["--before", str(before)])
    if after := arguments.get("after"):
        argv.extend(["--after", str(after)])
    if limit := arguments.get("limit"):
        argv.extend(["--limit", str(positive_int(arguments, "limit", int(limit)))])
    if bool_arg(arguments, "raw", False):
        argv.append("--raw")
    if only := arguments.get("only"):
        argv.extend(["--only", str(only)])
    ignore = arguments.get("ignore") or []
    if isinstance(ignore, str):
        ignore = [ignore]
    for item in ignore:
        argv.extend(["--ignore", str(item)])
    return argv


def argv_wifi_config(arguments: dict[str, Any], *, plan: bool) -> list[str]:
    connection = string_arg(arguments, "connection")
    argv = base_argv() + ["wifi-config", connection]
    if channel := arguments.get("channel"):
        argv.extend(["--channel", str(channel)])
    if width := arguments.get("width"):
        argv.extend(["--width", str(width)])
    if txpower := arguments.get("txpower"):
        argv.extend(["--txpower", str(txpower)])
    if ssid := arguments.get("ssid"):
        argv.extend(["--ssid", str(ssid)])
    if plan or bool_arg(arguments, "plan", False):
        argv.append("--plan")
    else:
        require_confirmation(arguments, "wifi_config")
        argv.append("--yes")
    return argv


def argv_port_forward(_: dict[str, Any]) -> list[str]:
    return base_argv() + ["port-forward"]


def argv_port_speed(_: dict[str, Any]) -> list[str]:
    return base_argv() + ["ports"]


def argv_ipv6_status(_: dict[str, Any]) -> list[str]:
    return base_argv() + ["ipv6"]


def argv_mesh_devices(_: dict[str, Any]) -> list[str]:
    return base_argv() + ["mesh"]


def argv_wireguard_status(_: dict[str, Any]) -> list[str]:
    return base_argv() + ["wireguard"]


def argv_nat(_: dict[str, Any]) -> list[str]:
    return base_argv() + ["nat"]


def argv_qos(_: dict[str, Any]) -> list[str]:
    return base_argv() + ["qos"]


def argv_storage(_: dict[str, Any]) -> list[str]:
    return base_argv() + ["storage"]


def argv_time(_: dict[str, Any]) -> list[str]:
    return base_argv() + ["time"]


def argv_power(_: dict[str, Any]) -> list[str]:
    return base_argv() + ["power"]


def argv_wifi_advanced(_: dict[str, Any]) -> list[str]:
    return base_argv() + ["wifi-advanced"]


def argv_ddns(_: dict[str, Any]) -> list[str]:
    return base_argv() + ["ddns"]


def argv_iptv(_: dict[str, Any]) -> list[str]:
    return base_argv() + ["iptv"]


TOOL_BUILDERS: dict[str, Callable[[dict[str, Any]], list[str]]] = {
    "wifi_info": lambda _: base_argv() + ["wifi-info"],
    "vpn_status": lambda _: base_argv() + ["vpn-status"],
    "vpn_client_status": lambda _: base_argv() + ["vpn-client-status"],
    "router_status": argv_status,
    "firmware_audit": argv_firmware_audit,
    "led_status": argv_led_status,
    "led_plan": argv_led_plan,
    "led_set": argv_led_set,
    "device_list": argv_devices,
    "device_show": argv_device_show,
    "device_plan": argv_device_plan,
    "device_block": argv_device_block,
    "device_unblock": argv_device_unblock,
    "wifi_config_plan": lambda args: argv_wifi_config(args, plan=True),
    "wifi_config": lambda args: argv_wifi_config(args, plan=False),
    "port_forward_list": argv_port_forward,
    "port_speed": argv_port_speed,
    "ipv6_status": argv_ipv6_status,
    "mesh_devices": argv_mesh_devices,
    "wireguard_status": argv_wireguard_status,
    "nat_status": argv_nat,
    "qos_status": argv_qos,
    "storage_status": argv_storage,
    "time_status": argv_time,
    "power_status": argv_power,
    "wifi_advanced": argv_wifi_advanced,
    "ddns_status": argv_ddns,
    "iptv_status": argv_iptv,
    "doctor_deep": argv_doctor_deep,
    "watch": argv_watch,
    "audit_tail": argv_audit_tail,
    "state_snapshot": argv_state_snapshot,
    "state_diff": argv_state_diff,
}


# --- Tool metadata -----------------------------------------------------------

# Registry `read_only` means "never changes router state" (it drives profiles and
# HTTP). MCP annotations describe the tool's whole environment, so tools that
# write local files are not read-only there.
LOCAL_WRITE_TOOLS = {"state_snapshot"}

_TITLE_WORDS = {
    "wifi": "Wi-Fi", "ipv6": "IPv6", "vpn": "VPN", "led": "LED", "ddns": "DDNS",
    "iptv": "IPTV", "nat": "NAT", "qos": "QoS", "wireguard": "WireGuard",
}


def tool_title(name: str) -> str:
    return " ".join(_TITLE_WORDS.get(word, word.capitalize()) for word in name.split("_"))


def tool_annotations(item: dict[str, Any]) -> dict[str, bool]:
    """Spec-accurate hints (2025-11-25 ToolAnnotations definitions)."""
    if item["name"] in LOCAL_WRITE_TOOLS:
        # Adds a new snapshot file: not read-only, purely additive, and each
        # call creates another snapshot.
        return {"readOnlyHint": False, "destructiveHint": False,
                "idempotentHint": False, "openWorldHint": False}
    if item["read_only"]:
        # destructive/idempotent hints are only meaningful when readOnlyHint is false.
        return {"readOnlyHint": True, "openWorldHint": False}
    # Every router mutation sets a value or removes an entry: it overwrites or
    # deletes existing state (destructive: not purely additive), and repeating
    # it with the same arguments has no further effect (idempotent).
    return {"readOnlyHint": False, "destructiveHint": True,
            "idempotentHint": True, "openWorldHint": False}


def wraps_array_output(item: dict[str, Any]) -> bool:
    return item["output_schema"].get("type") != "object"


def mcp_output_schema(item: dict[str, Any]) -> dict[str, Any]:
    """Adapt the registry schema to MCP's object-only outputSchema rule.

    Through 2025-11-25 a tool's outputSchema must describe an object and
    structuredContent must be one. Registry tools whose CLI payload is a
    top-level array are wrapped as {"items": [...]} on the MCP surface only;
    CLI and HTTP schemas stay truthful arrays.
    """
    schema = item["output_schema"]
    if not wraps_array_output(item):
        return schema
    return {"type": "object", "properties": {"items": schema},
            "required": ["items"], "additionalProperties": False}


def _manifest() -> dict[str, dict[str, Any]]:
    return {item["name"]: item for item in cli.tool_manifest()["tools"]}


def tool_definitions(version: str = PROTOCOL_VERSION) -> list[dict[str, Any]]:
    """Tool list shaped for the negotiated protocol version (lifecycle: both
    parties MUST respect the negotiated version)."""
    tools = []
    for item in cli.tool_manifest()["tools"]:
        tool: dict[str, Any] = {"name": item["name"], "description": item["description"],
                                "inputSchema": item["input_schema"]}
        if version >= "2025-03-26":
            tool["annotations"] = tool_annotations(item)
        if version >= "2025-06-18":
            tool["title"] = tool_title(item["name"])
            tool["outputSchema"] = mcp_output_schema(item)
            tool["_meta"] = {"tplinkctl": {key: item[key] for key in (
                "risk", "profiles", "plan_operation", "rollback_contract", "local_only", "output_schema")}}
        tools.append(tool)
    return tools


# --- Tool execution ------------------------------------------------------------

class ProtocolError(Exception):
    """A JSON-RPC protocol error (unknown tool, malformed request)."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


class ToolInputError(ValueError):
    """Arguments failed validation; safe, actionable text for the model."""


_STOK = re.compile(r";stok=[^/\s'\"]*")
_INPUT_VALIDATORS: dict[str, Any] = {}
MAX_WATCH_SECONDS = 120.0


def _redact(text: str) -> str:
    return _STOK.sub(";stok=<redacted>", text)


def _log(message: str) -> None:
    # stdio servers MAY log to stderr, but clients capture it into their own
    # logs; always redact router session tokens.
    print(f"tplinkctl-mcp: {_redact(message)}", file=sys.stderr, flush=True)


def _log_failure(name: str, exc: BaseException) -> None:
    # Exception text can carry router URLs, diagnostics, or secrets that
    # pattern redaction cannot recognize, so it is only logged on explicit
    # operator opt-in (TPLINK_MCP_DEBUG=1); the type name is always safe.
    detail = f": {exc}" if os.getenv("TPLINK_MCP_DEBUG") == "1" else ""
    _log(f"tool {name} failed: {type(exc).__name__}{detail}")


def validate_arguments(item: dict[str, Any], arguments: dict[str, Any]) -> None:
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import best_match

    name = item["name"]
    validator = _INPUT_VALIDATORS.get(name)
    if validator is None:
        validator = _INPUT_VALIDATORS[name] = Draft202012Validator(item["input_schema"])
    error = best_match(validator.iter_errors(arguments))
    if error is not None:
        where = "/".join(str(part) for part in error.absolute_path) or "arguments"
        message = f"Invalid arguments for {name} ({where}): {error.message}"
        if not item["read_only"] and "confirm" in error.message:
            message += ". Mutations require confirm=true after the user approves the plan."
        raise ToolInputError(message)
    if name == "watch":
        count = arguments.get("count", 1)
        interval = arguments.get("interval", 0) or 0
        if (count - 1) * interval > MAX_WATCH_SECONDS:
            raise ToolInputError(
                f"Invalid arguments for watch: (count - 1) * interval must be <= {MAX_WATCH_SECONDS:g}s "
                "so a single call cannot block the server.")


def _error_result(kind: str, message: str, **extra: Any) -> dict[str, Any]:
    payload = {"error": {"kind": kind, "message": message, **extra}}
    return {"content": [{"type": "text", "text": json.dumps(payload)}], "isError": True}


class CommandFailed(Exception):
    """A CLI command aborted with a free-form SystemExit message."""


def run_cli_json(argv: list[str]) -> str:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            cli.main(argv)
        except cli.CliError:
            raise
        except SystemExit as exc:
            if isinstance(exc.code, int) or exc.code is None:
                # argparse usage errors: an exit status plus an "error:" line
                # about the client's own arguments.
                detail = stderr.getvalue().strip()
                raise ToolInputError(detail.splitlines()[-1] if detail else "Invalid arguments.") from exc
            # Free-form runtime failures can interpolate upstream exception text
            # (router URLs, session tokens), so they never cross the boundary.
            raise CommandFailed(str(exc.code)) from exc
    return stdout.getvalue().strip()


def call_tool(name: str, arguments: dict[str, Any] | None = None,
              version: str = PROTOCOL_VERSION) -> dict[str, Any]:
    """Execute one tool. Raises ProtocolError for unknown tools; every other
    failure becomes a sanitized Tool Execution Error result."""
    arguments = {} if arguments is None else arguments
    item = _manifest().get(name)
    builder = TOOL_BUILDERS.get(name)
    if item is None or builder is None:
        raise ProtocolError(-32602, f"Unknown tool: {name}")
    try:
        validate_arguments(item, arguments)
        argv = builder(arguments)
    except ValueError as exc:  # ToolInputError and builder validation messages
        return _error_result("usage", str(exc))
    try:
        output = run_cli_json(argv)
    except cli.CliError as exc:
        # Machine-readable kind without upstream exception text, which may
        # contain secrets or router diagnostics.
        entry = cli.ERROR_CATALOG[exc.kind]
        return _error_result(exc.kind, entry["description"], retryable=entry["retryable"])
    except ToolInputError as exc:
        return _error_result("usage", str(exc))
    except CommandFailed as exc:
        # Same contract as the HTTP transport's SystemExit mapping.
        _log_failure(name, exc)
        return _error_result("router", "Command could not complete; inspect router state before retrying",
                             retryable=False)
    except Exception as exc:  # noqa: BLE001 - sanitize everything else
        import requests

        _log_failure(name, exc)
        if isinstance(exc, requests.RequestException):
            return _error_result("router", "Router unreachable or the request failed.", retryable=True)
        return _error_result("internal", cli.ERROR_CATALOG["internal"]["description"], retryable=False)

    if version < "2025-06-18":
        return {"content": [{"type": "text", "text": output or "null"}], "isError": False}
    try:
        payload = json.loads(output)
    except (json.JSONDecodeError, TypeError):
        _log(f"tool {name} produced non-JSON output")
        return _error_result("internal", cli.ERROR_CATALOG["internal"]["description"], retryable=False)
    if wraps_array_output(item):
        structured: Any = {"items": payload}
        text = json.dumps(structured, indent=2, sort_keys=True)
    else:
        structured, text = payload, output
    if not isinstance(structured, dict):
        # Declared object schema but non-object payload: a server bug. Fail
        # loudly instead of emitting structured content that violates it.
        _log(f"tool {name} payload type {type(payload).__name__} violates its output schema")
        return _error_result("internal", cli.ERROR_CATALOG["internal"]["description"], retryable=False)
    # Tools SHOULD return the serialized structured content as a text block.
    return {"content": [{"type": "text", "text": text}], "structuredContent": structured, "isError": False}


# --- Rate limiting (security best practice: servers rate-limit invocations) ---
EXPENSIVE_TOOLS = {"doctor_deep", "watch"}
_RATE_WINDOW_SECONDS = 60.0


def _env_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, "") or default))
    except ValueError:
        return default


class RateLimiter:
    """Sliding-window per-tool limiter; limits come from the environment."""

    def __init__(self) -> None:
        self._calls: dict[str, list[float]] = {}

    def reset(self) -> None:
        self._calls.clear()

    def check(self, name: str) -> int | None:
        """Return retry-after seconds if `name` is over budget, else None."""
        limit = _env_int(
            "TPLINK_MCP_EXPENSIVE_RATE_LIMIT_PER_MINUTE"
            if name in EXPENSIVE_TOOLS else "TPLINK_MCP_RATE_LIMIT_PER_MINUTE",
            6 if name in EXPENSIVE_TOOLS else 300,
        )
        if limit <= 0:
            return None
        now = time.monotonic()
        window = [t for t in self._calls.get(name, []) if now - t < _RATE_WINDOW_SECONDS]
        if len(window) >= limit:
            self._calls[name] = window
            return max(1, int(_RATE_WINDOW_SECONDS - (now - window[0])) + 1)
        window.append(now)
        self._calls[name] = window
        return None


_RATE_LIMITER = RateLimiter()


def _reset_rate_limiter() -> None:
    _RATE_LIMITER.reset()


# --- JSON-RPC / lifecycle ------------------------------------------------------

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS = -32700, -32600, -32601, -32602


class Session:
    """Per-connection state for one stdio process.

    `handle_request` without a session behaves as an already-initialized
    session at the latest version (unit tests, in-process callers).
    """

    def __init__(self, *, initialized: bool = False, version: str | None = None) -> None:
        self.initialized = initialized
        self.version = version or PROTOCOL_VERSION


def error_response(request_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def negotiate_protocol_version(params: dict[str, Any]) -> str:
    """Lifecycle: echo a supported requested version; otherwise respond with
    the latest version the server supports (the client decides to disconnect)."""
    requested = params.get("protocolVersion")
    if isinstance(requested, str) and requested in SUPPORTED_PROTOCOL_VERSIONS:
        return requested
    return PROTOCOL_VERSION


def tools_list_result(params: dict[str, Any], version: str = PROTOCOL_VERSION) -> dict[str, Any]:
    tools = tool_definitions(version)
    cursor = params.get("cursor")
    offset = 0
    if cursor is not None:
        try:
            offset = int(str(cursor))
        except ValueError:
            raise ProtocolError(INVALID_PARAMS, "Invalid cursor") from None
        if offset < 0 or offset > len(tools):
            raise ProtocolError(INVALID_PARAMS, "Invalid cursor")
    page_size = _env_int("TPLINK_MCP_PAGE_SIZE", 0)
    if page_size <= 0:
        if offset:
            raise ProtocolError(INVALID_PARAMS, "Invalid cursor")
        return {"tools": tools}
    result: dict[str, Any] = {"tools": tools[offset:offset + page_size]}
    if offset + page_size < len(tools):
        result["nextCursor"] = str(offset + page_size)
    return result


def _valid_id(value: Any) -> bool:
    # MCP: ids MUST be a string or integer and MUST NOT be null.
    return isinstance(value, str) or (isinstance(value, int) and not isinstance(value, bool))


def handle_request(message: Any, session: Session | None = None) -> dict[str, Any] | None:
    session = session or Session(initialized=True)
    if not isinstance(message, dict):
        return error_response(None, INVALID_REQUEST, "Invalid Request")
    has_id = "id" in message
    request_id = message.get("id") if has_id and _valid_id(message.get("id")) else None
    if "method" not in message and ("result" in message or "error" in message):
        return None  # a response to a server request; this server sends none
    if message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
        return None if not has_id else error_response(request_id, INVALID_REQUEST, "Invalid Request")
    if not has_id:
        return None  # notifications MUST NOT be answered, whatever the method
    if not _valid_id(message["id"]):
        return error_response(None, INVALID_REQUEST, "Invalid Request: id must be a string or integer")
    method = message["method"]
    params = message.get("params", {})
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return error_response(request_id, INVALID_PARAMS, "Invalid params: params must be an object")

    if method == "initialize":
        version = negotiate_protocol_version(params)
        session.initialized, session.version = True, version
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": server_info(version),
                "instructions": SERVER_INSTRUCTIONS,
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method not in {"tools/list", "tools/call"}:
        return error_response(request_id, METHOD_NOT_FOUND, f"Method not found: {method}")
    if not session.initialized:
        # Deterministic failure instead of serving era-ambiguous methods without
        # a negotiated version (2026-07-28 stdio backward-compatibility guidance).
        return error_response(request_id, INVALID_REQUEST, "Server not initialized: send initialize first")
    try:
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": request_id,
                    "result": tools_list_result(params, session.version)}
        name = params.get("name")
        arguments = params.get("arguments")
        if not isinstance(name, str) or not name:
            raise ProtocolError(INVALID_PARAMS, "Invalid params: name must be a non-empty string")
        if arguments is not None and not isinstance(arguments, dict):
            raise ProtocolError(INVALID_PARAMS, "Invalid params: arguments must be an object")
        if name not in TOOL_BUILDERS:
            raise ProtocolError(INVALID_PARAMS, f"Unknown tool: {name}")
        retry_after = _RATE_LIMITER.check(name)
        if retry_after is not None:
            result = _error_result("rate_limited", f"Rate limit exceeded for {name}; retry after {retry_after}s.",
                                   retry_after_seconds=retry_after, retryable=True)
        else:
            result = call_tool(name, arguments, session.version)
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    except ProtocolError as exc:
        return error_response(request_id, exc.code, str(exc))


def server_info(version: str = PROTOCOL_VERSION) -> dict[str, Any]:
    info: dict[str, Any] = {"name": SERVER_NAME, "version": __version__}
    if version >= "2025-06-18":
        info["title"] = "TP-Link Router (tplinkctl)"
    if version >= "2025-11-25":
        info["description"] = "Plan-first, profile-gated management of a local TP-Link router."
        info["websiteUrl"] = "https://github.com/JithendraNara/tplinkctl"
    return info


# --- stdio transport ------------------------------------------------------------

_BLANK = object()
_PARSE_ERROR = object()


def read_message(stream: Any) -> Any:
    """Return a decoded message, None at EOF, or a _BLANK/_PARSE_ERROR sentinel."""
    first = stream.readline()
    if not first:
        return None
    if isinstance(first, bytes):
        try:
            first = first.decode("utf-8")
        except UnicodeDecodeError:
            return _PARSE_ERROR
    if first.startswith("Content-Length:"):
        # Backward compatibility with earlier builds' LSP-style framing.
        try:
            length = int(first.split(":", 1)[1].strip())
        except ValueError:
            return _PARSE_ERROR
        while True:
            line = stream.readline()
            if isinstance(line, bytes):
                line = line.decode("utf-8", "replace")
            if line in {"\r\n", "\n", ""}:
                break
        body = stream.read(length)
        if isinstance(body, bytes):
            body = body.decode("utf-8", "replace")
        first = body
    if not first.strip():
        return _BLANK
    try:
        return json.loads(first)
    except json.JSONDecodeError:
        return _PARSE_ERROR


def write_message(stream: Any, message: Any) -> None:
    # MCP stdio: one JSON-RPC message (or 2025-03-26 batch) per line; json.dumps
    # escapes control characters, so no embedded newlines.
    stream.write(json.dumps(message, separators=(",", ":")) + "\n")
    stream.flush()


def dispatch(raw: Any, session: Session) -> Any:
    if raw is _PARSE_ERROR:
        return error_response(None, PARSE_ERROR, "Parse error")
    if isinstance(raw, list):
        # JSON-RPC batching exists only in protocol 2025-03-26 (added there,
        # removed in 2025-06-18), where receiving batches is a MUST.
        if not (session.initialized and session.version == "2025-03-26") or not raw:
            return error_response(None, INVALID_REQUEST, "Invalid Request: batches are not supported")
        if any(isinstance(m, dict) and m.get("method") == "initialize" for m in raw):
            return error_response(None, INVALID_REQUEST, "Invalid Request: initialize must not be batched")
        responses = [r for r in (handle_request(m, session) for m in raw) if r is not None]
        return responses or None
    return handle_request(raw, session)


def _finalize(response: Any, session: Session) -> Any:
    """Shape id-less error responses for the negotiated revision.

    When a request's id cannot be read, JSON-RPC 2.0 uses "id": null, but MCP
    2025-11-25 makes the error id optional and non-null (the official TS SDK
    rejects null). Older MCP schemas require a non-null id and have no valid
    form, so they keep the JSON-RPC 2.0 null.
    """
    if (isinstance(response, dict) and "error" in response and response.get("id") is None
            and session.version >= "2025-11-25"):
        response = {k: v for k, v in response.items() if k != "id"}
    return response


def serve(input_stream: Any = None, output_stream: Any = None) -> None:
    input_stream = input_stream or sys.stdin.buffer
    output_stream = output_stream or sys.stdout
    session = Session()
    while True:
        raw = read_message(input_stream)
        if raw is None:
            return
        if raw is _BLANK:
            continue
        response = _finalize(dispatch(raw, session), session)
        if response is not None:
            write_message(output_stream, response)


def main() -> int:
    # Keep the protocol channel exclusive: move the real stdout to a private
    # descriptor and point fd 1 at stderr, so stray writes from any library
    # (print, C extensions, subprocesses) cannot corrupt the stream.
    protocol_fd = os.dup(sys.stdout.fileno())
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    with open(protocol_fd, "w", encoding="utf-8", newline="\n", closefd=True) as protocol_out:
        serve(sys.stdin.buffer, protocol_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
