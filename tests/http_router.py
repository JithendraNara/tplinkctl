"""Synthetic router protocol fixture. No transport authorization behavior lives here."""
from copy import deepcopy
import json
import secrets
from urllib.parse import parse_qs, urlsplit

from tplink_admin import cli


class Router:
    def __init__(self):
        self.secret = secrets.token_urlsafe(32)
        self.mac = "02-00-00-00-00-01"
        self.device = {"hostname": "fixture-device", "_ipaddr": "192.0.2.10", "_macaddr": self.mac,
                       "active": True, "type": "wired", "traffic_usage": 0, "down_speed": 0, "up_speed": 0}
        self.forms = {
            cli.LED_GENERAL: {"enable": "on", "ledst_support": "yes", "time_set": "yes"},
            cli.LED_SCHEDULE: {"enable": "on", "ledpm_support": "yes", "time_start": "22:00", "time_end": "06:00"},
            cli.ACCESS_CONTROL_ENABLE: {"enable": "off"},
            cli.ACCESS_CONTROL_MODE: {"access_mode": "black"},
            cli.ACCESS_BLACK_LIST: [], cli.ACCESS_WHITE_LIST: [],
            cli.ACCESS_BLACK_DEVICES: [], cli.DHCP_RESERVATION: [],
            "admin/wireless?form=wireless_5g": {"channel": "36", "htmode": "80", "txpower": "high", "ssid": "fixture-network", "password": self.secret},
            cli.WIREGUARD_CONFIG: {"enable": "on", "public_key": "fixture-public", "private_key": self.secret},
            cli.DDNS_PROVIDER: {"provider": "fixture-provider"},
            cli.WIRELESS_REGION: {"country": "ZZ"},
        }
        self.writes = []
        self.requests = []
        self.fail_writes = False
        self.ignore_writes = False
        self.authorized = False

    def authorize(self):
        self.authorized = True

    def logout(self):
        self.authorized = False

    def get_firmware(self):
        return {"model": "fixture-router", "hardware_version": "test", "firmware_version": "test"}

    def get_status(self):
        return {"devices": [deepcopy(self.device)], "cpu_usage": 0.1, "mem_usage": 0.2,
                "_wan_ipv4_addr": "198.51.100.2", "_wan_ipv4_gateway": "198.51.100.1",
                "_lan_ipv4_addr": "192.0.2.1", "clients_total": 1}

    def get_ipv4_status(self):
        return {"_wan_ipv4_ipaddr": "198.51.100.2"}

    def get_ipv4_reservations(self):
        return deepcopy(self.forms[cli.DHCP_RESERVATION])

    def get_ipv4_dhcp_leases(self):
        return []

    def get_vpn_status(self):
        return {"openvpn_enable": False}

    def get_vpn_client_status(self):
        return {"enabled": False}

    def request(self, path, data="", **kwargs):
        self.requests.append((path, data))
        url = urlsplit(path)
        query = parse_qs(url.query)
        base = url.path + "?form=" + query.get("form", [""])[0]
        payload = json.loads(data) if data.startswith("{") else {k: v[0] for k, v in parse_qs(data).items()}
        operation = payload.get("operation", "read")
        state = self.forms.get(base, {})
        if operation in {"write", "insert", "remove"}:
            self.writes.append((base, deepcopy(payload)))
            if self.fail_writes:
                raise RuntimeError(self.secret)
            if not self.ignore_writes:
                if operation == "write":
                    state.update({k: v for k, v in payload.items() if k != "operation"})
                elif operation == "insert":
                    state.append(json.loads(payload["new"]))
                elif operation == "remove":
                    del state[int(payload["index"])]
        return {"data": deepcopy(state)} if operation == "load" else deepcopy(state)


class WebResponse:
    status_code = 200
    text = '<html><meta name="model" content="fixture-router"></html>'

    def raise_for_status(self):
        return None
