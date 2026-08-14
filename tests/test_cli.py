import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tplink_admin import cli


class FakeResponse:
    status_code = 200
    text = '<html><head><meta name="model" content="Archer"><script src="js/app.js"></script></head></html>'

    def raise_for_status(self):
        return None


class FakeRouter:
    last = None

    def __init__(self):
        FakeRouter.last = self
        self.authorized = False
        self.logged_out = False
        self.requests = []
        self.vpn_devices = []
        self.reservations = []
        self.blacklist = []
        self.access_enabled = "off"
        self.access_mode = "black"
        self.vpn_access = "off"
        self.led_enabled = "on"
        self.led_schedule_enabled = "on"
        self.led_schedule_start = "23:00"
        self.led_schedule_end = "07:00"

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
                    "down_speed": 1024,
                    "type": "wired",
                    "traffic_usage": 2048,
                    "up_speed": 512,
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

    def request(self, path, data="", **kwargs):
        self.requests.append((path, data, kwargs))
        base_path = path.split("&operation=", 1)[0]
        if base_path == cli.DHCP_RESERVATION:
            if data == "operation=load":
                return {"data": self.reservations}
            if "operation=insert" in data:
                self.reservations.append(
                    {
                        "key": "reservation-1",
                        "hostname": "debian_linux",
                        "ip": "192.168.0.79",
                        "mac": "48-BA-4E-40-B4-F4",
                        "enable": "on",
                    }
                )
                return None if kwargs.get("ignore_response") else {}
            if "operation=remove" in data:
                self.reservations.clear()
                return None if kwargs.get("ignore_response") else {}
        if base_path == cli.ACCESS_CONTROL_ENABLE:
            if data == "operation=read":
                return {"enable": self.access_enabled}
            if "operation=write" in data:
                self.access_enabled = "on" if "enable=on" in data else "off"
                return None if kwargs.get("ignore_response") else {}
        if base_path == cli.ACCESS_CONTROL_MODE:
            if data == "operation=read":
                return {"access_mode": self.access_mode}
            if "operation=write" in data:
                self.access_mode = "white" if "access_mode=white" in data else "black"
                return None if kwargs.get("ignore_response") else {}
        if base_path == cli.ACCESS_BLACK_LIST:
            if data == "operation=load":
                return {"data": self.blacklist}
            if "operation=insert" in data:
                self.blacklist.append(
                    {
                        "key": "block-1",
                        "name": "debian_linux",
                        "ipaddr": "192.168.0.79",
                        "mac": "48-BA-4E-40-B4-F4",
                    }
                )
                return None if kwargs.get("ignore_response") else {}
            if "operation=remove" in data:
                self.blacklist.clear()
                return None if kwargs.get("ignore_response") else {}
        if base_path == cli.ACCESS_WHITE_LIST:
            if data == "operation=load":
                return {"data": []}
        if base_path == cli.ACCESS_BLACK_DEVICES:
            if data == "operation=load":
                return {
                    "data": [
                        {
                            "name": "debian_linux",
                            "type": "Computer",
                            "mac": "48-BA-4E-40-B4-F4",
                            "ipaddr": "192.168.0.79",
                            "host": "NON_HOST",
                            "conn_type": "wired",
                        }
                    ]
                }
        if base_path == cli.LED_GENERAL:
            if data == "operation=read":
                return {"enable": self.led_enabled, "ledst_support": "yes", "time_set": "yes"}
            if "operation=write" in data:
                self.led_enabled = "on" if "enable=on" in data else "off"
                return None if kwargs.get("ignore_response") else {}
        if base_path == cli.LED_SCHEDULE:
            if data == "operation=read":
                return {
                    "enable": self.led_schedule_enabled,
                    "ledpm_support": "yes",
                    "time_start": self.led_schedule_start,
                    "time_end": self.led_schedule_end,
                }
            if "operation=write" in data:
                from urllib.parse import parse_qs

                payload = parse_qs(data)
                self.led_schedule_enabled = payload.get("enable", ["off"])[0]
                self.led_schedule_start = payload.get("time_start", [self.led_schedule_start])[0]
                self.led_schedule_end = payload.get("time_end", [self.led_schedule_end])[0]
                return None if kwargs.get("ignore_response") else {}
        if base_path == cli.FIRMWARE_LATEST:
            return {
                "latest_flag": "0",
                "latest_version": "1.1.4 Build 20260701",
                "detail": "Security and stability fixes.",
            }
        if base_path == cli.FIRMWARE_AUTO_UPDATE:
            return {"enable": "on", "time": "03:00"}
        if base_path == "admin/vpn?form=vpn_user_list":
            if data == "operation=load":
                return {"data": [{"name": "debian_linux", "mac": "48-BA-4E-40-B4-F4", "access": self.vpn_access}]}
            if "operation=update" in data:
                enabled = "access%22%3A+%22on" in data or "access%22%3A%22on" in data
                self.vpn_access = "on" if enabled else "off"
                self.vpn_devices.append(("48-BA-4E-40-B4-F4", enabled))
                return None if kwargs.get("ignore_response") else {}
        if base_path == "admin/wireless?form=smart_connect":
            return {"smart_enable": "on"}
        if "wireless_2g" in path or "wireless_5g" in path:
            if "operation=write" in data or "operation=write" in path:
                from urllib.parse import parse_qs
                payload = parse_qs(data)
                if "channel" in payload:
                    self.wifi_channel = payload["channel"][0]
                if "htmode" in payload:
                    self.wifi_htmode = payload["htmode"][0]
                if "txpower" in payload:
                    self.wifi_txpower = payload["txpower"][0]
                if "ssid" in payload:
                    self.wifi_ssid = payload["ssid"][0]
                return None if kwargs.get("ignore_response") else {}
            return {
                "channel": getattr(self, "wifi_channel", "auto"),
                "current_channel": getattr(self, "wifi_channel", "48"),
                "htmode": getattr(self, "wifi_htmode", "160"),
                "txpower": getattr(self, "wifi_txpower", "high"),
                "ssid": getattr(self, "wifi_ssid", "ps"),
                "wireless_2g_enable": "on",
                "wireless_2g_ssid": "lab",
                "wireless_2g_current_channel": "3",
                "wireless_2g_psk_key": "secret",
            }
        if "guest_2g" in path:
            return {"guest_2g_enable": "off", "guest_2g_ssid": "lab_guest"}
        if "iot_2g" in path:
            return {"iot_2g_enable": "on", "iot_2g_ssid": "lab_iot"}
        if base_path == cli.PORT_FORWARDING:
            return [
                {
                    "name": "NPM-HTTPS",
                    "internal_port": "8443",
                    "external_port": "443",
                    "ipaddr": "192.168.0.72",
                    "protocol": "TCP",
                    "enable": "on",
                }
            ]
        if base_path == cli.PORT_SPEED_CURRENT:
            return {"speed": "1000F"}
        if base_path == cli.PORT_SPEED_SUPPORTED:
            return {"supported": ["auto", "1000F", "100F", "100H", "10F", "10H"]}
        if base_path == cli.NETWORK_STATUS_IPV6:
            return {
                "wan_ipv6_enable": "on",
                "wan_ipv6_ip6addr": "2601::1/64",
                "wan_ipv6_gateway": "fe80::1",
                "wan_ipv6_pridns": "2001:4860:4860::8888",
                "wan_ipv6_snddns": "2001:4860:4860::8844",
                "wan_ipv6_conntype": "dhcpv6",
                "lan_ipv6_ipaddr": "FE80::6A7F:F0FF:FE3B:1CA0/64",
                "lan_ipv6_assign_type": "slaac",
                "lan_ipv6_link_local_addr": "FE80::6A7F:F0FF:FE3B:1CA0/64",
            }
        if base_path == cli.NETWORK_LAN_IPV6:
            return {
                "address": "2601::6a7f:f0ff:fe3b:1ca0/64",
                "assign_type": "slaac",
                "dhcp_prefix": "",
                "slaac_prefix": "2601::/64",
            }
        if base_path == cli.EASYMESH_DEVICE_LIST:
            return [
                {
                    "mac": "68-7F-F0-3B-1C-A0",
                    "client_num": 4,
                    "ip": "192.168.0.1",
                    "role": "main_router",
                    "name": "Archer BE3500",
                    "model": "Archer BE3500",
                    "status": "connected",
                    "location": "bedroom",
                    "vendor": "TP-Link",
                    "device_type": "WirelessRouter",
                }
            ]
        if base_path == cli.WIREGUARD_CONFIG:
            return {
                "enable": True,
                "listen_port": "51820",
                "address": "10.5.5.1/32",
                "public_key": "agvcmR8FY3Y4phfJaCC5b0UnOoHqYxrHGJDHKMhi3Uc=",
                "persistent_keepalive": "25",
                "dns": True,
                "private_key": "sDfwQQpn3mKGETYQTgUv+ZzEVPVbCJdDJtLnNvkyXHo=",
            }
        if base_path == cli.NAT_ALG:
            return {"sip": "on", "ipsec": "on", "pptp": "on", "ftp": "on"}
        if base_path == cli.NAT_DMZ:
            return {"enable": "off", "ipaddr": ""}
        if base_path == cli.UPNP_SETTING:
            return {"enable": "on"}
        if base_path == cli.QOS_SETTING:
            return {
                "enable": "on",
                "enable_app": "on",
                "up_band": "1000",
                "down_band": "1000",
                "max_up_band": 1000,
                "max_down_band": 1000,
                "high": "90",
                "middle": "30",
                "low": "10",
            }
        if base_path == cli.DISK_METADATA:
            return {"number": 0, "list": {}}
        if base_path == cli.FOLDER_SHARING_SETTINGS:
            return [
                {"protocol": "samba", "enable": "on", "link": r"\\192.168.0.1", "port": "---"},
                {"protocol": "ftp", "enable": "on", "link": "ftp://192.168.0.1:21", "port": 21},
            ]
        if base_path == cli.FOLDER_SHARING_SERVER:
            return {"server": "TP-Share"}
        if base_path == cli.TIME_MACHINE_SETTINGS:
            return {"enable": "off", "capacity": 0, "free": 0, "limitsize": "0"}
        if base_path == cli.TIME_SETTINGS:
            return {
                "date": "08/14/2026",
                "time": "00:50:00",
                "day": "Fri",
                "timezone": "19",
                "ntp_svr1": "us.pool.ntp.org",
                "ntp_svr2": "north-america.pool.ntp.org",
                "type": "auto",
                "hour24_enable": "off",
            }
        if base_path == cli.WIRELESS_OFDMA:
            return {"enable": "off"}
        if base_path == cli.WIRELESS_OFDMA_MIMO:
            return {"setting": "all"}
        if base_path == cli.WIRELESS_TWT:
            return {"enable": "off"}
        if base_path == cli.WIRELESS_ADDITION:
            return {
                "zerowait_dfs": "on",
                "wmm": "on",
                "shortgi": "on",
                "beacon_int": "100",
                "rts": "2346",
                "frag": "2346",
                "isolate": "off",
                "mscs_enable": "on",
            }
        if base_path == cli.WIRELESS_SCHEDULE_V2:
            return {"enable": False, "max_rules": 20, "list": {}}
        if base_path == cli.WIRELESS_CHANNEL_EXTRA_5G:
            return [
                {"channelWidth": 20, "channelList": []},
                {"channelWidth": 160, "channelList": ["132", "136", "140", "144"]},
            ]
        if base_path == cli.WIRELESS_REGION:
            return {"country": "US"}
        if base_path == cli.DDNS_PROVIDER:
            return {"provider": "tp-link"}
        if base_path == cli.IPTV_SETTING:
            return {
                "enable": "off",
                "mode": "Bridge",
                "igmp_snooping_enable": "on",
                "igmp_version": "2",
                "mcwifi_enable": "on",
                "iptv_enable": "on",
                "ipphone_enable": "on",
                "support_mode_list": ["Bridge", "Custom"],
                "port_settings": [
                    {"name": "lan1", "type": "Internet"},
                    {"name": "lan3", "type": "IPTV"},
                ],
            }
        if base_path == cli.ECO_MODE_SETTINGS:
            return {"enable": False, "power_mode": "balanced", "smart_eco": True, "schedule_mode": "always"}
        return {}

    def set_vpn_client_device(self, mac, enable):
        self.vpn_devices.append((mac, enable))


