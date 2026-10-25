"""Canonical transport contracts. Runtime routing and discovery consume these entries."""
from __future__ import annotations

from copy import deepcopy
from typing import Any
from tplinkrouterc6u import Connection

def tools() -> list[dict[str, Any]]:
    tools = [
        {
            "name": "router_status",
            "description": "Return router, WAN, Wi-Fi, health, and connected device summary.",
            "command": ["tplinkctl", "--json", "--no-input", "status"],
            "read_only": True,
            "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "firmware_audit",
            "description": "Check current firmware, update availability, and auto-update settings without installing anything.",
            "command": ["tplinkctl", "--json", "--no-input", "firmware-check"],
            "read_only": True,
            "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "led_status",
            "description": "Return router LED and nightly LED-off schedule status.",
            "command": ["tplinkctl", "--json", "--no-input", "led", "status"],
            "read_only": True,
            "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "led_plan",
            "description": "Plan a router LED or nightly schedule change without changing router state.",
            "command": ["tplinkctl", "--json", "--no-input", "led", "<action>", "--plan"],
            "read_only": True,
            "input_schema": {
                "type": "object",
                "required": ["action"],
                "properties": {
                    "action": {"type": "string", "enum": ["on", "off", "schedule"]},
                    "enabled": {"type": "boolean"},
                    "start": {"type": "string", "pattern": "^(?:[01]\\d|2[0-3]):[0-5]\\d$"},
                    "end": {"type": "string", "pattern": "^(?:[01]\\d|2[0-3]):[0-5]\\d$"},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "led_set",
            "description": "Change router LEDs or the nightly LED-off schedule. Requires explicit confirmation and should be preceded by led_plan.",
            "command": ["tplinkctl", "--json", "--no-input", "led", "<action>", "--yes"],
            "read_only": False,
            "risk": "physical_indicator_change",
            "input_schema": {
                "type": "object",
                "required": ["action"],
                "properties": {
                    "action": {"type": "string", "enum": ["on", "off", "schedule"]},
                    "enabled": {"type": "boolean"},
                    "start": {"type": "string", "pattern": "^(?:[01]\\d|2[0-3]):[0-5]\\d$"},
                    "end": {"type": "string", "pattern": "^(?:[01]\\d|2[0-3]):[0-5]\\d$"},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "device_list",
            "description": "List connected devices with hostname, IP, MAC, speed, usage, and connection type.",
            "command": ["tplinkctl", "--json", "--no-input", "devices"],
            "read_only": True,
            "input_schema": {
                "type": "object",
                "properties": {
                    "active": {"type": "boolean"},
                    "sort": {"type": "string", "enum": ["name", "ip", "speed", "usage", "signal"]},
                    "top": {"type": "integer", "minimum": 1},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "device_show",
            "description": "Resolve one device by hostname substring, IP, or MAC address.",
            "command": ["tplinkctl", "--json", "--no-input", "device", "<query>"],
            "read_only": True,
            "input_schema": {"type": "object", "required": ["query"], "properties": {"query": {"type": "string"}}, "additionalProperties": False},
        },
        {
            "name": "device_plan",
            "description": "Plan a device mutation without changing router state.",
            "command": ["tplinkctl", "--json", "--no-input", "device", "<action>", "<query>", "--plan"],
            "read_only": True,
            "input_schema": {
                "type": "object",
                "required": ["action", "query"],
                "properties": {
                    "action": {"type": "string", "enum": ["reserve", "release", "block", "unblock"]},
                    "query": {"type": "string"},
                    "enforce": {"type": "boolean"},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "device_block",
            "description": "Add a device to the access-control blacklist. Requires explicit confirmation and should be preceded by device_plan.",
            "command": ["tplinkctl", "--json", "--no-input", "device", "block", "<query>", "--yes"],
            "read_only": False,
            "risk": "device_connectivity_loss",
            "rollback": ["tplinkctl", "--json", "--no-input", "device", "unblock", "<query>", "--yes"],
            "input_schema": {"type": "object", "required": ["query"], "properties": {"query": {"type": "string"}, "enforce": {"type": "boolean"}}, "additionalProperties": False},
        },
        {
            "name": "device_unblock",
            "description": "Remove a device from the access-control blacklist.",
            "command": ["tplinkctl", "--json", "--no-input", "device", "unblock", "<query>", "--yes"],
            "read_only": False,
            "risk": "device_access_policy",
            "input_schema": {"type": "object", "required": ["query"], "properties": {"query": {"type": "string"}}, "additionalProperties": False},
        },
        {
            "name": "wifi_config_plan",
            "description": "Plan a Wi-Fi radio configuration change (channel, width, txpower, SSID) without changing router state.",
            "command": ["tplinkctl", "--json", "--no-input", "wifi-config", "<connection>", "--plan"],
            "read_only": True,
            "input_schema": {
                "type": "object",
                "required": ["connection"],
                "properties": {
                    "connection": {"type": "string", "enum": [item.value for item in Connection if item is not Connection.UNKNOWN]},
                    "channel": {"type": "string"},
                    "width": {"type": "string"},
                    "txpower": {"type": "string", "enum": ["low", "middle", "high"]},
                    "ssid": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "wifi_config",
            "description": "Configure Wi-Fi radio parameters (channel, channel width, txpower, SSID). Requires explicit confirmation.",
            "command": ["tplinkctl", "--json", "--no-input", "wifi-config", "<connection>", "--yes"],
            "read_only": False,
            "risk": "wifi_radio_configuration",
            "rollback": ["Re-run wifi-config with previous radio settings."],
            "input_schema": {
                "type": "object",
                "required": ["connection"],
                "properties": {
                    "connection": {"type": "string", "enum": [item.value for item in Connection if item is not Connection.UNKNOWN]},
                    "channel": {"type": "string"},
                    "width": {"type": "string"},
                    "txpower": {"type": "string", "enum": ["low", "middle", "high"]},
                    "ssid": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "doctor_deep",
            "description": "Run read-only web, auth, and endpoint health probes.",
            "command": ["tplinkctl", "--json", "--no-input", "doctor", "--deep"],
            "read_only": True,
            "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "audit_tail",
            "description": "Read recent local audit events from the append-only JSONL log.",
            "command": ["tplinkctl", "--json", "events", "--tail", "<limit>"],
            "read_only": True,
            "input_schema": {
                "type": "object",
                "properties": {
                    "tail": {"type": "integer", "minimum": 1},
                    "operation": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "state_snapshot",
            "description": "Save a redacted local router state snapshot.",
            "command": ["tplinkctl", "--json", "--no-input", "state", "save", "--name", "<name>"],
            "read_only": True,
            "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}, "additionalProperties": False},
        },
        {
            "name": "state_diff",
            "description": "Diff two saved local state snapshots.",
            "command": ["tplinkctl", "--json", "state", "diff"],
            "read_only": True,
            "input_schema": {
                "type": "object",
                "properties": {
                    "before": {"type": "string"},
                    "after": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1},
                    "raw": {"type": "boolean"},
                    "only": {"type": "string"},
                    "ignore": {"type": "array", "items": {"type": "string"}},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "port_forward_list",
            "description": "List NAT virtual servers and port forwarding rules.",
            "command": ["tplinkctl", "--json", "--no-input", "port-forward"],
            "read_only": True,
            "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "port_speed",
            "description": "Show physical Ethernet port link speed negotiation and supported speeds.",
            "command": ["tplinkctl", "--json", "--no-input", "ports"],
            "read_only": True,
            "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "ipv6_status",
            "description": "Show WAN and LAN IPv6 configuration and status.",
            "command": ["tplinkctl", "--json", "--no-input", "ipv6"],
            "read_only": True,
            "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "mesh_devices",
            "description": "List EasyMesh network nodes, roles, and connected client counts.",
            "command": ["tplinkctl", "--json", "--no-input", "mesh"],
            "read_only": True,
            "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "wireguard_status",
            "description": "Show WireGuard VPN server configuration and status.",
            "command": ["tplinkctl", "--json", "--no-input", "wireguard"],
            "read_only": True,
            "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "nat_status",
            "description": "Show NAT ALG passthrough rules, DMZ status, and UPnP enablement.",
            "command": ["tplinkctl", "--json", "--no-input", "nat"],
            "read_only": True,
            "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "qos_status",
            "description": "Show Quality of Service (QoS) enablement, bandwidth limits, and priority splits.",
            "command": ["tplinkctl", "--json", "--no-input", "qos"],
            "read_only": True,
            "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "storage_status",
            "description": "Show attached USB storage disks, Samba/FTP folder sharing, and Apple Time Machine status.",
            "command": ["tplinkctl", "--json", "--no-input", "storage"],
            "read_only": True,
            "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "time_status",
            "description": "Show router system date, time, timezone, and NTP server configuration.",
            "command": ["tplinkctl", "--json", "--no-input", "time"],
            "read_only": True,
            "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "power_status",
            "description": "Show router eco/power mode, smart eco state, and scheduled power-saving rules.",
            "command": ["tplinkctl", "--json", "--no-input", "power"],
            "read_only": True,
            "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "wifi_advanced",
            "description": "Show advanced Wi-Fi radio features: OFDMA, OFDMA MIMO, TWT, Smart Connect, DFS channels, radio schedule, and region.",
            "command": ["tplinkctl", "--json", "--no-input", "wifi-advanced"],
            "read_only": True,
            "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "ddns_status",
            "description": "Show the configured dynamic DNS provider.",
            "command": ["tplinkctl", "--json", "--no-input", "ddns"],
            "read_only": True,
            "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "iptv_status",
            "description": "Show IPTV/VLAN configuration, IGMP snooping, and LAN port assignments.",
            "command": ["tplinkctl", "--json", "--no-input", "iptv"],
            "read_only": True,
            "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    ]
    return enrich(tools)


# A route is part of the registry entry, never a second HTTP dispatch table.
ROUTES = {
    "router_status": ("get", "/v1/router/status"),
    "firmware_audit": ("get", "/v1/router/firmware"),
    "led_status": ("get", "/v1/router/led"),
    "led_plan": ("post", "/v1/router/led/plans"),
    "led_set": ("put", "/v1/router/led"),
    "device_list": ("get", "/v1/devices"),
    "device_show": ("get", "/v1/devices/{query}"),
    "device_plan": ("post", "/v1/devices/{query}/plans"),
    "device_block": ("put", "/v1/devices/{query}/block"),
    "device_unblock": ("delete", "/v1/devices/{query}/block"),
    "wifi_config_plan": ("post", "/v1/wifi/{connection}/plans"),
    "wifi_config": ("put", "/v1/wifi/{connection}/configuration"),
    "wifi_info": ("get", "/v1/wifi"),
    "vpn_status": ("get", "/v1/vpn/server"),
    "vpn_client_status": ("get", "/v1/vpn/client"),
    "port_forward_list": ("get", "/v1/nat/port-forwards"),
    "port_speed": ("get", "/v1/network/ports"),
    "ipv6_status": ("get", "/v1/network/ipv6"),
    "mesh_devices": ("get", "/v1/mesh"),
    "wireguard_status": ("get", "/v1/vpn/wireguard"),
    "nat_status": ("get", "/v1/nat"),
    "qos_status": ("get", "/v1/qos"),
    "storage_status": ("get", "/v1/storage"),
    "time_status": ("get", "/v1/system/time"),
    "power_status": ("get", "/v1/system/power"),
    "wifi_advanced": ("get", "/v1/wifi/advanced"),
    "ddns_status": ("get", "/v1/network/ddns"),
    "iptv_status": ("get", "/v1/network/iptv"),
    "doctor_deep": ("get", "/v1/health"),
}
LOCAL_ONLY = {
    "watch": "Repeated samples and streams belong to the local CLI/MCP lifecycle.",
    "audit_tail": "Local audit records are not remotely readable.",
    "state_snapshot": "Writes a local snapshot file, not router state.",
    "state_diff": "Accepts local snapshot references; never expose filesystem selectors over HTTP.",
}
PLAN_OPERATIONS = {"device_block": "device_plan", "device_unblock": "device_plan",
                   "led_set": "led_plan", "wifi_config": "wifi_config_plan"}


def object_schema(properties: dict, required: list[str] | None = None, *, extra: bool = False) -> dict:
    return {"type": "object", "properties": properties,
            "required": list(properties) if required is None else required, "additionalProperties": extra}


STRING = {"type": "string"}
BOOLEAN = {"type": "boolean"}
OPEN_OBJECT = {"type": "object", "additionalProperties": True}
ROLLBACK_SCHEMA = object_schema({
    "supported": BOOLEAN, "automatic": {"const": False, "type": "boolean"},
    "commands": {"type": "array", "items": {"type": "array", "items": STRING}},
    "limitations": {"type": "array", "items": STRING},
})
PLAN_SCHEMA = object_schema({
    "plan_id": {"type": "string", "minLength": 32}, "operation": STRING,
    "profile": STRING, "expires_at": {"type": "string", "format": "date-time"},
    "target": OPEN_OBJECT, "arguments": OPEN_OBJECT,
    "diff": {"type": "array", "items": object_schema({"field": STRING, "before": {}, "after": {}})},
    "risk": STRING, "rollback": ROLLBACK_SCHEMA,
    "requires_confirmation": {"type": "boolean", "const": True},
    "executable": BOOLEAN,
})
ERROR_STATUS = {"usage": 400, "auth": 401, "permission": 403, "not_found": 404,
                "confirmation_required": 409, "conflict": 409, "router": 502, "internal": 500}
ERROR_SCHEMA = object_schema({"error": object_schema({
    "kind": {"type": "string", "enum": list(ERROR_STATUS)}, "message": STRING,
})})


def data_schema(name: str) -> dict:
    """Stable top-level models, with firmware-dependent details left extensible."""
    device = object_schema({"hostname": STRING, "ip": STRING, "mac": STRING,
                            "active": BOOLEAN}, extra=True)
    if name == "device_show":
        return device
    if name == "device_list":
        return {"type": "array", "items": device}
    if name in {"port_forward_list", "mesh_devices"}:
        return {"type": "array", "items": OPEN_OBJECT}
    if name == "router_status":
        return object_schema({key: OPEN_OBJECT for key in ("router", "wan", "wifi", "health")}, extra=True)
    if name in {"led_status", "led_set"}:
        return object_schema({"enabled": {"type": ["boolean", "null"]}, "schedule": OPEN_OBJECT}, extra=True)
    if name == "device_block":
        return object_schema({"blocked": BOOLEAN, "already_listed": BOOLEAN,
                              "enforced": BOOLEAN, "device": device, "access_control": OPEN_OBJECT})
    if name == "device_unblock":
        return object_schema({"unblocked": BOOLEAN, "device": OPEN_OBJECT})
    if name == "wifi_config":
        return object_schema({"connection": STRING, "configured": BOOLEAN}, extra=True)
    if name == "wifi_info":
        return object_schema({"networks": {"type": "array", "items": OPEN_OBJECT},
                              "smart_connect": {"type": ["boolean", "null"]}, "errors": OPEN_OBJECT})
    return deepcopy(OPEN_OBJECT)


def enrich(entries: list[dict]) -> list[dict]:
    from . import cli
    for name, command, description in (
        ("wifi_info", "wifi-info", "Read Wi-Fi networks without secrets."),
        ("vpn_status", "vpn-status", "Read VPN server status."),
        ("vpn_client_status", "vpn-client-status", "Read VPN client enablement and profiles."),
    ):
        entries.append({"name": name, "description": description,
                        "command": ["tplinkctl", "--json", "--no-input", command],
                        "read_only": True, "input_schema": object_schema({})})
    entries.append({"name": "watch", "description": "Sample read-only router state repeatedly.",
                    "command": ["tplinkctl", "--json", "--no-input", "watch"], "read_only": True,
                    "input_schema": object_schema({
                        "target": {"type": "string", "enum": ["status", "devices", "speed", "health"]},
                        "count": {"type": "integer", "minimum": 1},
                        "interval": {"type": "number", "minimum": 0}, "active": BOOLEAN,
                        "top": {"type": "integer", "minimum": 1}}, [])})
    for item in entries:
        name = item["name"]
        item["risk"] = item.get("risk", "read_only")
        item["local_only"] = LOCAL_ONLY.get(name)
        if name not in LOCAL_ONLY:
            method, path = ROUTES[name]  # fail closed for an unclassified new entry
            item["http"] = {"method": method, "path": path}
        item["plan_operation"] = PLAN_OPERATIONS.get(name)
        item["rollback_contract"] = {
            "mode": "manual" if name in PLAN_OPERATIONS else "not_applicable",
            "automatic": False,
            "description": "Plan reports state-derived commands and limitations; never an automatic recovery guarantee.",
        }
        item["profiles"] = list(cli.POLICY_PROFILES)
        if name in {"device_plan", "device_block", "device_unblock"}:
            item["profiles"] = ["device-admin", "network-admin", "dangerous"]
        elif name in {"led_plan", "led_set", "wifi_config_plan", "wifi_config"}:
            item["profiles"] = ["network-admin", "dangerous"]
        schema = item["input_schema"]
        for prop in schema.get("properties", {}).values():
            if prop.get("type") == "string":
                prop.setdefault("minLength", 1)
                prop.setdefault("maxLength", 256)
        if not item["read_only"]:
            schema["properties"]["confirm"] = {"type": "boolean", "description": "Must be true to execute the mutation."}
            schema["required"] = sorted(set(schema.get("required", [])) | {"confirm"})
        item["output_schema"] = data_schema(name)
    return entries


def http_input(item: dict) -> dict:
    schema = deepcopy(item["input_schema"])
    if not item["read_only"]:
        schema["properties"]["plan_id"] = {"type": "string", "minLength": 32, "maxLength": 128}
        schema["required"] = sorted(set(schema["required"]) | {"plan_id"})
    if item["plan_operation"] or item["name"] in set(PLAN_OPERATIONS.values()):
        schema["properties"]["reason"] = {"type": "string", "maxLength": 512,
                                            "description": "Accepted but fully redacted in audit records."}
    return schema


def http_output(item: dict) -> dict:
    if item["name"] in set(PLAN_OPERATIONS.values()):
        return deepcopy(PLAN_SCHEMA)
    return object_schema({"data": item["output_schema"]})
