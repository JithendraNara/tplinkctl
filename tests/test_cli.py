import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
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
        if path == "admin/wireless?form=smart_connect":
            return {"smart_enable": "on"}
        if "wireless_2g" in path:
            return {
                "wireless_2g_enable": "on",
                "wireless_2g_ssid": "lab",
                "wireless_2g_current_channel": "3",
                "wireless_2g_psk_key": "secret",
            }
        if "guest_2g" in path:
            return {"guest_2g_enable": "off", "guest_2g_ssid": "lab_guest"}
        if "iot_2g" in path:
            return {"iot_2g_enable": "on", "iot_2g_ssid": "lab_iot"}
        return {}

    def set_vpn_client_device(self, mac, enable):
        self.vpn_devices.append((mac, enable))


def run_cli(argv):
    out = io.StringIO()
    with tempfile.TemporaryDirectory() as tmp:
        with (
            contextlib.redirect_stdout(out),
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
            diff = json.loads(run_cli_in_config(tmp, ["--json", "state", "diff", "--before", "one", "--after", "two"]))
        self.assertTrue(saved_one["saved"].endswith("one.json"))
        self.assertTrue(saved_two["saved"].endswith("two.json"))
        self.assertEqual(shown["snapshot_name"], "one")
        self.assertEqual(diff["before"], "one")
        self.assertEqual(diff["after"], "two")
        self.assertGreaterEqual(diff["change_count"], 1)

    def test_deep_doctor_runs_read_only_probes(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            with (
                contextlib.redirect_stdout(out),
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
