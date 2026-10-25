"""Authenticated local HTTP transport using the existing CLI/router boundary.

One process owns ephemeral plans. Router locks cover freshness checks and writes;
HTTP is intentionally serialized because router sessions are exclusive.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import ipaddress
import json
import os
import re
import secrets
import socket
import threading
import time
from urllib.parse import parse_qs, unquote, urlsplit

from jsonschema import Draft202012Validator

from . import cli, mcp, registry


class ApiError(Exception):
    def __init__(self, kind: str, message: str):
        self.kind = kind
        super().__init__(message)


@dataclass(frozen=True)
class Principal:
    actor: str
    profile: str = "read-only"


@dataclass
class Plan:
    actor: str
    profile: str
    operation: str
    arguments: dict
    fingerprint: str
    target: dict
    deadline: float


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def redact_diagnostics(value):
    if isinstance(value, dict):
        return {key: redact_diagnostics(child) for key, child in value.items()}
    if isinstance(value, list):
        return [redact_diagnostics(child) for child in value]
    return "[redacted]"


def safe_payload(value, credentials: tuple[str, ...] = ()):
    """Do not return router exceptions, raw secret fields, or credential fragments."""
    if isinstance(value, dict):
        return {k: ("[redacted]" if cli.SENSITIVE_KEY_RE.search(k) and k != "public_key"
                    else redact_diagnostics(v) if k in {"error", "errors", "message"}
                    else safe_payload(v, credentials)) for k, v in value.items()}
    if isinstance(value, list):
        return [safe_payload(v, credentials) for v in value]
    if isinstance(value, str):
        for secret in credentials:
            if secret:
                value = value.replace(secret, "[redacted]")
    return value


def target_of(raw: dict, operation: str) -> dict:
    target = raw.get("target") or {"resource": "router-led"}
    # Counters, signal, and rate changes must not invalidate device authorization.
    result = {key: value for key, value in target.items()
              if key in {"mac", "ip", "ipaddr", "hostname", "name", "connection", "resource", "form"}}
    policy = (raw.get("current") or {}).get("access_control", {})
    if "blacklist" in policy:
        result["affected_policy"] = {key: policy[key] for key in ("blacklist", "whitelist")}
    return result


def fingerprint(raw: dict, operation: str) -> str:
    value = {"target": target_of(raw, operation), "current": raw.get("current"),
             "changes": raw.get("changes")}
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def plan_details(raw: dict, operation: str, arguments: dict) -> tuple[list, dict]:
    """State-derived rollback guidance, not a promise of transactional recovery."""
    current = raw.get("current") or {}
    target = target_of(raw, operation)
    changes = []
    commands = []
    limitations = ["Manual recovery requires fresh authorization. Router writes are not atomic."]
    supported = True
    if operation == "led_set":
        if arguments["action"] == "schedule":
            previous = current.get("schedule", {})
            desired = {k: arguments.get(k, previous.get(k)) for k in ("enabled", "start", "end")}
            for key in desired:
                changes.append({"field": "schedule." + key, "before": previous.get(key), "after": desired[key]})
            supported = isinstance(previous.get("enabled"), bool) and all(previous.get(k) for k in ("start", "end"))
            if supported:
                commands = [["tplinkctl", "led", "schedule", cli.on_off(previous["enabled"]),
                             "--start", previous["start"], "--end", previous["end"], "--yes"]]
        else:
            changes = [{"field": "enabled", "before": current.get("enabled"), "after": arguments["action"] == "on"}]
            supported = isinstance(current.get("enabled"), bool)
            if supported:
                commands = [["tplinkctl", "led", cli.on_off(current["enabled"]), "--yes"]]
    elif operation == "wifi_config":
        command = ["tplinkctl", "wifi-config", arguments["connection"]]
        for key in ("channel", "width", "txpower", "ssid"):
            if key not in arguments:
                continue
            previous = current.get("htmode" if key == "width" else key)
            changes.append({"field": key, "before": previous, "after": arguments[key]})
            if not isinstance(previous, str) or not previous:
                supported = False
            else:
                command.extend(["--" + key, previous])
        if supported:
            commands = [command + ["--yes"]]
        limitations.append("Radio changes may disconnect this client. Use an independent management connection.")
    elif operation == "device_block":
        already = bool(current.get("already_listed"))
        changes = [{"field": "blacklisted", "before": already, "after": True}]
        if not already:
            commands.append(["tplinkctl", "device", "unblock", target["mac"], "--yes"])
        if arguments.get("enforce"):
            access = current.get("access_control", {})
            changes.extend({"field": "access_control." + key, "before": access.get(key), "after": desired}
                           for key, desired in (("enabled", True), ("mode", "black")))
            # Unblocking cannot restore global policy. Never call it a full rollback.
            supported = False
            limitations.append("Unblock only removes the new list entry; it does not restore global Access Control enablement or mode.")
    else:
        changes = [{"field": "blacklisted", "before": True, "after": False}] if operation == "device_unblock" else []
        supported = False
        limitations.append("No complete inverse is guaranteed for this operation; preserve the prior state separately.")
    return changes, {"supported": supported, "automatic": False, "commands": commands, "limitations": limitations}


class Application:
    def __init__(self, credentials: dict[str, Principal], *, plan_ttl: float = 120, max_plans: int = 256):
        if not credentials or any(len(key) < 32 or not key.isascii() for key in credentials):
            raise ValueError("Each API credential must be at least 32 ASCII characters")
        if any(p.profile not in cli.POLICY_PROFILES or not p.actor for p in credentials.values()):
            raise ValueError("Credentials need a server-configured actor and valid profile")
        if not 0 < plan_ttl <= 600 or not 1 <= max_plans <= 4096:
            raise ValueError("Invalid plan lifetime or capacity")
        self.credentials = dict(credentials)
        self.plan_ttl = plan_ttl
        self.max_plans = max_plans
        self.plans: dict[str, Plan] = {}
        self.lock = threading.RLock()
        self.tools = {item["name"]: item for item in registry.tools()}
        self.config = cli.merged_config()  # immutable target selection for this server lifetime
        self.router_password = os.getenv("TPLINK_PASSWORD")
        self.events = cli.events_path()

    def authenticate(self, authorization: str | None) -> Principal:
        if not authorization or not authorization.startswith("Bearer "):
            raise ApiError("auth", "Bearer authentication required")
        candidate = authorization[7:].encode("utf-8")
        for token, principal in self.credentials.items():
            if hmac.compare_digest(candidate, token.encode("ascii")):
                return principal
        raise ApiError("auth", "Invalid API credential")

    def sanitize(self, value):
        return safe_payload(value, tuple(self.credentials) + (self.router_password or "",))

    def namespace(self, name: str, arguments: dict, principal: Principal):
        argv = mcp.TOOL_BUILDERS[name](arguments)
        if name == "device_show":
            argv = mcp.base_argv() + ["device", "show", arguments["query"]]
        args = cli.build_parser().parse_args(argv)
        args.profile = principal.profile  # ignore ambient MCP profile and never accept caller policy
        args.reason = "[redacted]"
        args._audit_skip = True  # HTTP writes a bounded event, not arbitrary router result strings
        args.password = self.router_password
        for key in ("host", "username", "client", "timeout", "verify_ssl"):
            setattr(args, key, self.config[key])
        cli.ensure_command_allowed(args)
        return args

    def invoke(self, name: str, arguments: dict, principal: Principal, router=None):
        args = self.namespace(name, arguments, principal)
        result = []
        args._output_sink = result.append
        args._router_session = router
        args.func(args)
        if len(result) != 1:
            raise ApiError("internal", "Command did not produce one result")
        return result[0]

    def audit(self, principal: Principal, operation: str, target: dict, event: str, result: str):
        # Neither free-form reasons nor credential/plan identifiers enter the log.
        cli.append_jsonl(self.events, {
            "timestamp": datetime.now(timezone.utc).isoformat(), "event": event,
            "transport": "http", "operation": operation, "profile": principal.profile,
            "actor": principal.actor, "target": self.sanitize(target), "reason": "[redacted]",
            "result": result, "ok": result == "success",
        })

    def normalize(self, item: dict, arguments: dict) -> dict:
        value = deepcopy(arguments)
        schema = registry.http_input(item)
        # Missing confirmation artifacts have a semantic conflict, not a schema error.
        if not item["read_only"]:
            if not value.get("plan_id") or value.get("confirm") is not True:
                raise ApiError("confirmation_required", "A valid plan and explicit confirm=true are required")
        if not Draft202012Validator(schema).is_valid(value):
            raise ApiError("usage", "Arguments do not match the operation schema")
        for key, v in value.items():
            if isinstance(v, str) and key not in {"reason", "plan_id"}:
                if v.startswith("-") or any(ord(c) < 32 for c in v):
                    raise ApiError("usage", "Invalid argument value")
        if item["name"] in {"device_block", "device_plan"}:
            value.setdefault("enforce", False)
            if item["name"] == "device_plan" and value["action"] != "block" and value["enforce"]:
                raise ApiError("usage", "enforce is only valid for block")
        if item["name"] in {"led_plan", "led_set"}:
            if value["action"] == "schedule" and "enabled" not in value:
                raise ApiError("usage", "Schedule changes require enabled")
            if value["action"] != "schedule" and set(value) & {"enabled", "start", "end"}:
                raise ApiError("usage", "Schedule arguments require action=schedule")
        if item["name"] in {"wifi_config", "wifi_config_plan"} and not set(value) & {"channel", "width", "txpower", "ssid"}:
            raise ApiError("usage", "At least one radio setting is required")
        return value

    def plan_operation(self, name: str, arguments: dict) -> tuple[str, dict]:
        args = {k: v for k, v in arguments.items() if k not in {"reason", "confirm", "plan_id"}}
        if name == "device_plan":
            action = args.pop("action")
            if action != "block":
                args.pop("enforce", None)
            return "device_" + action, args
        return {"led_plan": "led_set", "wifi_config_plan": "wifi_config"}[name], args

    def plan_arguments(self, operation: str, arguments: dict) -> dict:
        if operation.startswith("device_"):
            return {**arguments, "action": operation.removeprefix("device_")}
        return dict(arguments)

    def create_plan(self, item: dict, arguments: dict, principal: Principal):
        operation, normalized = self.plan_operation(item["name"], arguments)
        raw = self.invoke(item["name"], arguments, principal)
        target = target_of(raw, operation)
        diff, rollback = plan_details(raw, operation, normalized)
        now = time.monotonic()
        self.plans = {k: v for k, v in self.plans.items() if v.deadline > now}
        if len(self.plans) >= self.max_plans:
            raise ApiError("conflict", "Plan capacity reached; wait for expiry")
        plan_id = secrets.token_urlsafe(32)
        executable = operation in registry.PLAN_OPERATIONS
        if executable:
            self.plans[plan_id] = Plan(principal.actor, principal.profile, operation, normalized,
                                       fingerprint(raw, operation), target, now + self.plan_ttl)
        self.audit(principal, operation, target, "plan", "success")
        return {"plan_id": plan_id, "operation": operation, "profile": principal.profile,
                "expires_at": datetime.fromtimestamp(time.time() + self.plan_ttl, timezone.utc).isoformat(),
                "target": self.sanitize(target), "arguments": self.sanitize(normalized),
                "diff": self.sanitize(diff), "risk": raw["risk"], "rollback": self.sanitize(rollback),
                "requires_confirmation": True, "executable": executable}

    def execute(self, item: dict, arguments: dict, principal: Principal):
        plan_id = arguments["plan_id"]
        plan = self.plans.get(plan_id)
        normalized = {k: v for k, v in arguments.items() if k not in {"confirm", "plan_id", "reason"}}
        if not plan or plan.deadline <= time.monotonic():
            self.plans.pop(plan_id, None)
            raise ApiError("conflict", "Plan is missing, expired, or already consumed")
        if (plan.actor, plan.profile, plan.operation, plan.arguments) != (
                principal.actor, principal.profile, item["name"], normalized):
            raise ApiError("conflict", "Plan does not authorize this request")
        # Consume BEFORE any upstream call. Uncertain outcomes must never be retried with this artifact.
        del self.plans[plan_id]
        name = item["name"]
        plan_name = item["plan_operation"]
        plan_args = self.plan_arguments(name, normalized)
        args = self.namespace(name, {**normalized, "confirm": True}, principal)
        self.audit(principal, name, plan.target, "execute_attempt", "pending")
        try:
            with cli.router_session(args) as router:
                raw = self.invoke(plan_name, plan_args, principal, router)
                if plan.deadline <= time.monotonic() or fingerprint(raw, name) != plan.fingerprint:
                    raise ApiError("conflict", "Plan expired or router state changed; create a fresh plan")
                execute_args = dict(normalized)
                if name.startswith("device_"):
                    execute_args["query"] = plan.target["mac"]  # never re-resolve a mutable hostname
                result = self.invoke(name, {**execute_args, "confirm": True}, principal, router)
            self.audit(principal, name, plan.target, "execute", "success")
            return {"data": self.sanitize(result)}
        except BaseException:
            self.audit(principal, name, plan.target, "execute", "failed_or_unknown")
            raise

    def dispatch(self, method: str, path: str, arguments: dict, principal: Principal):
        with self.lock:
            for item in self.tools.values():
                route = item.get("http")
                if not route or route["method"] != method.lower():
                    continue
                pattern = re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", route["path"])
                match = re.fullmatch(pattern, path)
                if not match:
                    continue
                path_args = {k: unquote(v) for k, v in match.groupdict().items()}
                if set(path_args) & set(arguments):
                    raise ApiError("usage", "Path parameters cannot be repeated")
                if principal.profile not in item["profiles"]:
                    raise ApiError("permission", "Operation blocked by server profile")
                merged = dict(arguments, **path_args)
                if method.lower() == "get":
                    for key, value in list(merged.items()):
                        prop = item["input_schema"]["properties"].get(key, {})
                        if prop.get("type") == "boolean" and value in {"true", "false"}:
                            merged[key] = value == "true"
                        elif prop.get("type") == "integer" and isinstance(value, str) and re.fullmatch(r"[0-9]{1,8}", value):
                            merged[key] = int(value)
                merged = self.normalize(item, merged)
                if item["name"] in registry.PLAN_OPERATIONS.values():
                    result = self.create_plan(item, merged, principal)
                elif not item["read_only"]:
                    result = self.execute(item, merged, principal)
                else:
                    result = {"data": self.sanitize(self.invoke(item["name"], merged, principal))}
                if not Draft202012Validator(registry.http_output(item)).is_valid(result):
                    raise ApiError("router", "Router response did not match the operation schema")
                return result
            raise ApiError("not_found", "Unknown API resource")


def error_result(exc: BaseException) -> tuple[int, dict]:
    if isinstance(exc, ApiError):
        kind, message = exc.kind, str(exc)
    elif isinstance(exc, cli.CliError):
        kind = exc.kind
        message = cli.ERROR_CATALOG[kind]["description"]
    elif isinstance(exc, SystemExit):
        kind, message = "router", "Command could not complete; inspect router state before retrying"
    else:
        kind, message = "router", "Upstream operation failed; outcome may be unknown"
    return registry.ERROR_STATUS[kind], {"error": {"kind": kind, "message": message}}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


class Handler(BaseHTTPRequestHandler):
    server_version = "tplinkctl-api"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *args):
        pass  # URLs, headers, and exception messages can contain secrets.

    def handle_api(self):
        try:
            app = self.server.application
            if len(self.headers.get_all("Authorization", [])) != 1:
                raise ApiError("auth", "One Bearer credential is required")
            principal = app.authenticate(self.headers.get("Authorization"))
            if self.headers.get("Origin"):
                raise ApiError("permission", "Browser-origin requests are not supported")
            if self.headers.get("Transfer-Encoding"):
                raise ApiError("usage", "Transfer-Encoding is not supported")
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) > 1:
                raise ApiError("usage", "Duplicate Content-Length")
            try:
                length = int(lengths[0]) if lengths else 0
            except ValueError:
                raise ApiError("usage", "Invalid Content-Length") from None
            if not 0 <= length <= 16384:
                raise ApiError("usage", "Request body limit is 16384 bytes")
            url = urlsplit(self.path)
            if url.scheme or url.netloc or len(self.path) > 4096:
                raise ApiError("usage", "Invalid request target")
            if self.command == "GET":
                if length:
                    raise ApiError("usage", "GET bodies are not supported")
                query = parse_qs(url.query, keep_blank_values=True, max_num_fields=32)
                if any(len(v) != 1 for v in query.values()):
                    raise ApiError("usage", "Repeated query parameter")
                arguments = {k: v[0] for k, v in query.items()}
            else:
                if url.query:
                    raise ApiError("usage", "Mutation arguments must use a JSON body")
                if self.headers.get_content_type() != "application/json":
                    raise ApiError("usage", "Content-Type must be application/json")
                try:
                    arguments = json.loads(self.rfile.read(length), object_pairs_hook=unique_object,
                                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                except (ValueError, UnicodeError):
                    raise ApiError("usage", "Invalid JSON object") from None
                if not isinstance(arguments, dict):
                    raise ApiError("usage", "Expected a JSON object")
            if url.path == "/v1/openapi.json" and self.command == "GET" and not arguments:
                from .openapi import document
                result = document()
            else:
                result = app.dispatch(self.command, url.path, arguments, principal)
            status = 200
        except (Exception, SystemExit) as exc:
            status, result = error_result(exc)
        body = (canonical(result) + "\n").encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if status == 401:
            self.send_header("WWW-Authenticate", "Bearer")
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = do_PUT = do_DELETE = handle_api


def create_server(application: Application, bind: str = "127.0.0.1", port: int = 8765,
                  *, allow_remote: bool = False) -> HTTPServer:
    try:
        address = ipaddress.ip_address(bind)
    except ValueError:
        raise ValueError("Bind must be an explicit numeric IP address") from None
    if not address.is_loopback and not allow_remote:
        raise ValueError("Non-loopback binding requires --allow-remote behind a trusted TLS proxy or encrypted tunnel")
    server_type = type("ApiServer", (HTTPServer,), {
        "address_family": socket.AF_INET6 if address.version == 6 else socket.AF_INET,
        "application": application,
    })
    return server_type((bind, port), Handler)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Authenticated tplinkctl HTTP API. Default: loopback and read-only.")
    parser.add_argument("--bind", default="127.0.0.1", help="Numeric listen address; default 127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--profile", choices=sorted(cli.POLICY_PROFILES), default="read-only", help="Server policy; callers cannot override it")
    parser.add_argument("--allow-remote", action="store_true", help="Explicitly permit non-loopback bind; require trusted TLS proxy or encrypted tunnel")
    parser.add_argument("--plan-ttl", type=float, default=120, help="Single-use plan lifetime in seconds, at most 600")
    args = parser.parse_args(argv)
    try:
        app = Application({os.environ.get("TPLINK_API_TOKEN", ""): Principal("api-client", args.profile)}, plan_ttl=args.plan_ttl)
        server = create_server(app, args.bind, args.port, allow_remote=args.allow_remote)
    except ValueError as exc:
        parser.error(str(exc) + ". Set TPLINK_API_TOKEN in the server environment; never pass credentials in URLs.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
