#!/usr/bin/env python3
"""Check whether tplinkctl is ready for local AI agents."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "bin" / "python"
VENV_BIN = ROOT / ".venv" / "bin"


def run(cmd: list[str], *, env: dict[str, str] | None = None, timeout: int = 30) -> dict[str, Any]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    try:
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            env=merged_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "cmd": cmd}
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
        "cmd": cmd,
    }


def parse_json_check(name: str, result: dict[str, Any]) -> dict[str, Any]:
    check = {"name": name, "ok": result["ok"], "cmd": result.get("cmd")}
    if not result["ok"]:
        check["error"] = result.get("stderr") or result.get("error") or result.get("stdout")
        return check
    try:
        check["data"] = json.loads(result["stdout"] or "{}")
    except json.JSONDecodeError as exc:
        check["ok"] = False
        check["error"] = f"Invalid JSON: {exc}"
    return check


def content_length_message(message: dict[str, Any]) -> bytes:
    payload = json.dumps(message).encode("utf-8")
    return b"Content-Length: " + str(len(payload)).encode("ascii") + b"\r\n\r\n" + payload


def mcp_handshake(env: dict[str, str]) -> dict[str, Any]:
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    cmd = [str(PYTHON), "-m", "tplink_admin.mcp"]
    merged = os.environ.copy()
    merged.update(env)
    merged["PYTHONPATH"] = str(ROOT / "src")
    try:
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            env=merged,
            input=content_length_message(request),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=90,
        )
    except Exception as exc:
        return {"name": "mcp_tools_list", "ok": False, "error": f"{type(exc).__name__}: {exc}", "cmd": cmd}
    output = proc.stdout.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        return {"name": "mcp_tools_list", "ok": False, "error": proc.stderr.decode("utf-8", errors="replace"), "cmd": cmd}
    try:
        body = output.split("\r\n\r\n", 1)[1]
        data = json.loads(body)
        tools = data["result"]["tools"]
    except Exception as exc:
        return {"name": "mcp_tools_list", "ok": False, "error": f"Invalid MCP response: {exc}", "cmd": cmd}
    return {"name": "mcp_tools_list", "ok": True, "tool_count": len(tools), "tools": sorted(tool["name"] for tool in tools)}


def source_cli_cmd(*args: str) -> list[str]:
    return [str(PYTHON), "-m", "tplink_admin.cli", *args]


def config_base(env: dict[str, str]) -> Path:
    base = env.get("XDG_CONFIG_HOME") or os.environ.get("XDG_CONFIG_HOME")
    return (Path(base).expanduser() if base else Path.home() / ".config") / "tplink-admin"


def writable_config_parent(path: Path) -> dict[str, Any]:
    parent = path.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
        probe = parent / ".tplinkctl-agent-doctor"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except Exception as exc:
        return {"name": "config_dir_parent", "ok": False, "path": str(parent), "error": f"{type(exc).__name__}: {exc}"}
    return {"name": "config_dir_parent", "ok": True, "path": str(parent)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check tplinkctl agent readiness.")
    parser.add_argument("--live", action="store_true", help="include read-only live router checks")
    parser.add_argument("--device", help="device query for live demo plan checks")
    parser.add_argument("--profile", default=os.getenv("TPLINK_MCP_PROFILE") or os.getenv("TPLINK_PROFILE") or "device-admin")
    parser.add_argument("--json", action="store_true", default=True, help="print JSON")
    args = parser.parse_args(argv)

    env = {"PYTHONPATH": str(ROOT / "src"), "TPLINK_MCP_PROFILE": args.profile}
    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ok": True,
        "root": str(ROOT),
        "profile": args.profile,
        "live": args.live,
        "checks": [],
        "warnings": [],
    }

    checks = report["checks"]
    tplinkctl_path = VENV_BIN / "tplinkctl"
    mcp_path = VENV_BIN / "tplinkctl-mcp"
    checks.append({"name": "python", "ok": PYTHON.exists(), "path": str(PYTHON)})
    checks.append({"name": "tplinkctl_entrypoint", "ok": tplinkctl_path.exists() or shutil.which("tplinkctl") is not None, "path": str(tplinkctl_path) if tplinkctl_path.exists() else shutil.which("tplinkctl")})
    checks.append({"name": "tplinkctl_mcp_entrypoint", "ok": mcp_path.exists() or shutil.which("tplinkctl-mcp") is not None, "path": str(mcp_path) if mcp_path.exists() else shutil.which("tplinkctl-mcp")})

    capabilities = parse_json_check("capabilities", run(source_cli_cmd("--json", "capabilities"), env=env, timeout=90))
    checks.append({key: value for key, value in capabilities.items() if key != "data"})
    if capabilities.get("data"):
        ids = {item["id"] for item in capabilities["data"].get("capabilities", [])}
        checks.append({"name": "agent_capabilities", "ok": {"agent.demo", "agent.tools", "agent.state", "agent.events"} <= ids})

    tools = parse_json_check("tools", run(source_cli_cmd("--json", "tools"), env=env, timeout=90))
    checks.append({key: value for key, value in tools.items() if key != "data"})
    if tools.get("data"):
        tool_names = {item["name"] for item in tools["data"].get("tools", [])}
        checks.append({"name": "agent_tools", "ok": {"device_plan", "audit_tail", "state_snapshot", "state_diff"} <= tool_names})

    demo = parse_json_check("demo", run(source_cli_cmd("--json", "demo"), env=env, timeout=90))
    checks.append({key: value for key, value in demo.items() if key != "data"})
    checks.append(mcp_handshake(env))

    base = config_base(env)
    checks.append(writable_config_parent(base))
    checks.append({"name": "password_env", "ok": bool(os.getenv("TPLINK_PASSWORD")) or not args.live, "present": bool(os.getenv("TPLINK_PASSWORD")), "required": bool(args.live)})
    if not os.getenv("TPLINK_PASSWORD"):
        report["warnings"].append("TPLINK_PASSWORD is not set; live authenticated checks will fail.")

    if args.live:
        live_args = ["--json", "--no-input", "doctor", "--deep"]
        live = parse_json_check("live_doctor_deep", run(source_cli_cmd(*live_args), env=env, timeout=45))
        checks.append({key: value for key, value in live.items() if key != "data"})
        if args.device:
            plan = parse_json_check(
                "live_device_plan",
                run(source_cli_cmd("--json", "--no-input", "demo", "--live", "--device", args.device), env=env, timeout=45),
            )
            checks.append({key: value for key, value in plan.items() if key != "data"})

    report["ok"] = all(check.get("ok") for check in checks)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
