import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tplink_admin import cli


class FakeRouter:
    def __init__(self):
        self.authorized = False
        self.logged_out = False

    def authorize(self):
        self.authorized = True

    def logout(self):
        self.logged_out = True

    def get_firmware(self):
        return {
            "model": "Archer BE3500",
            "hardware_version": "Archer BE3500 v1.0",
            "firmware_version": "1.1.3",
        }

    def get_status(self):
        return {
            "_wan_ipv4_addr": "10.0.0.17",
            "_wan_ipv4_gateway": "10.0.0.1",
            "_lan_ipv4_addr": "192.168.0.1",
            "cpu_usage": 0.16,
            "mem_usage": 0.47,
            "clients_total": 1,
            "wired_total": 1,
            "wifi_clients_total": 0,
            "guest_clients_total": 0,
            "iot_clients_total": 0,
            "wifi_2g_enable": True,
            "wifi_5g_enable": True,
            "wifi_6g_enable": None,
            "guest_2g_enable": False,
            "guest_5g_enable": False,
            "guest_6g_enable": None,
            "iot_2g_enable": True,
            "iot_5g_enable": False,
            "iot_6g_enable": None,
            "devices": [
                {
                    "hostname": "debian_linux",
                    "_ipaddr": "192.168.0.79",
                    "_macaddr": "48-BA-4E-40-B4-F4",
                    "active": True,
                    "type": "wired",
                }
            ],
        }

    def get_ipv4_status(self):
        return {
            "_wan_ipv4_ipaddr": "10.0.0.17",
            "_wan_ipv4_gateway": "10.0.0.1",
            "_wan_ipv4_netmask": "255.255.255.0",
            "_wan_ipv4_pridns": "10.0.0.1",
            "_wan_ipv4_snddns": "8.8.8.8",
        }

    def get_ipv4_dhcp_leases(self):
        return [{"hostname": "debian_linux", "_ipaddr": "192.168.0.79"}]

    def get_ipv4_reservations(self):
        return []

    def get_vpn_status(self):
        return {"openvpn_enable": False}

    def get_vpn_client_status(self):
        return {"enabled": False}


def run_cli(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), patch.object(cli, "build_router", return_value=FakeRouter()):
        cli.main(argv)
    return out.getvalue()


class CliTests(unittest.TestCase):
    def test_health_reports_double_nat(self):
        output = run_cli(["--json", "--no-input", "health"])
        data = json.loads(output)
        self.assertFalse(data["ok"])
        self.assertIn("private", data["warnings"][0])

    def test_clients_active_outputs_devices(self):
        output = run_cli(["--json", "--no-input", "clients", "--active"])
        data = json.loads(output)
        self.assertEqual(data[0]["hostname"], "debian_linux")

    def test_denylist_blocks_command(self):
        with self.assertRaises(SystemExit) as raised:
            cli.main(["--disable-commands", "status", "status"])
        self.assertIn("blocked", str(raised.exception))

    def test_endpoint_and_route_discovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp)
            (bundle / "index-ESh8tgBq.js").write_text(
                '{name:"internetAdv",path:"internetAdv",component:()=>o(()=>import("./index-BOBVatjl.js")}',
                encoding="utf-8",
            )
            (bundle / "index-BOBVatjl.js").write_text(
                'function a(){return L.read("/admin/network?form=wan_ipv4_status")}'
                'function b(){return L.write("/admin/network?form=wan_fc",{})}',
                encoding="utf-8",
            )
            routes = cli.discover_routes(bundle)
            endpoints = cli.discover_endpoints(bundle)

        self.assertEqual(routes[0]["name"], "internetAdv")
        self.assertEqual(endpoints[0]["endpoint"], "/admin/network?form=wan_fc")
        self.assertEqual(endpoints[1]["endpoint"], "/admin/network?form=wan_ipv4_status")


if __name__ == "__main__":
    unittest.main()
