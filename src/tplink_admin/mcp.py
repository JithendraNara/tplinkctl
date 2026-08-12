"""Small stdio JSON-RPC tool server for tplinkctl.

This intentionally avoids an MCP SDK dependency. It speaks the core JSON-RPC
methods used by MCP clients (`initialize`, `tools/list`, `tools/call`) and uses
Content-Length framing on stdio.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
from collections.abc import Callable
from typing import Any

from . import __version__
from . import cli


SERVER_NAME = "tplinkctl-mcp"
PROTOCOL_VERSION = "2024-11-05"


def base_argv() -> list[str]:
    argv = ["--json", "--no-input"]
    profile = os.getenv("TPLINK_MCP_PROFILE") or os.getenv(cli.PROFILE_ENV)
    if profile:
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


TOOL_BUILDERS: dict[str, Callable[[dict[str, Any]], list[str]]] = {
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
    "doctor_deep": argv_doctor_deep,
    "watch": argv_watch,
    "audit_tail": argv_audit_tail,
    "state_snapshot": argv_state_snapshot,
    "state_diff": argv_state_diff,
}


def tool_definitions() -> list[dict[str, Any]]:
    tools = []
    for item in cli.tool_manifest()["tools"]:
        tool = {
            "name": item["name"],
            "description": item["description"],
            "inputSchema": item["input_schema"],
        }
        if item["name"] in {"device_block", "device_unblock", "led_set", "wifi_config"}:
            tool["inputSchema"] = dict(tool["inputSchema"])
            properties = dict(tool["inputSchema"].get("properties", {}))
            properties["confirm"] = {"type": "boolean", "description": "Must be true to execute the mutation."}
            tool["inputSchema"]["properties"] = properties
            tool["inputSchema"]["required"] = sorted(set(tool["inputSchema"].get("required", [])) | {"confirm"})
        tools.append(tool)
    tools.append(
        {
            "name": "watch",
            "description": "Sample read-only router state repeatedly.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "enum": ["status", "devices", "speed", "health"]},
                    "count": {"type": "integer", "minimum": 1},
                    "interval": {"type": "number", "minimum": 0},
                    "active": {"type": "boolean"},
                    "top": {"type": "integer", "minimum": 1},
                },
                "additionalProperties": False,
            },
        }
    )
    return tools


def run_cli_json(argv: list[str]) -> str:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            cli.main(argv)
        except SystemExit as exc:
            detail = stderr.getvalue().strip() or str(exc)
            raise RuntimeError(detail) from exc
    return stdout.getvalue().strip()


def call_tool(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    arguments = arguments or {}
    builder = TOOL_BUILDERS.get(name)
    if builder is None:
        raise ValueError(f"Unknown tool `{name}`")
    output = run_cli_json(builder(arguments))
    return {"content": [{"type": "text", "text": output or "null"}], "isError": False}


def error_response(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def handle_request(message: dict[str, Any]) -> dict[str, Any] | None:
    request_id = message.get("id")
    method = message.get("method")
    params = message.get("params") or {}

    if method == "notifications/initialized":
        return None
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": __version__},
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": tool_definitions()}}
    if method == "tools/call":
        try:
            result = call_tool(str(params.get("name", "")), params.get("arguments") or {})
        except Exception as exc:
            result = {"content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}], "isError": True}
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    return error_response(request_id, -32601, f"Method not found: {method}")


def read_message(stream: Any) -> dict[str, Any] | None:
    first = stream.readline()
    if not first:
        return None
    if isinstance(first, bytes):
        first = first.decode("utf-8")
    if first.startswith("Content-Length:"):
        length = int(first.split(":", 1)[1].strip())
        while True:
            line = stream.readline()
            if isinstance(line, bytes):
                line = line.decode("utf-8")
            if line in {"\r\n", "\n", ""}:
                break
        body = stream.read(length)
        if isinstance(body, bytes):
            body = body.decode("utf-8")
        return json.loads(body)
    return json.loads(first)


def write_message(stream: Any, message: dict[str, Any]) -> None:
    body = json.dumps(message, separators=(",", ":"))
    stream.write(f"Content-Length: {len(body.encode('utf-8'))}\r\n\r\n{body}")
    stream.flush()


def serve(input_stream: Any = None, output_stream: Any = None) -> None:
    input_stream = input_stream or sys.stdin.buffer
    output_stream = output_stream or sys.stdout
    while True:
        message = read_message(input_stream)
        if message is None:
            return
        response = handle_request(message)
        if response is not None:
            write_message(output_stream, response)


def main() -> int:
    serve()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