def run_cli(argv):
    out = io.StringIO()
    with (
        tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(out),
        patch.dict("os.environ", {"XDG_CONFIG_HOME": tmp}, clear=False),
        patch.object(cli, "build_router", return_value=FakeRouter()),
    ):
        cli.main(argv)
    return out.getvalue()


def run_cli_in_config(tmp, argv, router=None):
    out = io.StringIO()
    with (
        contextlib.redirect_stdout(out),
        patch.dict("os.environ", {"XDG_CONFIG_HOME": tmp}, clear=False),
        patch.object(cli, "build_router", return_value=router or FakeRouter()),
    ):
        cli.main(argv)
    return out.getvalue()


class CliTests(unittest.TestCase):
    def test_firmware_check_is_read_only_and_normalized(self):
        output = run_cli(["--json", "--no-input", "firmware-check"])
        data = json.loads(output)
        self.assertTrue(data["update"]["available"])
        self.assertEqual(data["update"]["latest_version"], "1.1.4 Build 20260701")
        self.assertTrue(data["auto_update"]["enabled"])
        self.assertFalse(data["action_taken"])
        self.assertTrue(all("operation=read" in path for path, _, _ in FakeRouter.last.requests))

    def test_firmware_audit_does_not_infer_unknown_availability(self):
        router = FakeRouter()
        original_request = router.request

        def request(path, data="", **kwargs):
            if path.split("&operation=", 1)[0] == cli.FIRMWARE_LATEST:
                return {"latest_flag": "unknown"}
            return original_request(path, data, **kwargs)

        router.request = request
        data = cli.firmware_audit(router)
        self.assertIsNone(data["update"]["available"])

    def test_health_reports_double_nat(self):
        output = run_cli(["--json", "--no-input", "health"])
        data = json.loads(output)
        self.assertFalse(data["ok"])
        self.assertIn("private", data["warnings"][0])

    def test_clients_active_outputs_devices(self):
        output = run_cli(["--json", "--no-input", "clients", "--active"])
        data = json.loads(output)
        self.assertEqual(data[0]["hostname"], "debian_linux")
        self.assertEqual(data[0]["ip"], "192.168.0.79")

    def test_device_lookup_outputs_detail(self):
        output = run_cli(["--json", "--no-input", "device", "debian"])
        data = json.loads(output)
        self.assertEqual(data["mac"], "48-BA-4E-40-B4-F4")

    def test_device_reserve_requires_confirmation(self):
        with self.assertRaises(SystemExit) as raised:
            run_cli(["--json", "--no-input", "device", "reserve", "debian"])
        self.assertIn("--yes", str(raised.exception))

    def test_device_reserve_creates_dhcp_reservation(self):
        output = run_cli(["--json", "--no-input", "device", "reserve", "debian", "--yes"])
        data = json.loads(output)
        self.assertTrue(data["created"])
        self.assertEqual(data["reservation"]["ip"], "192.168.0.79")

    def test_device_reserve_accepts_postfix_action(self):
        output = run_cli(["--json", "--no-input", "device", "debian", "reserve", "--yes"])
        data = json.loads(output)
        self.assertTrue(data["created"])
        self.assertEqual(data["reservation"]["mac"], "48-BA-4E-40-B4-F4")

    def test_device_block_can_enforce_blacklist_mode(self):
        output = run_cli(["--json", "--no-input", "device", "block", "debian", "--yes", "--enforce"])
        data = json.loads(output)
        self.assertTrue(data["blocked"])
        self.assertTrue(data["enforced"])
        self.assertEqual(data["access_control"]["mode"], "black")

    def test_device_block_accepts_postfix_action(self):
        output = run_cli(["--json", "--no-input", "device", "debian", "block", "--yes"])
        data = json.loads(output)
        self.assertTrue(data["blocked"])
        self.assertFalse(data["enforced"])

    def test_device_unblock_removes_blacklist_entry(self):
        router = FakeRouter()
        router.blacklist.append({"key": "block-1", "name": "debian_linux", "ipaddr": "192.168.0.79", "mac": "48-BA-4E-40-B4-F4"})
        with tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {"XDG_CONFIG_HOME": tmp}, clear=False), patch.object(cli, "build_router", return_value=router):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                cli.main(["--json", "--no-input", "device", "unblock", "48-BA-4E-40-B4-F4", "--yes"])
        data = json.loads(out.getvalue())
        self.assertTrue(data["unblocked"])
        self.assertEqual(router.blacklist, [])

    def test_device_vpn_sets_client_device(self):
        router = FakeRouter()
        with tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {"XDG_CONFIG_HOME": tmp}, clear=False), patch.object(cli, "build_router", return_value=router):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                cli.main(["--json", "--no-input", "device", "vpn", "debian", "on", "--yes"])
        data = json.loads(out.getvalue())
        self.assertTrue(data["vpn_client"])
        self.assertEqual(router.vpn_devices, [("48-BA-4E-40-B4-F4", True)])

    def test_speed_summarizes_throughput(self):
        output = run_cli(["--json", "--no-input", "speed"])
        data = json.loads(output)
        self.assertEqual(data["totals"]["down_Bps"], 1024)
        self.assertEqual(data["totals"]["up_Bps"], 512)

    def test_wifi_info_redacts_password_fields(self):
        output = run_cli(["--json", "--no-input", "wifi-info"])
        data = json.loads(output)
        self.assertTrue(data["smart_connect"])
        self.assertEqual(data["networks"][0]["ssid"], "lab")
        self.assertNotIn("psk_key", data["networks"][0])

    def test_wifi_config_requires_confirmation_and_verifies(self):
        with self.assertRaises(SystemExit) as raised:
            run_cli(["--json", "--no-input", "wifi-config", "host_5g", "--channel", "149", "--width", "80"])
        self.assertIn("--yes", str(raised.exception))
        data = json.loads(run_cli(["--json", "--no-input", "wifi-config", "host_5g", "--channel", "149", "--width", "80", "--yes"]))
        self.assertTrue(data["configured"])
        self.assertEqual(data["channel"], "149")
        self.assertEqual(data["width"], "80")

    def test_wifi_config_plan_returns_preview_without_mutating(self):
        plan = json.loads(run_cli(["--json", "--no-input", "wifi-config", "host_5g", "--channel", "149", "--width", "80", "--plan"]))
        self.assertTrue(plan["plan"])
        self.assertEqual(plan["action"], "wifi-config")
        self.assertIn("channel: auto -> 149", plan["changes"])

    def test_led_status_reports_general_and_schedule(self):
        data = json.loads(run_cli(["--json", "--no-input", "led", "status"]))
        self.assertTrue(data["enabled"])
        self.assertTrue(data["schedule"]["enabled"])
        self.assertEqual(data["schedule"]["start"], "23:00")

    def test_led_toggle_requires_confirmation_and_verifies(self):
        with self.assertRaises(SystemExit) as raised:
            run_cli(["--json", "--no-input", "led", "off"])
        self.assertIn("--yes", str(raised.exception))
        data = json.loads(run_cli(["--json", "--no-input", "led", "off", "--yes"]))
        self.assertFalse(data["enabled"])

    def test_led_schedule_plan_and_apply(self):
        plan = json.loads(
            run_cli(["--json", "--no-input", "led", "schedule", "on", "--start", "22:30", "--end", "06:15", "--plan"])
        )
        self.assertTrue(plan["plan"])
        self.assertEqual(plan["action"], "router.led.set")
        data = json.loads(
            run_cli(["--json", "--no-input", "led", "schedule", "on", "--start", "22:30", "--end", "06:15", "--yes"])
        )
        self.assertEqual(data["schedule"]["start"], "22:30")
        self.assertEqual(data["schedule"]["end"], "06:15")

    def test_read_places_operation_in_url(self):
        router = FakeRouter()
        with tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {"XDG_CONFIG_HOME": tmp}, clear=False), patch.object(cli, "build_router", return_value=router):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                cli.main(["--json", "--no-input", "read", "/admin/ledgeneral?form=setting"])
        self.assertEqual(json.loads(out.getvalue())["enable"], "on")
        self.assertEqual(router.requests[0][0], "admin/ledgeneral?form=setting&operation=read")

    def test_capabilities_reports_agent_contract(self):
        output = run_cli(["--json", "capabilities"])
        data = json.loads(output)
        capability_ids = {item["id"] for item in data["capabilities"]}
        self.assertIn("device.block", capability_ids)
        self.assertIn("router.status", capability_ids)
        self.assertIn("device-admin", data["policy_profiles"])
        device_block = next(item for item in data["capabilities"] if item["id"] == "device.block")
        device_vpn = next(item for item in data["capabilities"] if item["id"] == "device.vpn")
        led_status = next(item for item in data["capabilities"] if item["id"] == "router.led.status")
        vpn_client_status = next(item for item in data["capabilities"] if item["id"] == "vpn.client_status")
        self.assertEqual(device_block["requires_confirmation"], "--yes")
        self.assertEqual(device_vpn["status"], "firmware_error")
        self.assertEqual(led_status["status"], "live_verified")
        self.assertEqual(vpn_client_status["status"], "firmware_error")
        self.assertIn("--json", data["agent_contract"]["prefer"])

    def test_tools_reports_agent_tool_schemas(self):
        output = run_cli(["--json", "tools"])
        data = json.loads(output)
        tool_names = {item["name"] for item in data["tools"]}
        self.assertIn("router_status", tool_names)
        self.assertIn("device_plan", tool_names)
        self.assertEqual(data["transport"], "local-cli")

    def test_device_block_plan_does_not_mutate(self):
        output = run_cli(["--json", "--no-input", "device", "block", "debian", "--plan", "--enforce"])
        data = json.loads(output)
        self.assertTrue(data["plan"])
        self.assertFalse(data["will_mutate"])
        self.assertEqual(data["action"], "device.block")
        self.assertEqual(data["target"]["mac"], "48-BA-4E-40-B4-F4")
        self.assertIn("--enforce", data["command"])
        self.assertIn("device_connectivity_loss", data["risk"])

    def test_device_admin_profile_allows_device_plan_and_blocks_wifi(self):
        output = run_cli(["--json", "--profile", "device-admin", "--no-input", "device", "reserve", "debian", "--plan"])
        data = json.loads(output)
        self.assertEqual(data["action"], "device.reserve")
        with self.assertRaises(SystemExit) as raised:
            run_cli(["--profile", "device-admin", "wifi", "guest_2g", "on"])
        self.assertIn("profile", str(raised.exception))

    def test_read_only_profile_blocks_device_mutation(self):
        output = run_cli(["--json", "--profile", "read-only", "--no-input", "device", "debian"])
        data = json.loads(output)
        self.assertEqual(data["hostname"], "debian_linux")
        with self.assertRaises(SystemExit) as raised:
            run_cli(["--profile", "read-only", "--no-input", "device", "block", "debian", "--plan"])
        self.assertIn("blocked", str(raised.exception))

    def test_watch_collects_read_only_samples(self):
        output = run_cli(["--json", "--no-input", "watch", "devices", "--count", "1", "--active"])
        data = json.loads(output)
        self.assertEqual(data[0]["target"], "devices")
        self.assertEqual(data[0]["sequence"], 1)
        self.assertEqual(data[0]["data"][0]["hostname"], "debian_linux")

    def test_demo_offline_reports_agent_workflow(self):
        output = run_cli(["--json", "demo"])
        data = json.loads(output)
        self.assertFalse(data["live"])
        self.assertIn("tplinkctl-mcp", data["summary"]["mcp_server"])
        self.assertIn("device_plan", data["tool_names"])
        self.assertIn("examples/agent-runbook.md", data["docs"])

    def test_demo_live_includes_read_only_plan(self):
        output = run_cli(["--json", "--no-input", "demo", "--live", "--device", "debian"])
        data = json.loads(output)
        self.assertTrue(data["live"])
        self.assertEqual(data["live_checks"]["device_plan"]["action"], "device.block")
        self.assertFalse(data["live_checks"]["device_plan"]["will_mutate"])
        self.assertEqual(data["live_checks"]["device_plan"]["target"]["hostname"], "debian_linux")

    def test_device_plan_writes_audit_event_with_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = run_cli_in_config(
                tmp,
                ["--json", "--reason", "testing audit", "--no-input", "device", "block", "debian", "--plan"],
            )
            plan = json.loads(output)
            self.assertEqual(plan["action"], "device.block")
            events = json.loads(run_cli_in_config(tmp, ["--json", "events", "--tail", "5"]))
        self.assertEqual(events["count"], 1)
        self.assertEqual(events["events"][0]["event"], "plan")
        self.assertEqual(events["events"][0]["operation"], "device.block")
        self.assertEqual(events["events"][0]["reason"], "testing audit")

    def test_state_save_show_and_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            saved_one = json.loads(run_cli_in_config(tmp, ["--json", "--no-input", "state", "save", "--name", "one"]))
            saved_two = json.loads(run_cli_in_config(tmp, ["--json", "--no-input", "state", "save", "--name", "two"]))
            shown = json.loads(run_cli_in_config(tmp, ["--json", "state", "show", "one"]))
            # Default diff filters rate/counter/timestamp noise, so two identical
            # saves should report zero changes. Verify with --raw that they still
            # differ (proves snapshots aren't being deduped).
            filtered = json.loads(run_cli_in_config(tmp, ["--json", "state", "diff", "--before", "one", "--after", "two"]))
            raw = json.loads(run_cli_in_config(tmp, ["--json", "state", "diff", "--before", "one", "--after", "two", "--raw"]))
        self.assertTrue(saved_one["saved"].endswith("one.json"))
        self.assertTrue(saved_two["saved"].endswith("two.json"))
        self.assertEqual(shown["snapshot_name"], "one")
        self.assertEqual(filtered["before"], "one")
        self.assertEqual(filtered["after"], "two")
        # Default should be clean (noise filtered) while raw still shows some change.
        self.assertEqual(filtered["change_count"], 0)
        self.assertGreaterEqual(raw["change_count"], 1)

    def test_state_diff_filters_transient_fields_by_default(self):
        before = {
            "generated_at": "2026-07-20T13:55:18.996751+00:00",
            "health": {"summary": {"cpu_usage": 0.14, "mem_usage": 0.48, "wan_uptime_seconds": 385189}},
            "devices": [
                {"hostname": "Pixel", "online_seconds": 100, "packets_received": 1000, "down_Bps": 50},
            ],
            "wifi": {"enabled": True},
        }
        after = {
            "generated_at": "2026-07-20T13:56:00.000000+00:00",
            "health": {"summary": {"cpu_usage": 0.28, "mem_usage": 0.51, "wan_uptime_seconds": 385249}},
            "devices": [
                {"hostname": "Pixel", "online_seconds": 142, "packets_received": 1500, "down_Bps": 90},
            ],
            "wifi": {"enabled": True},
        }
        changes = cli.diff_values(before, after)
        # Only structural noise changes; wifi.enabled didn't change, so zero real diffs.
        self.assertEqual(changes, [])

    def test_state_diff_raw_keeps_every_change(self):
        before = {"generated_at": "a", "value": 1}
        after = {"generated_at": "b", "value": 2}
        changes = cli.diff_values(before, after, ignore_leaves=frozenset())
        paths = {c["path"] for c in changes}
        self.assertIn("generated_at", paths)
        self.assertIn("value", paths)

    def test_state_diff_only_prefix_restricts_scope(self):
        before = {"wifi": {"enabled": True, "channel": 10}, "health": {"ok": True}}
        after = {"wifi": {"enabled": False, "channel": 10}, "health": {"ok": False}}
        changes = cli.diff_values(before, after, only_prefix="wifi")
        paths = {c["path"] for c in changes}
        self.assertIn("wifi.enabled", paths)
        self.assertNotIn("health.ok", paths)

    def test_state_diff_extra_ignore_prefixes(self):
        before = {
            "devices": [
                {"hostname": "a", "active": True},
                {"hostname": "b", "active": False},
            ],
        }
        after = {
            "devices": [
                {"hostname": "a-renamed", "active": True},
                {"hostname": "b", "active": True},
            ],
        }
        # Default ignore set doesn't include hostname/active; expect both to show up.
        all_changes = cli.diff_values(before, after)
        paths = sorted({c["path"] for c in all_changes})
        self.assertEqual(paths, ["devices[0].hostname", "devices[1].active"])
        # With extra ignore on first device, only the second's `active` flips remain.
        filtered = cli.diff_values(before, after, ignore_prefixes=("devices[0]",))
        self.assertEqual(len(filtered), 1)
        self.assertIn("devices[1].active", filtered[0]["path"])

    def test_state_diff_default_returns_empty_on_identical_snapshots(self):
        snap = {
            "generated_at": "2026-07-20T13:55:18+00:00",
            "health": {"summary": {"cpu_usage": 0.5, "mem_usage": 0.5}},
            "devices": [
                {"hostname": "Pixel", "online_seconds": 100, "down_Bps": 50},
            ],
        }
        changes = cli.diff_values(snap, snap)
        self.assertEqual(changes, [])

    def test_state_diff_structural_change_surfaces(self):
        before = {"wifi": {"enabled": True, "channel": 10, "ssid": "ps"}}
        after = {"wifi": {"enabled": True, "channel": 36, "ssid": "ps"}}
        changes = cli.diff_values(before, after)
        paths = {c["path"] for c in changes}
        self.assertEqual(paths, {"wifi.channel"})

    def test_state_diff_only_matches_list_index_paths(self):
        # Regression: --only devices must match devices[0].hostname, not just
        # devices.* (which silently drops list-element diffs).
        before = {"devices": [{"hostname": "a"}], "wifi": {"enabled": True}}
        after = {"devices": [{"hostname": "b"}], "wifi": {"enabled": False}}
        changes = cli.diff_values(before, after, only_prefix="devices")
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["path"], "devices[0].hostname")

    def test_state_diff_ignore_prefix_suppresses_whole_list(self):
        before = {"devices": [{"hostname": "a"}]}
        after = {"devices": [{"hostname": "b"}]}
        changes = cli.diff_values(before, after, ignore_prefixes=("devices",))
        self.assertEqual(changes, [])

    def test_state_diff_list_length_change_shows_added_element(self):
        before = {"devices": [{"hostname": "a"}]}
        after = {"devices": [{"hostname": "a"}, {"hostname": "b"}]}
        changes = cli.diff_values(before, after)
        added = [c for c in changes if c["type"] == "added"]
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0]["path"], "devices[1]")
        self.assertEqual(added[0]["after"], {"hostname": "b"})

    def test_state_diff_noise_leaf_added_still_surfaces(self):
        # A dict-add for a normally-ignored leaf (e.g. signal_dbm appearing on
        # a device that didn't have one) must still be reported. Otherwise
        # intentional additions inside noisy fields are silently hidden.
        before = {"devices": [{"hostname": "x"}]}
        after = {"devices": [{"hostname": "x", "signal_dbm": -30}]}
        changes = cli.diff_values(before, after)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["path"], "devices[0].signal_dbm")
        self.assertEqual(changes[0]["type"], "added")

    def test_state_diff_noise_leaf_removed_still_surfaces(self):
        before = {"devices": [{"hostname": "x", "signal_dbm": -30}]}
        after = {"devices": [{"hostname": "x"}]}
        changes = cli.diff_values(before, after)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["path"], "devices[0].signal_dbm")
        self.assertEqual(changes[0]["type"], "removed")

    def test_state_diff_noise_leaf_value_change_still_filtered(self):
        # When both sides have the noise leaf and it just changes value, the
        # default filter still drops it. Intentional changes use --raw or
        # remove the leaf from the ignore set.
        before = {"devices": [{"hostname": "x", "signal_dbm": -50}]}
        after = {"devices": [{"hostname": "x", "signal_dbm": -30}]}
        changes = cli.diff_values(before, after)
        self.assertEqual(changes, [])

    def test_state_diff_filters_derived_usage_sibling(self):
        before = {"devices": [{"hostname": "mac", "usage_bytes": 2048, "usage": "2.0 KB"}]}
        after = {"devices": [{"hostname": "mac", "usage_bytes": 4096, "usage": "4.0 KB"}]}
        self.assertEqual(cli.diff_values(before, after), [])

    def test_state_diff_matches_devices_by_mac_on_reorder(self):
        before = {
            "devices": [
                {"mac": "aa", "hostname": "A"},
                {"mac": "bb", "hostname": "B"},
                {"mac": "cc", "hostname": "C"},
            ]
        }
        after = {
            "devices": [
                {"mac": "cc", "hostname": "C"},
                {"mac": "aa", "hostname": "A"},
                {"mac": "bb", "hostname": "B"},
            ]
        }
        self.assertEqual(cli.diff_values(before, after), [])

    def test_state_diff_mac_drop_attributes_the_removed_device(self):
        before = {
            "devices": [
                {"mac": "aa", "hostname": "A"},
                {"mac": "bb", "hostname": "B"},
                {"mac": "cc", "hostname": "C"},
            ]
        }
        after = {
            "devices": [
                {"mac": "bb", "hostname": "B"},
                {"mac": "cc", "hostname": "C"},
            ]
        }
        changes = cli.diff_values(before, after)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["type"], "removed")
        self.assertEqual(changes[0]["before"]["hostname"], "A")

    def test_state_diff_bare_ignore_leaf_filters_nested_path(self):
        before = {"devices": [{"hostname": "x", "foo": 1}]}
        after = {"devices": [{"hostname": "x", "foo": 2}]}
        leaves, prefixes = cli.split_ignore_args(["foo"])
        self.assertEqual(prefixes, ())
        changes = cli.diff_values(before, after, ignore_leaves=leaves, ignore_prefixes=prefixes)
        self.assertEqual(changes, [])

    def test_state_diff_only_walks_into_added_parent(self):
        before = {}
        after = {"wifi": {"enabled": True, "channel": 36}}
        changes = cli.diff_values(before, after, only_prefix="wifi.enabled")
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["path"], "wifi.enabled")
        self.assertEqual(changes[0]["type"], "added")

    def test_state_diff_only_walks_into_added_list_item(self):
        before = {"devices": []}
        after = {"devices": [{"mac": "aa", "hostname": "A"}]}
        changes = cli.diff_values(before, after, only_prefix="devices[0].hostname")
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["path"], "devices[0].hostname")
        self.assertEqual(changes[0]["type"], "added")

    def test_state_diff_ignore_suppresses_added_or_removed_field(self):
        before = {"a": 1}
        after = {"a": 1, "foo": 2}
        changes = cli.diff_values(before, after, ignore_prefixes=("foo",))
        self.assertEqual(changes, [])

    def test_state_diff_ignore_top_level_section(self):
        before = {"devices": [{"hostname": "a"}]}
        after = {"devices": [{"hostname": "b"}]}
        changes = cli.diff_values(before, after, ignore_prefixes=("devices",))
        self.assertEqual(changes, [])

    def test_state_diff_cli_ignore_leaf_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "tplink-admin" / "state"
            state.mkdir(parents=True)
            (state / "a.json").write_text(json.dumps({"devices": [{"hostname": "x", "foo": 1}]}), encoding="utf-8")
            (state / "b.json").write_text(json.dumps({"devices": [{"hostname": "x", "foo": 2}]}), encoding="utf-8")
            data = json.loads(
                run_cli_in_config(tmp, ["--json", "state", "diff", "--before", "a", "--after", "b", "--ignore", "foo"])
            )
        self.assertEqual(data["change_count"], 0)
        self.assertIn("foo", data["ignored_leaves"])

    def test_state_diff_cli_default_suppresses_noise(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_cli_in_config(tmp, ["--json", "--no-input", "state", "save", "--name", "a"])
            run_cli_in_config(tmp, ["--json", "--no-input", "state", "save", "--name", "b"])
            filtered = json.loads(run_cli_in_config(tmp, ["--json", "state", "diff", "--before", "a", "--after", "b"]))
            raw = json.loads(run_cli_in_config(tmp, ["--json", "state", "diff", "--before", "a", "--after", "b", "--raw"]))
        # Raw diff has rate/timestamp noise; default diff should drop to zero (or near-zero)
        # because the fake router returns identical data between snapshots.
        self.assertGreaterEqual(raw["change_count"], filtered["change_count"])
        # Default explicitly reports what it ignored.
        self.assertGreater(len(filtered["ignored_leaves"]), 0)
        self.assertFalse(filtered["raw"])

    def test_deep_doctor_runs_read_only_probes(self):
        out = io.StringIO()
        with (
            tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(out),
            patch.dict("os.environ", {"XDG_CONFIG_HOME": tmp}, clear=False),
            patch.object(cli.requests, "get", return_value=FakeResponse()),
            patch.object(cli, "build_router", return_value=FakeRouter()),
        ):
            cli.main(["--json", "--no-input", "doctor", "--deep"])
        data = json.loads(out.getvalue())
        probe_ids = {probe["id"] for probe in data["probes"]}
        self.assertTrue(data["deep"])
        self.assertTrue(data["ok"])
        self.assertEqual(data["router"]["model"], "Archer BE3500")
        self.assertIn("device.access", probe_ids)
        self.assertIn("vpn.user_list", probe_ids)
        quirk_ids = {q["id"]: q["applies_to"] for q in data.get("known_quirks", [])}
        self.assertIn("vpn-user-list-dispatcher-error", quirk_ids)
        self.assertIn("Archer BE3500 firmware 1.3.3 Build 20260618", quirk_ids["vpn-user-list-dispatcher-error"])

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

    def test_port_forward_lists_rules(self):
        output = run_cli(["--json", "--no-input", "port-forward"])
        data = json.loads(output)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["name"], "NPM-HTTPS")
        self.assertEqual(data[0]["external_port"], "443")
        self.assertEqual(data[0]["internal_port"], "8443")

    def test_ports_reports_link_speed_and_supported(self):
        output = run_cli(["--json", "--no-input", "ports"])
        data = json.loads(output)
        self.assertEqual(data["speed"], "1000F")
        self.assertIn("auto", data["supported"])
        self.assertIn("1000F", data["supported"])

    def test_ipv6_reports_wan_and_lan(self):
        output = run_cli(["--json", "--no-input", "ipv6"])
        data = json.loads(output)
        self.assertTrue(data["wan"]["enabled"])
        self.assertEqual(data["wan"]["connection_type"], "dhcpv6")
        self.assertEqual(data["lan"]["assign_type"], "slaac")
        self.assertIn("6a7f", data["lan"]["address"].lower())

    def test_mesh_reports_nodes(self):
        output = run_cli(["--json", "--no-input", "mesh"])
        data = json.loads(output)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["role"], "main_router")
        self.assertEqual(data[0]["name"], "Archer BE3500")
        self.assertEqual(data[0]["client_num"], 4)

    def test_wireguard_reports_config_and_preserves_public_key(self):
        output = run_cli(["--json", "--no-input", "wireguard"])
        data = json.loads(output)
        self.assertTrue(data["enabled"])
        self.assertEqual(data["listen_port"], 51820)
        self.assertEqual(data["address"], "10.5.5.1/32")
        self.assertTrue(data["public_key"].startswith("agvcmR"))
        self.assertNotIn("private_key", data)

    def test_nat_reports_upnp_dmz_and_alg(self):
        output = run_cli(["--json", "--no-input", "nat"])
        data = json.loads(output)
        self.assertTrue(data["upnp"])
        self.assertFalse(data["dmz"]["enabled"])
        self.assertTrue(data["alg_passthrough"]["sip"])

    def test_qos_reports_bandwidth_and_splits(self):
        output = run_cli(["--json", "--no-input", "qos"])
        data = json.loads(output)
        self.assertTrue(data["enabled"])
        self.assertEqual(data["up_bandwidth_mbps"], 1000.0)
        self.assertEqual(data["down_bandwidth_mbps"], 1000.0)
        self.assertEqual(data["priorities"]["high_percent"], 90.0)

    def test_storage_reports_shares_and_time_machine(self):
        output = run_cli(["--json", "--no-input", "storage"])
        data = json.loads(output)
        self.assertEqual(data["server_name"], "TP-Share")
        self.assertEqual(len(data["shares"]), 2)
        self.assertEqual(data["shares"][0]["protocol"], "samba")
        self.assertFalse(data["time_machine"]["enabled"])

    def test_time_reports_system_time_and_ntp(self):
        output = run_cli(["--json", "--no-input", "time"])
        data = json.loads(output)
        self.assertEqual(data["date"], "08/14/2026")
        self.assertIn("us.pool.ntp.org", data["ntp_servers"])
        self.assertFalse(data["hour24_enabled"])

    def test_wifi_advanced_reports_radio_features(self):
        output = run_cli(["--json", "--no-input", "wifi-advanced"])
        data = json.loads(output)
        self.assertTrue(data["smart_connect"])
        self.assertFalse(data["ofdma"])
        self.assertFalse(data["twt"])
        self.assertEqual(data["ofdma_mimo_setting"], "all")
        self.assertTrue(data["radio"]["zerowait_dfs"])
        self.assertEqual(data["radio"]["beacon_interval"], "100")
        self.assertEqual(data["country"], "US")
        widths = {item["width_mhz"] for item in data["channels_5g"]}
        self.assertIn(160, widths)

    def test_ddns_reports_provider(self):
        output = run_cli(["--json", "--no-input", "ddns"])
        data = json.loads(output)
        self.assertEqual(data["provider"], "tp-link")

    def test_iptv_reports_vlan_and_ports(self):
        output = run_cli(["--json", "--no-input", "iptv"])
        data = json.loads(output)
        self.assertFalse(data["enabled"])
        self.assertEqual(data["mode"], "Bridge")
        self.assertTrue(data["igmp_snooping"])
        port_types = {p["port"]: p["type"] for p in data["port_settings"]}
        self.assertEqual(port_types["lan3"], "IPTV")

    def test_power_reports_eco_mode(self):
        output = run_cli(["--json", "--no-input", "power"])
        data = json.loads(output)
        self.assertFalse(data["eco_enabled"])
        self.assertEqual(data["power_mode"], "balanced")
        self.assertTrue(data["smart_eco"])

    def test_schema_emits_clispec_v0_2_contract(self):
        output = run_cli(["schema"])
        data = json.loads(output)
        self.assertEqual(data["clispec"], "0.2")
        self.assertEqual(data["name"], "tplinkctl")
        self.assertEqual(data["command_layout"], "flat")
        names = {item["name"] for item in data["commands"]}
        self.assertIn("schema", names)
        self.assertIn("status", names)
        self.assertIn("device block", names)
        kinds = {item["kind"] for item in data["errors"]}
        self.assertEqual(kinds, set(cli.ERROR_CATALOG))
        device_block = next(item for item in data["commands"] if item["name"] == "device block")
        self.assertTrue(device_block["mutating"])
        status = next(item for item in data["commands"] if item["name"] == "status")
        self.assertFalse(status["mutating"])

    def test_schema_can_narrow_to_a_command_path(self):
        output = run_cli(["schema", "device"])
        data = json.loads(output)
        names = {item["name"] for item in data["commands"]}
        self.assertTrue(names)
        self.assertTrue(all(name == "device" or name.startswith("device ") for name in names))
        self.assertNotIn("status", names)

    def test_dry_run_is_an_alias_for_plan(self):
        output = run_cli(["--json", "--no-input", "device", "block", "debian", "--dry-run"])
        data = json.loads(output)
        self.assertTrue(data["plan"])
        self.assertEqual(data["action"], "device.block")

    def test_run_emits_structured_error_and_semantic_exit_code(self):
        err = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {"XDG_CONFIG_HOME": tmp}, clear=False):
            with contextlib.redirect_stderr(err):
                code = cli.run(["--disable-commands", "status", "status"])
        self.assertEqual(code, 4)
        envelope = json.loads(err.getvalue().strip().splitlines()[-1])
        self.assertEqual(envelope["error"]["kind"], "permission")

    def test_run_uses_confirmation_required_exit_code(self):
        err = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {"XDG_CONFIG_HOME": tmp}, clear=False), patch.object(cli, "build_router", return_value=FakeRouter()):
            with contextlib.redirect_stderr(err):
                code = cli.run(["--json", "--no-input", "device", "reserve", "debian"])
        self.assertEqual(code, 5)
        envelope = json.loads(err.getvalue().strip().splitlines()[-1])
        self.assertEqual(envelope["error"]["kind"], "confirmation_required")


if __name__ == "__main__":
    unittest.main()
