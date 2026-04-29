"""Command line interface for local TP-Link router administration."""

from __future__ import annotations

import argparse
import dataclasses
import enum
import fcntl
import getpass
from hashlib import sha256
import ipaddress
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from collections.abc import Iterable
from contextlib import contextmanager
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urljoin

from . import __version__

import requests

try:
    from tplinkrouterc6u import (
        Connection,
        TplinkRouterProvider,
        TplinkRouterSG,
        VPN,
    )
except ModuleNotFoundError as exc:
    print(
        "Missing dependency: tplinkrouterc6u. Run `python -m pip install -e .`.",
        file=sys.stderr,
    )
    raise SystemExit(2) from exc


APP_NAME = "tplink-admin"
DEFAULT_HOST = "http://192.168.0.1"
DEFAULT_BUNDLE_DIR = "js"
DEFAULTS = {
    "host": DEFAULT_HOST,
    "username": "admin",
    "client": "sg",
    "timeout": 30,
    "verify_ssl": True,
}
ENV_MAP = {
    "host": "TPLINK_HOST",
    "username": "TPLINK_USERNAME",
    "client": "TPLINK_CLIENT",
    "timeout": "TPLINK_TIMEOUT",
}
COMMAND_ENV = {
    "enable": "TPLINK_ENABLE_COMMANDS",
    "disable": "TPLINK_DISABLE_COMMANDS",
}
WIFI_ENDPOINTS = {
    "main": (
        "admin/wireless?form=wireless_2g&form=wireless_5g&form=wireless_5g_2&form=wireless_6g",
        "operation=read",
    ),
    "guest": (
        "admin/wireless?form=guest_2g&form=guest_5g&form=guest_2g5g",
        "operation=read",
    ),
    "iot": (
        "admin/wireless?form=iot_2g&form=iot_5g&form=iot_5g_2",
        "operation=read_spf",
    ),
    "smart_connect": ("admin/wireless?form=smart_connect", "operation=read"),
}
SENSITIVE_KEY_RE = re.compile(r"(password|passwd|psk|key|secret|token)", re.IGNORECASE)
ACCESS_CONTROL_ENABLE = "admin/access_control?form=enable"
ACCESS_CONTROL_MODE = "admin/access_control?form=mode"
ACCESS_BLACK_LIST = "admin/access_control?form=black_list"
ACCESS_WHITE_LIST = "admin/access_control?form=white_list"
ACCESS_BLACK_DEVICES = "admin/access_control?form=black_devices"
ACCESS_WHITE_DEVICES = "admin/access_control?form=white_devices"
DHCP_RESERVATION = "admin/dhcps?form=reservation"
KNOWN_QUIRKS = [
    {
        "id": "sg-operation-placement",
        "applies_to": ["Archer BE-series", "TplinkRouterSG"],
        "summary": "Some SG/BE endpoints require operation parameters in the URL as well as the encrypted payload.",
    },
    {
        "id": "vpn-user-list-dispatcher-error",
        "applies_to": ["Archer BE3500 firmware 1.1.3 Build 20251120"],
        "summary": "The live router returns a Lua dispatcher error for admin/vpn?form=vpn_user_list on this firmware.",
        "affects": ["device.vpn"],
    },
]
CAPABILITIES = [
    {"id": "router.firmware", "command": "firmware", "type": "read", "requires_auth": True, "output": ["json", "plain"], "status": "supported"},
    {"id": "router.health", "command": "health", "type": "read", "requires_auth": True, "output": ["json", "plain"], "status": "supported"},
    {"id": "router.status", "command": "status", "type": "read", "requires_auth": True, "output": ["json", "plain"], "status": "supported"},
    {"id": "router.snapshot", "command": "snapshot", "type": "read", "requires_auth": True, "output": ["json", "plain"], "status": "supported"},
    {"id": "internet.wan", "command": "wan", "type": "read", "requires_auth": True, "output": ["json", "plain"], "status": "supported"},
    {"id": "internet.speed", "command": "speed", "type": "read", "requires_auth": True, "output": ["json", "plain"], "status": "supported"},
    {"id": "internet.speedtest", "command": "speedtest", "type": "external_network_test", "requires_auth": False, "output": ["json", "plain"], "status": "supported"},
    {"id": "wifi.status", "command": "wifi-status", "type": "read", "requires_auth": True, "output": ["json", "plain"], "status": "supported"},
    {"id": "wifi.info", "command": "wifi-info", "type": "read", "requires_auth": True, "output": ["json", "plain"], "status": "supported"},
    {"id": "wifi.toggle", "command": "wifi <connection> <on|off>", "type": "mutation", "requires_auth": True, "requires_confirmation": False, "risk": "network_outage", "rollback": "Run the opposite wifi command.", "status": "supported"},
    {"id": "device.list", "command": "devices", "type": "read", "requires_auth": True, "output": ["json", "plain"], "status": "supported"},
    {"id": "device.show", "command": "device <query>", "type": "read", "requires_auth": True, "output": ["json", "plain"], "status": "supported"},
    {"id": "device.access", "command": "device access <status|on|off>", "type": "read_or_mutation", "requires_auth": True, "requires_confirmation": "--yes for on/off", "risk": "network_access_policy", "status": "supported"},
    {"id": "device.reserve", "command": "device reserve <query> --yes", "type": "mutation", "requires_auth": True, "requires_confirmation": "--yes", "risk": "dhcp_reservation", "rollback": "device release <query> --yes", "status": "live_verified"},
    {"id": "device.release", "command": "device release <query> --yes", "type": "mutation", "requires_auth": True, "requires_confirmation": "--yes", "risk": "dhcp_reservation", "rollback": "device reserve <query> --yes", "status": "live_verified"},
    {"id": "device.block", "command": "device block <query> --yes [--enforce]", "type": "mutation", "requires_auth": True, "requires_confirmation": "--yes", "risk": "device_connectivity_loss", "rollback": "device unblock <query> --yes", "status": "live_verified"},
    {"id": "device.unblock", "command": "device unblock <query> --yes", "type": "mutation", "requires_auth": True, "requires_confirmation": "--yes", "risk": "device_access_policy", "rollback": "device block <query> --yes", "status": "live_verified"},
    {"id": "device.vpn", "command": "device vpn <query> <on|off> --yes", "type": "mutation", "requires_auth": True, "requires_confirmation": "--yes", "risk": "routing_change", "status": "firmware_error", "note": "Known to fail on the tested Archer BE3500 firmware."},
    {"id": "vpn.status", "command": "vpn-status", "type": "read", "requires_auth": True, "output": ["json", "plain"], "status": "supported"},
    {"id": "vpn.client_status", "command": "vpn-client-status", "type": "read", "requires_auth": True, "output": ["json", "plain"], "status": "supported"},
    {"id": "vpn.client_toggle", "command": "vpn-client <on|off>", "type": "mutation", "requires_auth": True, "risk": "routing_change", "status": "supported"},
    {"id": "router.reboot", "command": "reboot --yes", "type": "mutation", "requires_auth": True, "requires_confirmation": "--yes", "risk": "router_reboot", "status": "supported"},
    {"id": "discovery.routes", "command": "routes", "type": "local_discovery", "requires_auth": False, "output": ["json", "plain"], "status": "supported"},
    {"id": "discovery.endpoints", "command": "endpoints", "type": "local_discovery", "requires_auth": False, "output": ["json", "plain"], "status": "supported"},
    {"id": "advanced.read", "command": "read <path>", "type": "advanced_read", "requires_auth": True, "output": ["json", "plain"], "status": "supported"},
    {"id": "advanced.raw", "command": "raw <path>", "type": "advanced_escape_hatch", "requires_auth": True, "risk": "unknown_endpoint_effects", "status": "supported"},
]


class MetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.meta: dict[str, str] = {}
        self.scripts: list[str] = []
        self.stylesheets: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value for key, value in attrs if value is not None}
        if tag == "meta" and attr.get("name"):
            self.meta[attr["name"]] = attr.get("content", "")
        elif tag == "script" and attr.get("src"):
            self.scripts.append(attr["src"])
        elif tag == "link" and attr.get("rel") == "stylesheet" and attr.get("href"):
            self.stylesheets.append(attr["href"])


def config_dir() -> Path:
    base = os.getenv("XDG_CONFIG_HOME")
    return Path(base).expanduser() / APP_NAME if base else Path.home() / ".config" / APP_NAME


def config_path() -> Path:
    return config_dir() / "config.json"


def lock_path() -> Path:
    return config_dir() / "session.lock"


@contextmanager
def session_lock(enabled: bool):
    if not enabled:
        yield
        return
    path = lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def load_config() -> dict[str, Any]:
    path = config_path()
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid config JSON at {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise SystemExit(f"Invalid config at {path}: expected a JSON object.")
    return loaded


def save_config(config: dict[str, Any]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def merged_config() -> dict[str, Any]:
    config = {**DEFAULTS, **load_config()}
    for key, env_name in ENV_MAP.items():
        if env_name in os.environ:
            config[key] = os.environ[env_name]
    if "TPLINK_VERIFY_SSL" in os.environ:
        config["verify_ssl"] = bool_arg(os.environ["TPLINK_VERIFY_SSL"])
    config["timeout"] = int(config["timeout"])
    return config


def to_plain(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return {field.name: to_plain(getattr(value, field.name)) for field in dataclasses.fields(value)}
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
        return str(value)
    if isinstance(value, dict):
        return {str(key): to_plain(item) for key, item in value.items()}
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, bytearray)):
        return [to_plain(item) for item in value]
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def print_json(value: Any) -> None:
    print(json.dumps(to_plain(value), indent=2, sort_keys=True))


def emit(args: argparse.Namespace, value: Any) -> None:
    output = getattr(args, "output", None) or output_from_env()
    if output == "json":
        print_json(value)
        return
    print_plain(to_plain(value))


def output_from_env() -> str:
    if bool_env("TPLINK_JSON"):
        return "json"
    if bool_env("TPLINK_PLAIN"):
        return "plain"
    return "plain"


def bool_env(name: str) -> bool:
    value = os.getenv(name)
    if value is None:
        return False
    try:
        return bool_arg(value)
    except argparse.ArgumentTypeError:
        return False


def print_plain(value: Any) -> None:
    if isinstance(value, list):
        print_table(value)
    elif isinstance(value, dict):
        for key in sorted(value):
            item = value[key]
            if isinstance(item, (dict, list)):
                print(f"{key}\t{json.dumps(item, sort_keys=True)}")
            else:
                print(f"{key}\t{item}")
    else:
        print(value)


def print_table(rows: list[Any]) -> None:
    if not rows:
        return
    if not all(isinstance(row, dict) for row in rows):
        for row in rows:
            print(row)
        return
    keys = list(dict.fromkeys(key for row in rows for key in row.keys()))
    print("\t".join(keys))
    for row in rows:
        print("\t".join(format_cell(row.get(key, "")) for key in keys))


def format_cell(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    return str(value)


def number_or_zero(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def human_bytes(value: Any) -> str:
    amount = number_or_zero(value)
    units = ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if abs(amount) < 1024 or unit == units[-1]:
            return f"{amount:.1f} {unit}" if unit != "B" else f"{amount:.0f} B"
        amount /= 1024
    return f"{amount:.1f} TB"


def human_rate(value: Any) -> str:
    return f"{human_bytes(value)}/s"


def redact_value(key: str, value: Any) -> Any:
    if SENSITIVE_KEY_RE.search(key):
        if value in (None, ""):
            return value
        return "[redacted]"
    if isinstance(value, dict):
        return {item_key: redact_value(item_key, item_value) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [redact_value(key, item) for item in value]
    return value


def redact_mapping(value: dict[str, Any]) -> dict[str, Any]:
    return {key: redact_value(key, item) for key, item in value.items()}


def normalize_api_path(path: str) -> str:
    return path.lstrip("/")


def safe_call(label: str, func) -> dict[str, Any]:
    try:
        return {"ok": True, "data": to_plain(func())}
    except SystemExit as exc:
        return {"ok": False, "error": f"SystemExit: {exc}"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def operation_path(path: str, operation: str) -> str:
    if "operation=" in path:
        return path
    separator = "&" if "?" in path else "?"
    return f"{path}{separator}operation={operation}"


def api_request(
    router,
    path: str,
    data: str,
    *,
    ignore_response: bool = False,
    ignore_errors: bool = False,
) -> Any:
    if not all(hasattr(router, name) for name in ("_aes_encrypt", "_aes_decrypt", "_build_request_signature")):
        return router.request(path, data, ignore_response=ignore_response, ignore_errors=ignore_errors)

    if isinstance(data, str) and "=" in data:
        parsed = dict(parse_qsl(data))
        for key, value in parsed.items():
            if f"{key}=" not in path:
                path += f"&{key}={quote(str(value))}"
        data = json.dumps(parsed)

    encrypted_data = router._aes_encrypt(data)
    router._hash = sha256(encrypted_data.encode()).hexdigest()
    sign = router._build_request_signature(len(encrypted_data))
    url = f"{router.host}/cgi-bin/luci/;stok={router._stok}/{path}"
    body = f"sign={sign}&data={quote(encrypted_data)}"
    response = requests.post(
        url,
        data=body,
        headers=router._headers_request,
        cookies={"sysauth": router._sysauth},
        timeout=router.timeout,
        verify=router._verify_ssl,
    )
    if ignore_response:
        return None

    try:
        raw = response.json().get("data", "")
    except ValueError:
        raw = response.text
    try:
        decrypted_text = router._aes_decrypt(raw)
        decrypted = json.loads(decrypted_text)
    except Exception as exc:
        detail = decrypted_text.strip() if "decrypted_text" in locals() else str(exc)
        raise SystemExit(f"Router returned an unreadable response for `{path}`: {detail}") from exc

    data_block = getattr(router, "_data_block", "data")
    if isinstance(decrypted, dict) and decrypted.get("success") and data_block in decrypted:
        return decrypted[data_block]
    if ignore_errors:
        return decrypted
    raise SystemExit(f"Router returned an error for `{path}`: {decrypted}")


def is_private_ip(value: str | None) -> bool:
    if not value:
        return False
    try:
        return ipaddress.ip_address(value).is_private
    except ValueError:
        return False


def status_summary(status: dict[str, Any]) -> dict[str, Any]:
    devices = status.get("devices", [])
    active_devices = [device for device in devices if device.get("active")]
    speed = speed_summary(device_rows(status))
    by_type: dict[str, int] = {}
    for device in active_devices:
        by_type[device.get("type", "unknown")] = by_type.get(device.get("type", "unknown"), 0) + 1
    return {
        "wan_ip": status.get("_wan_ipv4_addr"),
        "wan_gateway": status.get("_wan_ipv4_gateway"),
        "lan_ip": status.get("_lan_ipv4_addr"),
        "cpu_usage": status.get("cpu_usage"),
        "mem_usage": status.get("mem_usage"),
        "wan_uptime_seconds": status.get("wan_ipv4_uptime"),
        "clients": {
            "reported_total": status.get("clients_total"),
            "active_seen": len(active_devices),
            "wired": status.get("wired_total"),
            "wifi": status.get("wifi_clients_total"),
            "guest": status.get("guest_clients_total"),
            "iot": status.get("iot_clients_total"),
            "by_type": by_type,
        },
        "wifi": wifi_summary(status),
        "speed": {
            "down_Bps": speed["totals"]["down_Bps"],
            "up_Bps": speed["totals"]["up_Bps"],
            "down_human": speed["totals"]["down_human"],
            "up_human": speed["totals"]["up_human"],
        },
    }


def device_rows(status: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for device in status.get("devices", []):
        hostname = device.get("hostname") or device.get("name") or ""
        down_speed = int(number_or_zero(device.get("down_speed")))
        up_speed = int(number_or_zero(device.get("up_speed")))
        usage = int(number_or_zero(device.get("traffic_usage")))
        signal = device.get("signal")
        rows.append(
            {
                "hostname": hostname,
                "ip": device.get("_ipaddr") or device.get("ipaddr") or device.get("ip") or "",
                "mac": device.get("_macaddr") or device.get("macaddr") or device.get("mac") or "",
                "connection": device.get("type") or "unknown",
                "active": bool(device.get("active")),
                "down_Bps": down_speed,
                "up_Bps": up_speed,
                "down": human_rate(down_speed),
                "up": human_rate(up_speed),
                "usage_bytes": usage,
                "usage": human_bytes(usage),
                "signal_dbm": signal,
                "rx_rate": device.get("rx_rate"),
                "tx_rate": device.get("tx_rate"),
                "online_seconds": device.get("online_time"),
                "packets_received": device.get("packets_received"),
                "packets_sent": device.get("packets_sent"),
            }
        )
    return rows


def filter_device_rows(rows: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    filtered = rows
    if getattr(args, "active", False):
        filtered = [row for row in filtered if row["active"]]
    if getattr(args, "connection", None):
        filtered = [row for row in filtered if row["connection"] == args.connection.value]
    if getattr(args, "name", None):
        needle = args.name.lower()
        filtered = [row for row in filtered if needle in row["hostname"].lower()]
    if getattr(args, "ip", None):
        filtered = [row for row in filtered if args.ip == row["ip"]]
    if getattr(args, "mac", None):
        needle = normalize_mac(args.mac)
        filtered = [row for row in filtered if normalize_mac(row["mac"]) == needle]
    sort_key = getattr(args, "sort", None)
    if sort_key:
        key_map = {
            "name": lambda row: row["hostname"].lower(),
            "ip": lambda row: tuple(int(part) if part.isdigit() else 999 for part in row["ip"].split(".")),
            "speed": lambda row: row["down_Bps"] + row["up_Bps"],
            "usage": lambda row: row["usage_bytes"],
            "signal": lambda row: row["signal_dbm"] if row["signal_dbm"] is not None else -999,
        }
        filtered = sorted(filtered, key=key_map[sort_key], reverse=sort_key in {"speed", "usage", "signal"})
    top = getattr(args, "top", None)
    if top:
        filtered = filtered[:top]
    return filtered


def normalize_mac(value: str) -> str:
    return re.sub(r"[^0-9a-f]", "", value.lower())


def match_device(row: dict[str, Any], query: str) -> bool:
    needle = query.lower()
    mac = normalize_mac(query)
    return (
        needle in row["hostname"].lower()
        or needle == row["ip"].lower()
        or (mac and mac == normalize_mac(row["mac"]))
    )


def find_device(rows: list[dict[str, Any]], query: str) -> dict[str, Any]:
    matches = [row for row in rows if match_device(row, query)]
    if not matches:
        raise SystemExit(f"No device matched `{query}`.")
    exact = [
        row for row in matches
        if query.lower() in {row["hostname"].lower(), row["ip"].lower()}
        or normalize_mac(query) == normalize_mac(row["mac"])
    ]
    if len(exact) == 1:
        return exact[0]
    if len(matches) == 1:
        return matches[0]
    names = ", ".join(f"{row['hostname']} ({row['ip']}, {row['mac']})" for row in matches[:8])
    raise SystemExit(f"Device query `{query}` matched multiple devices: {names}")


def load_device(router, query: str) -> dict[str, Any]:
    rows = device_rows(to_plain(router.get_status()))
    return find_device(rows, query)


def on_off(value: bool) -> str:
    return "on" if value else "off"


def form_payload(**items: Any) -> str:
    return urlencode({key: value for key, value in items.items() if value not in (None, "")})


def compact_json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"))


def insert_payload(new: dict[str, Any], index: int = 0) -> str:
    return urlencode({"operation": "insert", "new": compact_json(new), "index": index})


def require_yes(args: argparse.Namespace, action: str) -> None:
    if not getattr(args, "yes", False):
        raise SystemExit(f"Refusing to {action} without --yes.")


def load_collection(router, path: str) -> list[dict[str, Any]]:
    response = to_plain(api_request(router, operation_path(path, "load"), "operation=load", ignore_errors=True))
    if isinstance(response, dict) and isinstance(response.get("data"), list):
        return response["data"]
    if isinstance(response, dict) and isinstance(response.get("data"), dict) and isinstance(response["data"].get("data"), list):
        return response["data"]["data"]
    if isinstance(response, list):
        return response
    return []


def find_list_item(items: list[dict[str, Any]], query: str) -> tuple[int, dict[str, Any]]:
    needle = query.lower()
    mac = normalize_mac(query)
    for index, item in enumerate(items):
        item_mac = normalize_mac(str(item.get("mac") or item.get("macaddr") or ""))
        values = {
            str(item.get("hostname") or item.get("name") or "").lower(),
            str(item.get("ip") or item.get("ipaddr") or "").lower(),
        }
        if needle in values or (mac and mac == item_mac):
            return index, item
    for index, item in enumerate(items):
        name = str(item.get("hostname") or item.get("name") or "").lower()
        if needle and needle in name:
            return index, item
    raise SystemExit(f"No list entry matched `{query}`.")


def device_access_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": row["hostname"] or row["mac"],
        "mac": row["mac"],
        "ipaddr": row["ip"],
        "deviceType": row["connection"],
        "conn_type": row["connection"],
        "host": "NON_HOST",
        "key": normalize_mac(row["mac"]),
    }


def reservation_payload(row: dict[str, Any], ip: str | None = None, name: str | None = None) -> dict[str, Any]:
    return {
        "hostname": name or row["hostname"] or row["mac"],
        "ip": ip or row["ip"],
        "mac": row["mac"],
        "enable": "on",
    }


def access_control_status(router) -> dict[str, Any]:
    enable = to_plain(api_request(router, operation_path(ACCESS_CONTROL_ENABLE, "read"), "operation=read", ignore_errors=True))
    mode = to_plain(api_request(router, operation_path(ACCESS_CONTROL_MODE, "read"), "operation=read", ignore_errors=True))
    return {
        "enabled": is_on(enable.get("enable") if isinstance(enable, dict) else None),
        "mode": mode.get("access_mode") if isinstance(mode, dict) else None,
        "blacklist": load_collection(router, ACCESS_BLACK_LIST),
        "whitelist": load_collection(router, ACCESS_WHITE_LIST),
    }


def access_device_payload(router, row: dict[str, Any], list_path: str) -> dict[str, Any]:
    candidates = load_collection(router, list_path)
    match = next((item for item in candidates if normalize_mac(str(item.get("mac") or "")) == normalize_mac(row["mac"])), {})
    return {
        "name": match.get("name") or row["hostname"] or row["mac"],
        "deviceType": match.get("deviceType") or match.get("type") or row["connection"],
        "mac": match.get("mac") or row["mac"],
        "ipaddr": match.get("ipaddr") or row["ip"],
        "host": match.get("host") or "NON_HOST",
        "conn_type": match.get("conn_type") or match.get("connType") or row["connection"],
        "key": match.get("key") or normalize_mac(row["mac"]),
    }


def contains_mac(items: list[dict[str, Any]], mac: str) -> bool:
    normalized = normalize_mac(mac)
    return any(normalize_mac(str(item.get("mac") or item.get("macaddr") or "")) == normalized for item in items)


def speed_summary(rows: list[dict[str, Any]], top: int = 5) -> dict[str, Any]:
    active = [row for row in rows if row["active"]]
    total_down = sum(row["down_Bps"] for row in active)
    total_up = sum(row["up_Bps"] for row in active)

    def slim(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "hostname": row["hostname"],
            "ip": row["ip"],
            "connection": row["connection"],
            "down_Bps": row["down_Bps"],
            "up_Bps": row["up_Bps"],
            "down": row["down"],
            "up": row["up"],
            "usage_bytes": row["usage_bytes"],
            "usage": row["usage"],
        }

    return {
        "totals": {
            "down_Bps": total_down,
            "up_Bps": total_up,
            "down_human": human_rate(total_down),
            "up_human": human_rate(total_up),
            "active_devices": len(active),
        },
        "top_download": [slim(row) for row in sorted(active, key=lambda row: row["down_Bps"], reverse=True)[:top]],
        "top_upload": [slim(row) for row in sorted(active, key=lambda row: row["up_Bps"], reverse=True)[:top]],
        "top_usage": [slim(row) for row in sorted(active, key=lambda row: row["usage_bytes"], reverse=True)[:top]],
    }


def wifi_summary(status: dict[str, Any]) -> dict[str, Any]:
    return {
        "host_2g": status.get("wifi_2g_enable"),
        "host_5g": status.get("wifi_5g_enable"),
        "host_6g": status.get("wifi_6g_enable"),
        "guest_2g": status.get("guest_2g_enable"),
        "guest_5g": status.get("guest_5g_enable"),
        "guest_6g": status.get("guest_6g_enable"),
        "iot_2g": status.get("iot_2g_enable"),
        "iot_5g": status.get("iot_5g_enable"),
        "iot_6g": status.get("iot_6g_enable"),
    }


def is_on(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return None
    lowered = str(value).lower()
    if lowered in {"on", "true", "1", "yes", "enabled"}:
        return True
    if lowered in {"off", "false", "0", "no", "disabled"}:
        return False
    return None


def wifi_network_rows(raw: dict[str, Any]) -> list[dict[str, Any]]:
    prefixes = sorted(
        {
            key.removesuffix("_ssid")
            for key in raw
            if key.endswith("_ssid") and raw.get(key) not in (None, "")
        }
    )
    rows: list[dict[str, Any]] = []
    for prefix in prefixes:
        rows.append(
            {
                "network": prefix.replace("wireless_", "main_"),
                "ssid": raw.get(f"{prefix}_ssid"),
                "enabled": is_on(raw.get(f"{prefix}_enable")),
                "hidden": is_on(raw.get(f"{prefix}_hidden")),
                "channel": raw.get(f"{prefix}_current_channel") or raw.get(f"{prefix}_channel"),
                "configured_channel": raw.get(f"{prefix}_channel"),
                "width": raw.get(f"{prefix}_htmode"),
                "txpower": raw.get(f"{prefix}_txpower"),
                "security": raw.get(f"{prefix}_encryption"),
                "mac": raw.get(f"{prefix}_macaddr"),
            }
        )
    return rows


def read_wifi_info(router) -> dict[str, Any]:
    raw_sections: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}
    for name, (path, payload) in WIFI_ENDPOINTS.items():
        try:
            data = router.request(path, payload, ignore_errors=True)
            raw_sections[name] = to_plain(data) if isinstance(data, dict) else {}
        except Exception as exc:
            errors[name] = f"{type(exc).__name__}: {exc}"
    networks: list[dict[str, Any]] = []
    for section in ("main", "guest", "iot"):
        for row in wifi_network_rows(raw_sections.get(section, {})):
            row["group"] = section
            networks.append(row)
    return {
        "smart_connect": is_on(raw_sections.get("smart_connect", {}).get("smart_enable")),
        "networks": networks,
        "errors": errors,
    }


def capability_manifest() -> dict[str, Any]:
    return {
        "name": "tplinkctl",
        "version": __version__,
        "default_host": DEFAULT_HOST,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "agent_contract": {
            "prefer": ["--json", "--no-input"],
            "password": "Set TPLINK_PASSWORD in the agent runtime; do not pass secrets in shell history.",
            "safety": [
                "Mutating device commands require --yes.",
                "Use --enable-commands or --disable-commands to constrain autonomous agents.",
                "Authenticated sessions are serialized by default with a local lock.",
            ],
        },
        "capabilities": CAPABILITIES,
        "known_quirks": KNOWN_QUIRKS,
    }


def probe_result(probe_id: str, capability: str, result: dict[str, Any], required: bool = True) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": probe_id,
        "capability": capability,
        "required": required,
        "ok": result["ok"],
    }
    if result["ok"]:
        data = result.get("data")
        if isinstance(data, dict):
            row["keys"] = sorted(str(key) for key in data.keys())[:20]
        elif isinstance(data, list):
            row["count"] = len(data)
        else:
            row["summary"] = data
    else:
        row["error"] = result["error"]
    return row


def deep_doctor_payload(args: argparse.Namespace, web_result: dict[str, Any]) -> dict[str, Any]:
    def action(router):
        firmware_probe = safe_call("firmware", router.get_firmware)
        status_probe = safe_call("status", router.get_status)
        ipv4_probe = safe_call("ipv4", router.get_ipv4_status)
        probes = [
            probe_result("auth.firmware", "router.firmware", firmware_probe),
            probe_result("router.status", "router.status", status_probe),
            probe_result("internet.ipv4", "internet.wan", ipv4_probe),
            probe_result("dhcp.leases", "device.list", safe_call("leases", router.get_ipv4_dhcp_leases)),
            probe_result("dhcp.reservations", "device.reserve", safe_call("reservations", lambda: load_collection(router, DHCP_RESERVATION)), required=False),
            probe_result("wifi.info", "wifi.info", safe_call("wifi_info", lambda: read_wifi_info(router)), required=False),
            probe_result("device.access", "device.access", safe_call("access_control", lambda: access_control_status(router)), required=False),
            probe_result("vpn.status", "vpn.status", safe_call("vpn_status", router.get_vpn_status), required=False),
            probe_result("vpn.client_status", "vpn.client_status", safe_call("vpn_client_status", router.get_vpn_client_status), required=False),
            probe_result("vpn.user_list", "device.vpn", safe_call("vpn_user_list", lambda: load_collection(router, "admin/vpn?form=vpn_user_list")), required=False),
        ]
        firmware = firmware_probe.get("data") if firmware_probe["ok"] else {}
        status = status_probe.get("data") if status_probe["ok"] else {}
        ipv4 = ipv4_probe.get("data") if ipv4_probe["ok"] else {}
        required_ok = all(probe["ok"] for probe in probes if probe["required"])
        payload = {
            **web_result,
            "ok": web_result["ok"] and required_ok,
            "deep": True,
            "router": {
                "model": firmware.get("model") if isinstance(firmware, dict) else None,
                "hardware_version": firmware.get("hardware_version") if isinstance(firmware, dict) else None,
                "firmware_version": firmware.get("firmware_version") if isinstance(firmware, dict) else None,
            },
            "probes": probes,
            "capability_summary": {
                "total": len(CAPABILITIES),
                "live_verified": len([cap for cap in CAPABILITIES if cap.get("status") == "live_verified"]),
                "firmware_error": [cap["id"] for cap in CAPABILITIES if cap.get("status") == "firmware_error"],
            },
            "known_quirks": KNOWN_QUIRKS,
        }
        if isinstance(status, dict) and isinstance(firmware, dict) and isinstance(ipv4, dict):
            payload["health"] = health_from(status, firmware, ipv4)
        return payload

    return with_session(args, action)


def health_from(status: dict[str, Any], firmware: dict[str, Any], ipv4: dict[str, Any]) -> dict[str, Any]:
    warnings: list[str] = []
    cpu_usage = status.get("cpu_usage")
    mem_usage = status.get("mem_usage")
    wan_ip = status.get("_wan_ipv4_addr") or ipv4.get("_wan_ipv4_ipaddr")
    if isinstance(cpu_usage, (int, float)) and cpu_usage >= 0.8:
        warnings.append(f"High CPU usage: {cpu_usage:.0%}")
    if isinstance(mem_usage, (int, float)) and mem_usage >= 0.8:
        warnings.append(f"High memory usage: {mem_usage:.0%}")
    if is_private_ip(wan_ip):
        warnings.append(f"WAN IP {wan_ip} is private; router appears to be behind another NAT.")
    if not status.get("wifi_2g_enable") and not status.get("wifi_5g_enable") and not status.get("wifi_6g_enable"):
        warnings.append("Main Wi-Fi networks appear disabled.")
    return {
        "ok": not warnings,
        "model": firmware.get("model"),
        "hardware_version": firmware.get("hardware_version"),
        "firmware_version": firmware.get("firmware_version"),
        "summary": status_summary(status),
        "warnings": warnings,
    }


def wan_summary(status: dict[str, Any], ipv4: dict[str, Any]) -> dict[str, Any]:
    wan_ip = status.get("_wan_ipv4_addr") or ipv4.get("_wan_ipv4_ipaddr")
    return {
        "wan_ip": wan_ip,
        "wan_gateway": status.get("_wan_ipv4_gateway") or ipv4.get("_wan_ipv4_gateway"),
        "wan_mac": status.get("_wan_macaddr") or ipv4.get("_wan_macaddr"),
        "wan_uptime_seconds": status.get("wan_ipv4_uptime"),
        "connection_type": status.get("conn_type") or ipv4.get("_wan_ipv4_conntype"),
        "netmask": ipv4.get("_wan_ipv4_netmask"),
        "primary_dns": ipv4.get("_wan_ipv4_pridns"),
        "secondary_dns": ipv4.get("_wan_ipv4_snddns"),
        "double_nat_likely": is_private_ip(wan_ip),
    }


def bundle_dir_from_args(args: argparse.Namespace) -> Path:
    return Path(args.bundle_dir or os.getenv("TPLINK_BUNDLE_DIR", DEFAULT_BUNDLE_DIR)).expanduser()


def js_files(bundle_dir: Path) -> list[Path]:
    if not bundle_dir.exists():
        return []
    return sorted(bundle_dir.glob("*.js"))


def discover_endpoints(bundle_dir: Path) -> list[dict[str, Any]]:
    endpoint_re = re.compile(r"""["'`]((?:/admin|/accessibility)[^"'`\\\s]+?\?form=[^"'`\\\s]+)["'`]""")
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for path in js_files(bundle_dir):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in endpoint_re.finditer(text):
            endpoint = match.group(1)
            window = text[max(0, match.start() - 80):match.end() + 120]
            operations = []
            for operation in ("read", "write", "request", "file"):
                if f".{operation}(" in window or f"{operation}(" in window:
                    operations.append(operation)
            key = (endpoint, path.name)
            existing = found.setdefault(key, {"endpoint": endpoint, "file": path.name, "operations": []})
            existing["operations"] = sorted(set(existing["operations"]) | set(operations or ["unknown"]))
    return sorted(found.values(), key=lambda item: (item["endpoint"], item["file"]))


def discover_routes(bundle_dir: Path) -> list[dict[str, str]]:
    route_file = bundle_dir / "index-ESh8tgBq.js"
    if not route_file.exists():
        return []
    text = route_file.read_text(encoding="utf-8", errors="replace")
    route_re = re.compile(r"""\{name:"(?P<name>[^"]+)",path:"(?P<path>[^"]*)",component:\(\)=>o\(\(\)=>import\("\./(?P<bundle>[^"]+)""")
    return [
        match.groupdict()
        for match in route_re.finditer(text)
    ]


def bool_arg(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "on", "true", "yes", "enable", "enabled"}:
        return True
    if normalized in {"0", "off", "false", "no", "disable", "disabled"}:
        return False
    raise argparse.ArgumentTypeError("expected one of: on/off, true/false, yes/no")


def connection_arg(value: str) -> Connection:
    normalized = value.strip().lower().replace("-", "_")
    for connection in Connection:
        if normalized in {connection.name.lower(), connection.value.lower()}:
            if connection is Connection.UNKNOWN:
                break
            return connection
    choices = ", ".join(item.value for item in Connection if item is not Connection.UNKNOWN)
    raise argparse.ArgumentTypeError(f"unknown connection `{value}`; choose one of: {choices}")


def vpn_arg(value: str) -> VPN:
    normalized = value.strip().lower().replace("-", "_")
    for vpn in VPN:
        if normalized in {vpn.name.lower(), vpn.value.lower()}:
            return vpn
    choices = ", ".join(item.value for item in VPN)
    raise argparse.ArgumentTypeError(f"unknown vpn `{value}`; choose one of: {choices}")


def password_from_args(args: argparse.Namespace) -> str:
    password = args.password or os.getenv("TPLINK_PASSWORD")
    if password:
        return password
    if getattr(args, "no_input", False):
        raise SystemExit("Password required. Set TPLINK_PASSWORD or pass --password.")
    return getpass.getpass("TP-Link local admin password: ")


def apply_runtime_defaults(args: argparse.Namespace) -> argparse.Namespace:
    config = merged_config()
    for key in ("host", "username", "client", "timeout", "verify_ssl"):
        if getattr(args, key, None) is None:
            setattr(args, key, config[key])
    return args


def build_router(args: argparse.Namespace):
    password = password_from_args(args)
    if args.client == "sg":
        return TplinkRouterSG(args.host, password, args.username, verify_ssl=args.verify_ssl, timeout=args.timeout)
    return TplinkRouterProvider.get_client(
        args.host,
        password,
        args.username,
        verify_ssl=args.verify_ssl,
        timeout=args.timeout,
    )


def with_session(args: argparse.Namespace, action):
    args = apply_runtime_defaults(args)
    with session_lock(not args.no_lock):
        router = build_router(args)
        router.authorize()
        try:
            return action(router)
        finally:
            router.logout()


def cmd_firmware(args: argparse.Namespace) -> None:
    emit(args, with_session(args, lambda router: router.get_firmware()))


def cmd_status(args: argparse.Namespace) -> None:
    def action(router):
        firmware = to_plain(router.get_firmware())
        status = to_plain(router.get_status())
        ipv4 = to_plain(router.get_ipv4_status())
        wifi = read_wifi_info(router)
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "model": firmware.get("model"),
            "hardware_version": firmware.get("hardware_version"),
            "firmware_version": firmware.get("firmware_version"),
            "router": status_summary(status),
            "wan": wan_summary(status, ipv4),
            "wifi": wifi,
            "devices": device_rows(status),
            "health": health_from(status, firmware, ipv4),
        }

    emit(args, with_session(args, action))


def cmd_health(args: argparse.Namespace) -> None:
    def action(router):
        firmware = to_plain(router.get_firmware())
        status = to_plain(router.get_status())
        ipv4 = to_plain(router.get_ipv4_status())
        return health_from(status, firmware, ipv4)

    emit(args, with_session(args, action))


def cmd_wan(args: argparse.Namespace) -> None:
    def action(router):
        status = to_plain(router.get_status())
        ipv4 = to_plain(router.get_ipv4_status())
        return wan_summary(status, ipv4)

    emit(args, with_session(args, action))


def cmd_wifi_status(args: argparse.Namespace) -> None:
    emit(args, with_session(args, lambda router: wifi_summary(to_plain(router.get_status()))))


def cmd_ipv4(args: argparse.Namespace) -> None:
    emit(args, with_session(args, lambda router: router.get_ipv4_status()))


def cmd_leases(args: argparse.Namespace) -> None:
    emit(args, with_session(args, lambda router: router.get_ipv4_dhcp_leases()))


def cmd_reservations(args: argparse.Namespace) -> None:
    emit(args, with_session(args, lambda router: router.get_ipv4_reservations()))


def cmd_devices(args: argparse.Namespace) -> None:
    def action(router):
        status = to_plain(router.get_status())
        return filter_device_rows(device_rows(status), args)

    emit(args, with_session(args, action))


def cmd_device(args: argparse.Namespace) -> None:
    def action(router):
        rows = device_rows(to_plain(router.get_status()))
        return find_device(rows, args.query)

    emit(args, with_session(args, action))


def cmd_device_access(args: argparse.Namespace) -> None:
    def action(router):
        if args.access_state == "status":
            return access_control_status(router)
        require_yes(args, f"turn access control {args.access_state}")
        expected = args.access_state == "on"
        api_request(
            router,
            operation_path(ACCESS_CONTROL_ENABLE, "write"),
            form_payload(operation="write", enable=on_off(expected)),
            ignore_response=True,
        )
        if args.mode:
            api_request(
                router,
                operation_path(ACCESS_CONTROL_MODE, "write"),
                form_payload(operation="write", access_mode=args.mode),
                ignore_response=True,
            )
        status = access_control_status(router)
        if status["enabled"] is not expected:
            raise SystemExit(f"Router did not confirm access control {args.access_state}; current status is {status}.")
        if args.mode and status["mode"] != args.mode:
            raise SystemExit(f"Router did not confirm access-control mode `{args.mode}`; current status is {status}.")
        return status

    emit(args, with_session(args, action))


def cmd_device_reserve(args: argparse.Namespace) -> None:
    require_yes(args, "create a DHCP reservation")

    def action(router):
        row = load_device(router, args.query)
        existing = load_collection(router, DHCP_RESERVATION)
        normalized = normalize_mac(row["mac"])
        duplicate = next((item for item in existing if normalize_mac(str(item.get("mac") or "")) == normalized), None)
        if duplicate:
            return {"created": False, "reason": "reservation already exists", "reservation": duplicate, "device": row}
        payload = reservation_payload(row, ip=args.ip, name=args.name)
        response = api_request(
            router,
            DHCP_RESERVATION,
            insert_payload(payload),
            ignore_errors=True,
        )
        if isinstance(response, dict) and response.get("success") is False and response.get("errorcode") == "imb duplication":
            refreshed = load_collection(router, DHCP_RESERVATION)
            dup = next((item for item in refreshed if normalize_mac(str(item.get("mac") or "")) == normalized), None)
            if dup:
                return {"created": False, "reason": "reservation already exists", "reservation": dup, "device": row}
        refreshed = load_collection(router, DHCP_RESERVATION)
        if not contains_mac(refreshed, row["mac"]):
            raise SystemExit("Router did not confirm the DHCP reservation; no reservation was left behind.")
        return {"created": True, "reservation": payload, "device": row}

    emit(args, with_session(args, action))


def cmd_device_release(args: argparse.Namespace) -> None:
    require_yes(args, "remove a DHCP reservation")

    def action(router):
        reservations = load_collection(router, DHCP_RESERVATION)
        index, item = find_list_item(reservations, args.query)
        api_request(
            router,
            DHCP_RESERVATION,
            form_payload(operation="remove", index=index, key=item.get("key") or item.get("mac")),
            ignore_errors=True,
        )
        refreshed = load_collection(router, DHCP_RESERVATION)
        if contains_mac(refreshed, str(item.get("mac") or "")):
            raise SystemExit("Router did not confirm reservation removal.")
        return {"removed": True, "reservation": item}

    emit(args, with_session(args, action))


def cmd_device_block(args: argparse.Namespace) -> None:
    require_yes(args, "add a device to the access-control blacklist")

    def action(router):
        row = load_device(router, args.query)
        payload = access_device_payload(router, row, ACCESS_BLACK_DEVICES)
        existing = load_collection(router, ACCESS_BLACK_LIST)
        duplicate = next((item for item in existing if normalize_mac(str(item.get("mac") or "")) == normalize_mac(row["mac"])), None)
        if not duplicate:
            api_request(
                router,
                ACCESS_BLACK_LIST,
                insert_payload(payload),
                ignore_errors=True,
            )
        if args.enforce:
            api_request(router, operation_path(ACCESS_CONTROL_ENABLE, "write"), form_payload(operation="write", enable="on"), ignore_response=True)
            api_request(router, operation_path(ACCESS_CONTROL_MODE, "write"), form_payload(operation="write", access_mode="black"), ignore_response=True)
        status = access_control_status(router)
        refreshed_duplicate = contains_mac(status["blacklist"], row["mac"])
        if not duplicate and not refreshed_duplicate:
            raise SystemExit("Router did not confirm adding the device to the blacklist.")
        return {
            "blocked": True,
            "already_listed": duplicate is not None,
            "enforced": bool(args.enforce),
            "device": row,
            "access_control": {
                "enabled": status["enabled"],
                "mode": status["mode"],
                "blacklist_count": len(status["blacklist"]),
            },
        }

    emit(args, with_session(args, action))


def cmd_device_unblock(args: argparse.Namespace) -> None:
    require_yes(args, "remove a device from the access-control blacklist")

    def action(router):
        blacklist = load_collection(router, ACCESS_BLACK_LIST)
        index, item = find_list_item(blacklist, args.query)
        api_request(
            router,
            ACCESS_BLACK_LIST,
            form_payload(operation="remove", index=index, key=item.get("key") or item.get(".name") or item.get("mac")),
            ignore_errors=True,
        )
        refreshed = load_collection(router, ACCESS_BLACK_LIST)
        if contains_mac(refreshed, str(item.get("mac") or "")):
            raise SystemExit("Router did not confirm removing the device from the blacklist.")
        return {"unblocked": True, "device": item}

    emit(args, with_session(args, action))


def cmd_device_vpn(args: argparse.Namespace) -> None:
    require_yes(args, f"turn VPN client routing {on_off(args.enabled)} for a device")

    def action(router):
        row = load_device(router, args.query)
        devices = load_collection(router, "admin/vpn?form=vpn_user_list")
        target = next((item for item in devices if normalize_mac(str(item.get("mac") or "")) == normalize_mac(row["mac"])), None)
        if target is None:
            raise SystemExit(f"Device `{row['hostname']}` was not found in the VPN client device list.")
        old = dict(target)
        new = dict(target)
        new["access"] = on_off(args.enabled)
        api_request(
            router,
            operation_path("admin/vpn?form=vpn_user_list", "update"),
            urlencode({"operation": "update", "key": target["mac"], "new": json.dumps(new), "old": json.dumps(old)}),
            ignore_response=True,
        )
        refreshed = load_collection(router, "admin/vpn?form=vpn_user_list")
        updated = next((item for item in refreshed if normalize_mac(str(item.get("mac") or "")) == normalize_mac(row["mac"])), {})
        if is_on(updated.get("access")) is not args.enabled:
            raise SystemExit("Router did not confirm the VPN client device change.")
        return {"device": row, "vpn_client": args.enabled}

    emit(args, with_session(args, action))


def cmd_device_dispatch(args: argparse.Namespace) -> None:
    if not args.device_args:
        raise SystemExit("Usage: tplinkctl device QUERY or tplinkctl device <access|reserve|release|block|unblock|vpn> ...")
    commands = {
        "show": build_device_show_parser,
        "access": build_device_access_parser,
        "reserve": build_device_reserve_parser,
        "release": build_device_release_parser,
        "block": build_device_block_parser,
        "unblock": build_device_unblock_parser,
        "vpn": build_device_vpn_parser,
    }
    access_subcommands = {"status", "on", "off"}
    if len(args.device_args) >= 2 and args.device_args[0] in commands:
        # e.g. "device reserve debian" -> device_args=['reserve', 'debian', '--yes']
        action = args.device_args[0]
        subparser = commands[action]()
        subvalues = vars(args).copy()
        subvalues.pop("func", None)
        subargs = argparse.Namespace(**subvalues)
        # For access subcommand: args are [action, access_state, ...] - no query
        # For other subcommands: args are [action, query, ...]
        if action == "access":
            subparser.parse_args(args.device_args[1:], namespace=subargs)
        else:
            query = args.device_args[1] if len(args.device_args) > 1 else ""
            subargs.query = query
            # query is positional, so include it at the front of the args
            subparser.parse_args([query] + args.device_args[2:], namespace=subargs)
        subargs.func(subargs)
    elif len(args.device_args) >= 2 and args.device_args[1] in commands:
        # e.g. "device debian show" -> device_args=['debian', 'show']
        action = args.device_args[1]
        subparser = commands[action]()
        subvalues = vars(args).copy()
        subvalues.pop("func", None)
        subargs = argparse.Namespace(**subvalues)
        if action == "access":
            # e.g. "device debian access status" -> access_state='status', no query
            if args.device_args[0] in access_subcommands:
                # "device access status" - access_state is in position 0
                subargs.query = ""
                subparser.parse_args(args.device_args[1:], namespace=subargs)
            else:
                # "device debian access status" - access_state is in position 2
                subargs.query = args.device_args[0]
                subparser.parse_args(args.device_args[2:], namespace=subargs)
        else:
            query = args.device_args[0]
            subargs.query = query
            subparser.parse_args([query] + args.device_args[2:], namespace=subargs)
        subargs.func(subargs)
    else:
        args.query = " ".join(args.device_args)
        cmd_device(args)


def cmd_speed(args: argparse.Namespace) -> None:
    def action(router):
        rows = device_rows(to_plain(router.get_status()))
        return speed_summary(rows, top=args.top)

    emit(args, with_session(args, action))


def timed_request(session: requests.Session, method: str, url: str, **kwargs: Any) -> tuple[requests.Response, float]:
    started = time.perf_counter()
    response = session.request(method, url, **kwargs)
    elapsed = time.perf_counter() - started
    response.raise_for_status()
    return response, elapsed


def cmd_speedtest(args: argparse.Namespace) -> None:
    args = apply_runtime_defaults(args)
    session = requests.Session()
    result: dict[str, Any] = {
        "provider": "Cloudflare speed test endpoints",
        "download_bytes": args.download_bytes,
        "upload_bytes": 0 if args.skip_upload else args.upload_bytes,
    }
    latency_url = "https://speed.cloudflare.com/cdn-cgi/trace"
    _, latency_seconds = timed_request(session, "GET", latency_url, timeout=args.timeout)
    result["latency_ms"] = round(latency_seconds * 1000, 2)

    download_url = f"https://speed.cloudflare.com/__down?bytes={args.download_bytes}"
    response, elapsed = timed_request(session, "GET", download_url, timeout=args.timeout, stream=True)
    downloaded = 0
    for chunk in response.iter_content(chunk_size=1024 * 256):
        downloaded += len(chunk)
    down_bps = downloaded / elapsed if elapsed else 0
    result["download"] = {
        "bytes": downloaded,
        "seconds": round(elapsed, 3),
        "Bps": round(down_bps, 2),
        "Mbps": round(down_bps * 8 / 1_000_000, 2),
    }

    if not args.skip_upload:
        upload_url = "https://speed.cloudflare.com/__up"
        payload = os.urandom(args.upload_bytes)
        _, elapsed = timed_request(session, "POST", upload_url, data=payload, timeout=args.timeout)
        up_bps = args.upload_bytes / elapsed if elapsed else 0
        result["upload"] = {
            "bytes": args.upload_bytes,
            "seconds": round(elapsed, 3),
            "Bps": round(up_bps, 2),
            "Mbps": round(up_bps * 8 / 1_000_000, 2),
        }

    emit(args, result)


def cmd_wifi_info(args: argparse.Namespace) -> None:
    def action(router):
        info = read_wifi_info(router)
        if args.group:
            info["networks"] = [row for row in info["networks"] if row["group"] == args.group]
        return info

    emit(args, with_session(args, action))


def cmd_clients(args: argparse.Namespace) -> None:
    def action(router):
        status = to_plain(router.get_status())
        return filter_device_rows(device_rows(status), args)

    emit(args, with_session(args, action))


def cmd_wifi(args: argparse.Namespace) -> None:
    def action(router):
        router.set_wifi(args.connection, args.enabled)
        return {"connection": args.connection.value, "enabled": args.enabled}

    emit(args, with_session(args, action))


def cmd_vpn_status(args: argparse.Namespace) -> None:
    emit(args, with_session(args, lambda router: router.get_vpn_status()))


def cmd_vpn(args: argparse.Namespace) -> None:
    def action(router):
        router.set_vpn(args.vpn, args.enabled)
        return {"vpn": args.vpn.value, "enabled": args.enabled}

    emit(args, with_session(args, action))


def cmd_vpn_client_status(args: argparse.Namespace) -> None:
    emit(args, with_session(args, lambda router: router.get_vpn_client_status()))


def cmd_vpn_client(args: argparse.Namespace) -> None:
    def action(router):
        router.set_vpn_client(args.enabled)
        return {"vpn_client": args.enabled}

    emit(args, with_session(args, action))


def cmd_reboot(args: argparse.Namespace) -> None:
    if not args.yes and not args.force:
        raise SystemExit("Refusing to reboot without --yes.")
    emit(args, with_session(args, lambda router: router.reboot() or {"reboot": "requested"}))


def cmd_raw(args: argparse.Namespace) -> None:
    payload = args.data
    if args.data_file:
        payload = Path(args.data_file).read_text(encoding="utf-8")

    def action(router):
        return router.request(
            normalize_api_path(args.path),
            payload,
            ignore_response=args.ignore_response,
            ignore_errors=args.ignore_errors,
        )

    emit(args, with_session(args, action))


def cmd_read(args: argparse.Namespace) -> None:
    def action(router):
        return router.request(
            normalize_api_path(args.path),
            "operation=read",
            ignore_errors=args.ignore_errors,
        )

    emit(args, with_session(args, action))


def cmd_snapshot(args: argparse.Namespace) -> None:
    def action(router):
        snapshot = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "firmware": safe_call("firmware", router.get_firmware),
            "status": safe_call("status", router.get_status),
            "ipv4": safe_call("ipv4", router.get_ipv4_status),
            "leases": safe_call("leases", router.get_ipv4_dhcp_leases),
            "reservations": safe_call("reservations", router.get_ipv4_reservations),
            "vpn_status": safe_call("vpn_status", router.get_vpn_status),
            "vpn_client_status": safe_call("vpn_client_status", router.get_vpn_client_status),
        }
        firmware = snapshot["firmware"].get("data") if snapshot["firmware"]["ok"] else {}
        status = snapshot["status"].get("data") if snapshot["status"]["ok"] else {}
        ipv4 = snapshot["ipv4"].get("data") if snapshot["ipv4"]["ok"] else {}
        snapshot["health"] = health_from(status, firmware, ipv4) if status and firmware else {"ok": False, "warnings": ["Incomplete snapshot."]}
        return snapshot

    emit(args, with_session(args, action))


def cmd_capabilities(args: argparse.Namespace) -> None:
    emit(args, capability_manifest())


def web_doctor_payload(args: argparse.Namespace) -> dict[str, Any]:
    args = apply_runtime_defaults(args)
    url = urljoin(args.host.rstrip("/") + "/", "webpages/index.html")
    try:
        response = requests.get(url, timeout=args.timeout, verify=args.verify_ssl)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise SystemExit(f"Router web UI check failed: {exc}") from exc
    parser = MetaParser()
    parser.feed(response.text)
    return {
        "ok": True,
        "deep": False,
        "url": url,
        "status_code": response.status_code,
        "meta": parser.meta,
        "scripts": parser.scripts,
        "stylesheets": parser.stylesheets,
    }


def cmd_doctor(args: argparse.Namespace) -> None:
    web_result = web_doctor_payload(args)
    if getattr(args, "deep", False):
        emit(args, deep_doctor_payload(args, web_result))
        return
    emit(
        args,
        web_result,
    )


def cmd_endpoints(args: argparse.Namespace) -> None:
    endpoints = discover_endpoints(bundle_dir_from_args(args))
    if args.form:
        endpoints = [endpoint for endpoint in endpoints if args.form in endpoint["endpoint"]]
    emit(args, endpoints)


def cmd_routes(args: argparse.Namespace) -> None:
    routes = discover_routes(bundle_dir_from_args(args))
    if args.name:
        routes = [route for route in routes if args.name.lower() in route["name"].lower()]
    emit(args, routes)


def cmd_config_path(_: argparse.Namespace) -> None:
    print(config_path())


def cmd_config_show(_: argparse.Namespace) -> None:
    config = merged_config()
    config["config_path"] = str(config_path())
    config["password"] = "set via TPLINK_PASSWORD" if os.getenv("TPLINK_PASSWORD") else "not stored"
    emit(_, config)


def cmd_config_set(args: argparse.Namespace) -> None:
    config = load_config()
    updates = {
        "host": args.host,
        "username": args.username,
        "client": args.client,
        "timeout": args.timeout,
        "verify_ssl": args.verify_ssl,
    }
    for key, value in updates.items():
        if value is not None:
            config[key] = value
    save_config(config)
    emit(args, {"saved": str(config_path()), "config": config})


def parse_csv(value: str | None) -> set[str]:
    if not value:
        return set()
    return {item.strip() for item in value.split(",") if item.strip()}


def ensure_command_allowed(args: argparse.Namespace) -> None:
    command = getattr(args, "command", "")
    enabled = parse_csv(args.enable_commands) or parse_csv(os.getenv(COMMAND_ENV["enable"]))
    disabled = parse_csv(args.disable_commands) or parse_csv(os.getenv(COMMAND_ENV["disable"]))
    if enabled and command not in enabled:
        raise SystemExit(f"Command `{command}` blocked by allowlist: {', '.join(sorted(enabled))}")
    if command in disabled:
        raise SystemExit(f"Command `{command}` blocked by denylist.")


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default=None, help=f"router URL (default: {DEFAULT_HOST})")
    parser.add_argument("--username", default=None, help="local admin username")
    parser.add_argument("--password", default=None, help="local admin password; otherwise prompts or reads TPLINK_PASSWORD")
    parser.add_argument("--timeout", type=int, default=None, help="HTTP timeout in seconds")
    parser.add_argument("--client", choices=["auto", "sg"], default=None, help="client type; sg is useful for BE-series routers")
    parser.add_argument("--verify-ssl", action="store_true", default=None, help="enable HTTPS certificate verification")
    parser.add_argument("--no-verify-ssl", action="store_false", dest="verify_ssl", help="disable HTTPS certificate verification")
    parser.add_argument("--json", action="store_const", const="json", dest="output", default=None, help="print JSON to stdout")
    parser.add_argument("--plain", action="store_const", const="plain", dest="output", help="print stable TSV/key-value text to stdout")
    parser.add_argument("--no-input", action="store_true", help="never prompt; fail if required input is missing")
    parser.add_argument("--no-lock", action="store_true", help="do not serialize authenticated router sessions")
    parser.add_argument("--enable-commands", help="comma-separated allowlist for agent use, e.g. status,leases")
    parser.add_argument("--disable-commands", help="comma-separated denylist for agent use, e.g. reboot,wifi")


def add_simple_commands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    commands = {
        "firmware": (cmd_firmware, "show firmware and model info"),
        "health": (cmd_health, "summarize router health and likely issues"),
        "status": (cmd_status, "show router, WAN, Wi-Fi, speed, and device status"),
        "snapshot": (cmd_snapshot, "collect a broad read-only router snapshot"),
        "wan": (cmd_wan, "show WAN summary"),
        "wifi-status": (cmd_wifi_status, "show Wi-Fi network enablement"),
        "ipv4": (cmd_ipv4, "show WAN/LAN IPv4 status"),
        "leases": (cmd_leases, "list DHCP leases"),
        "reservations": (cmd_reservations, "list IPv4 DHCP reservations"),
        "vpn-status": (cmd_vpn_status, "show VPN server status"),
        "vpn-client-status": (cmd_vpn_client_status, "show VPN client status"),
    }
    for name, (func, help_text) in commands.items():
        subparser = subparsers.add_parser(name, help=help_text)
        subparser.set_defaults(func=func)


def add_device_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--active", action="store_true", help="show only active devices")
    parser.add_argument("--connection", type=connection_arg, help="filter by connection, e.g. host_5g")
    parser.add_argument("--name", help="filter by hostname substring")
    parser.add_argument("--ip", help="filter by IP address")
    parser.add_argument("--mac", help="filter by MAC address")
    parser.add_argument("--sort", choices=["name", "ip", "speed", "usage", "signal"], default="name")
    parser.add_argument("--top", type=int, help="limit rows after filtering and sorting")


def device_action_parser(prog: str, description: str) -> argparse.ArgumentParser:
    return argparse.ArgumentParser(prog=prog, description=description)


def build_device_show_parser() -> argparse.ArgumentParser:
    parser = device_action_parser("tplinkctl device show", "Show one device by hostname, IP, or MAC.")
    parser.add_argument("query", help="hostname substring, IP address, or MAC address")
    parser.set_defaults(func=cmd_device)
    return parser


def build_device_access_parser() -> argparse.ArgumentParser:
    parser = device_action_parser("tplinkctl device access", "Show or change access-control enforcement.")
    parser.add_argument("access_state", choices=["status", "on", "off"], help="status, on, or off")
    parser.add_argument("--mode", choices=["black", "white"], help="set blacklist or whitelist mode when turning access control on/off")
    parser.add_argument("--yes", action="store_true", help="confirm access-control change")
    parser.set_defaults(func=cmd_device_access)
    return parser


def build_device_reserve_parser() -> argparse.ArgumentParser:
    parser = device_action_parser("tplinkctl device reserve", "Reserve a device's DHCP address.")
    parser.add_argument("query", help="device hostname substring, IP address, or MAC address")
    parser.add_argument("--ip", help="reserved IP address; defaults to the device's current IP")
    parser.add_argument("--name", help="reservation hostname; defaults to the current device name")
    parser.add_argument("--yes", action="store_true", help="confirm reservation creation")
    parser.set_defaults(func=cmd_device_reserve)
    return parser


def build_device_release_parser() -> argparse.ArgumentParser:
    parser = device_action_parser("tplinkctl device release", "Remove a DHCP reservation.")
    parser.add_argument("query", help="reservation hostname, IP address, or MAC address")
    parser.add_argument("--yes", action="store_true", help="confirm reservation removal")
    parser.set_defaults(func=cmd_device_release)
    return parser


def build_device_block_parser() -> argparse.ArgumentParser:
    parser = device_action_parser("tplinkctl device block", "Add a device to the access-control blacklist.")
    parser.add_argument("query", help="device hostname substring, IP address, or MAC address")
    parser.add_argument("--enforce", action="store_true", help="also enable Access Control and set blacklist mode")
    parser.add_argument("--yes", action="store_true", help="confirm blacklist change")
    parser.set_defaults(func=cmd_device_block)
    return parser


def build_device_unblock_parser() -> argparse.ArgumentParser:
    parser = device_action_parser("tplinkctl device unblock", "Remove a device from the access-control blacklist.")
    parser.add_argument("query", help="blacklist hostname, IP address, or MAC address")
    parser.add_argument("--yes", action="store_true", help="confirm blacklist removal")
    parser.set_defaults(func=cmd_device_unblock)
    return parser


def build_device_vpn_parser() -> argparse.ArgumentParser:
    parser = device_action_parser("tplinkctl device vpn", "Include or exclude a device from VPN client routing.")
    parser.add_argument("query", help="device hostname substring, IP address, or MAC address")
    parser.add_argument("enabled", type=bool_arg, help="on/off")
    parser.add_argument("--yes", action="store_true", help="confirm VPN client device change")
    parser.set_defaults(func=cmd_device_vpn)
    return parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tplinkctl",
        description="Manage a TP-Link router admin page from the terminal.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    add_common(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)
    add_simple_commands(subparsers)

    capabilities = subparsers.add_parser("capabilities", help="print the agent-readable command and safety manifest")
    capabilities.set_defaults(func=cmd_capabilities)

    doctor = subparsers.add_parser("doctor", help="check router web UI reachability and optional authenticated probes")
    doctor.add_argument("--deep", action="store_true", help="run read-only authenticated capability probes")
    doctor.set_defaults(func=cmd_doctor)

    wifi = subparsers.add_parser("wifi", help="enable or disable a Wi-Fi network")
    wifi.add_argument("connection", type=connection_arg, help="for example: host_2g, host_5g, host_6g, guest_2g, iot_2g")
    wifi.add_argument("enabled", type=bool_arg, help="on/off")
    wifi.set_defaults(func=cmd_wifi)

    wifi_info = subparsers.add_parser("wifi-info", help="list Wi-Fi SSIDs, bands, channels, and enabled state")
    wifi_info.add_argument("--group", choices=["main", "guest", "iot"], help="filter network group")
    wifi_info.set_defaults(func=cmd_wifi_info)

    devices = subparsers.add_parser("devices", help="list connected devices with IP, speed, signal, and usage")
    add_device_filters(devices)
    devices.set_defaults(func=cmd_devices)

    device = subparsers.add_parser("device", help="show or manage one device")
    device.add_argument(
        "device_args",
        nargs=argparse.REMAINDER,
        help="QUERY or one of: show, access, reserve, release, block, unblock, vpn",
    )
    device.set_defaults(func=cmd_device_dispatch)

    speed = subparsers.add_parser("speed", help="show current router throughput and top devices")
    speed.add_argument("--top", type=int, default=5, help="number of top devices to show")
    speed.set_defaults(func=cmd_speed)

    speedtest = subparsers.add_parser("speedtest", help="run a small external internet speed test")
    speedtest.add_argument("--download-bytes", type=int, default=10_000_000, help="download test size")
    speedtest.add_argument("--upload-bytes", type=int, default=2_000_000, help="upload test size")
    speedtest.add_argument("--skip-upload", action="store_true", help="only test latency and download")
    speedtest.set_defaults(func=cmd_speedtest)

    clients = subparsers.add_parser("clients", help="alias of devices; list connected clients from status")
    add_device_filters(clients)
    clients.set_defaults(func=cmd_clients)

    vpn = subparsers.add_parser("vpn", help="enable or disable a VPN server")
    vpn.add_argument("vpn", type=vpn_arg, help="for example: OPENVPN, PPTPVPN, IPSEC")
    vpn.add_argument("enabled", type=bool_arg, help="on/off")
    vpn.set_defaults(func=cmd_vpn)

    vpn_client = subparsers.add_parser("vpn-client", help="enable or disable the VPN client")
    vpn_client.add_argument("enabled", type=bool_arg, help="on/off")
    vpn_client.set_defaults(func=cmd_vpn_client)

    reboot = subparsers.add_parser("reboot", help="reboot the router")
    reboot.add_argument("--yes", action="store_true", help="confirm reboot")
    reboot.add_argument("--force", action="store_true", help="alias for --yes")
    reboot.set_defaults(func=cmd_reboot)

    raw = subparsers.add_parser("raw", help="advanced: call the underlying router request API")
    raw.add_argument("path", help="router API path, for example /admin/network?form=wan_ipv4")
    raw.add_argument("--data", default="", help="request payload string")
    raw.add_argument("--data-file", help="read request payload from a file")
    raw.add_argument("--ignore-response", action="store_true")
    raw.add_argument("--ignore-errors", action="store_true")
    raw.set_defaults(func=cmd_raw)

    read = subparsers.add_parser("read", help="advanced: read an endpoint with operation=read")
    read.add_argument("path", help="router API path, for example /admin/network?form=wan_ipv4_status")
    read.add_argument("--ignore-errors", action="store_true")
    read.set_defaults(func=cmd_read)

    endpoints = subparsers.add_parser("endpoints", help="discover API endpoints from downloaded router JS bundles")
    endpoints.add_argument("--bundle-dir", default=None, help=f"directory with router JS bundles (default: {DEFAULT_BUNDLE_DIR})")
    endpoints.add_argument("--form", help="filter endpoint path/form text")
    endpoints.set_defaults(func=cmd_endpoints)

    routes = subparsers.add_parser("routes", help="discover UI routes from downloaded router JS bundles")
    routes.add_argument("--bundle-dir", default=None, help=f"directory with router JS bundles (default: {DEFAULT_BUNDLE_DIR})")
    routes.add_argument("--name", help="filter route name")
    routes.set_defaults(func=cmd_routes)

    config = subparsers.add_parser("config", help="manage saved CLI defaults")
    config_subparsers = config.add_subparsers(dest="config_command", required=True)
    config_path_parser = config_subparsers.add_parser("path", help="print config file path")
    config_path_parser.set_defaults(func=cmd_config_path)
    config_show = config_subparsers.add_parser("show", help="show effective config")
    config_show.set_defaults(func=cmd_config_show)
    config_set = config_subparsers.add_parser("set", help="save non-secret defaults")
    config_set.add_argument("--host")
    config_set.add_argument("--username")
    config_set.add_argument("--client", choices=["auto", "sg"])
    config_set.add_argument("--timeout", type=int)
    config_set.add_argument("--verify-ssl", action="store_true", default=None)
    config_set.add_argument("--no-verify-ssl", action="store_false", dest="verify_ssl")
    config_set.set_defaults(func=cmd_config_set)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    ensure_command_allowed(args)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
