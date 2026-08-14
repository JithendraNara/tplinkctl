import contextlib
import io
import json
import tempfile
import unittest
from unittest.mock import patch

from test_cli import FakeRouter

from tplink_admin import cli, mcp


def call_tool_with_fake_router(name, arguments=None):
    with tempfile.TemporaryDirectory() as tmp:
        with (
            patch.dict("os.environ", {"XDG_CONFIG_HOME": tmp}, clear=False),
            patch.object(cli, "build_router", return_value=FakeRouter()),
        ):
            return mcp.call_tool(name, arguments or {})


def call_tool_in_config(tmp, name, arguments=None):
    with (
        patch.dict("os.environ", {"XDG_CONFIG_HOME": tmp}, clear=False),
        patch.object(cli, "build_router", return_value=FakeRouter()),
    ):
        return mcp.call_tool(name, arguments or {})


class McpTests(unittest.TestCase):
    def test_initialize_response(self):
        response = mcp.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        self.assertEqual(response["result"]["serverInfo"]["name"], "tplinkctl-mcp")
        self.assertIn("tools", response["result"]["capabilities"])

    def test_tools_list_contains_router_tools(self):
        response = mcp.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = {tool["name"] for tool in response["result"]["tools"]}
        self.assertIn("router_status", names)
        self.assertIn("firmware_audit", names)
        self.assertIn("led_status", names)
        self.assertIn("led_plan", names)
        self.assertIn("led_set", names)
        self.assertIn("device_plan", names)
        self.assertIn("port_forward_list", names)
        self.assertIn("port_speed", names)
        self.assertIn("ipv6_status", names)
        self.assertIn("mesh_devices", names)
        self.assertIn("wireguard_status", names)
        self.assertIn("nat_status", names)
        self.assertIn("qos_status", names)
        self.assertIn("storage_status", names)
        self.assertIn("time_status", names)
        self.assertIn("power_status", names)
        self.assertIn("wifi_advanced", names)
        self.assertIn("ddns_status", names)
        self.assertIn("iptv_status", names)
        self.assertIn("watch", names)
        self.assertIn("audit_tail", names)
        self.assertIn("state_snapshot", names)

    def test_device_show_tool_uses_cli_json(self):
        result = call_tool_with_fake_router("device_show", {"query": "debian"})
        payload = json.loads(result["content"][0]["text"])
        self.assertFalse(result["isError"])
        self.assertEqual(payload["hostname"], "debian_linux")

    def test_firmware_audit_tool_is_read_only(self):
        result = call_tool_with_fake_router("firmware_audit")
        payload = json.loads(result["content"][0]["text"])
        self.assertFalse(result["isError"])
        self.assertTrue(payload["update"]["available"])
        self.assertFalse(payload["action_taken"])

    def test_device_plan_tool_does_not_mutate(self):
        result = call_tool_with_fake_router("device_plan", {"action": "block", "query": "debian", "enforce": True})
        payload = json.loads(result["content"][0]["text"])
        self.assertTrue(payload["plan"])
        self.assertFalse(payload["will_mutate"])
        self.assertEqual(payload["action"], "device.block")

    def test_mutation_tool_requires_confirmation(self):
        response = mcp.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "device_block", "arguments": {"query": "debian"}},
            }
        )
        self.assertTrue(response["result"]["isError"])
        self.assertIn("confirm=true", response["result"]["content"][0]["text"])

    def test_led_tools_plan_and_require_confirmation(self):
        status = call_tool_with_fake_router("led_status")
        self.assertTrue(json.loads(status["content"][0]["text"])["enabled"])

        plan = call_tool_with_fake_router(
            "led_plan",
            {"action": "schedule", "enabled": True, "start": "22:00", "end": "06:00"},
        )
        self.assertTrue(json.loads(plan["content"][0]["text"])["plan"])

        response = mcp.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {"name": "led_set", "arguments": {"action": "off"}},
            }
        )
        self.assertTrue(response["result"]["isError"])
        self.assertIn("confirm=true", response["result"]["content"][0]["text"])

    def test_wifi_config_tools_plan_and_require_confirmation(self):
        plan = call_tool_with_fake_router(
            "wifi_config_plan",
            {"connection": "host_5g", "channel": "149", "width": "80"},
        )
        payload = json.loads(plan["content"][0]["text"])
        self.assertTrue(payload["plan"])
        self.assertEqual(payload["action"], "wifi-config")

        response = mcp.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {"name": "wifi_config", "arguments": {"connection": "host_5g", "channel": "149"}},
            }
        )
        self.assertIsNotNone(response)
        assert response is not None
        self.assertTrue(response["result"]["isError"])
        self.assertIn("confirm=true", response["result"]["content"][0]["text"])

    def test_framed_stdio_round_trip(self):
        message = json.dumps({"jsonrpc": "2.0", "id": 4, "method": "tools/list"})
        raw = f"Content-Length: {len(message.encode('utf-8'))}\r\n\r\n{message}".encode()
        output = io.StringIO()
        with contextlib.redirect_stderr(io.StringIO()):
            mcp.serve(io.BytesIO(raw), output)
        written = output.getvalue()
        self.assertTrue(written.startswith("Content-Length:"))
        body = written.split("\r\n\r\n", 1)[1]
        response = json.loads(body)
        self.assertEqual(response["id"], 4)
        self.assertIn("tools", response["result"])

    def test_audit_tail_tool_reads_cli_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            call_tool_in_config(tmp, "device_plan", {"action": "block", "query": "debian"})
            result = call_tool_in_config(tmp, "audit_tail", {"tail": 5})
        payload = json.loads(result["content"][0]["text"])
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["events"][0]["operation"], "device.block")

    def test_state_snapshot_and_diff_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = call_tool_in_config(tmp, "state_snapshot", {"name": "first"})
            second = call_tool_in_config(tmp, "state_snapshot", {"name": "second"})
            diff = call_tool_in_config(tmp, "state_diff", {"before": "first", "after": "second"})
        first_payload = json.loads(first["content"][0]["text"])
        second_payload = json.loads(second["content"][0]["text"])
        diff_payload = json.loads(diff["content"][0]["text"])
        self.assertTrue(first_payload["saved"].endswith("first.json"))
        self.assertTrue(second_payload["saved"].endswith("second.json"))
        self.assertEqual(diff_payload["before"], "first")
        self.assertEqual(diff_payload["after"], "second")

    def test_state_diff_argv_exposes_raw_only_ignore(self):
        argv = mcp.argv_state_diff(
            {"before": "a", "after": "b", "raw": True, "only": "wifi", "ignore": ["signal_dbm", "devices[0]"]}
        )
        self.assertIn("--raw", argv)
        self.assertEqual(argv[argv.index("--only") + 1], "wifi")
        self.assertIn("signal_dbm", argv)
        self.assertIn("devices[0]", argv)

    def test_new_read_only_mcp_tools(self):
        pf = call_tool_with_fake_router("port_forward_list")
        self.assertFalse(pf["isError"])
        self.assertEqual(json.loads(pf["content"][0]["text"])[0]["name"], "NPM-HTTPS")

        ps = call_tool_with_fake_router("port_speed")
        self.assertFalse(ps["isError"])
        self.assertEqual(json.loads(ps["content"][0]["text"])["speed"], "1000F")

        ip6 = call_tool_with_fake_router("ipv6_status")
        self.assertFalse(ip6["isError"])
        self.assertTrue(json.loads(ip6["content"][0]["text"])["wan"]["enabled"])

        mesh = call_tool_with_fake_router("mesh_devices")
        self.assertFalse(mesh["isError"])
        self.assertEqual(json.loads(mesh["content"][0]["text"])[0]["role"], "main_router")

        wg = call_tool_with_fake_router("wireguard_status")
        self.assertFalse(wg["isError"])
        self.assertTrue(json.loads(wg["content"][0]["text"])["enabled"])

        nat = call_tool_with_fake_router("nat_status")
        self.assertFalse(nat["isError"])
        self.assertTrue(json.loads(nat["content"][0]["text"])["upnp"])

        qos = call_tool_with_fake_router("qos_status")
        self.assertFalse(qos["isError"])
        self.assertTrue(json.loads(qos["content"][0]["text"])["enabled"])

        storage = call_tool_with_fake_router("storage_status")
        self.assertFalse(storage["isError"])
        self.assertEqual(json.loads(storage["content"][0]["text"])["server_name"], "TP-Share")

        time_res = call_tool_with_fake_router("time_status")
        self.assertFalse(time_res["isError"])
        self.assertEqual(json.loads(time_res["content"][0]["text"])["date"], "08/14/2026")

        power = call_tool_with_fake_router("power_status")
        self.assertFalse(power["isError"])
        self.assertEqual(json.loads(power["content"][0]["text"])["power_mode"], "balanced")

        wadv = call_tool_with_fake_router("wifi_advanced")
        self.assertFalse(wadv["isError"])
        self.assertTrue(json.loads(wadv["content"][0]["text"])["smart_connect"])

        ddns = call_tool_with_fake_router("ddns_status")
        self.assertFalse(ddns["isError"])
        self.assertEqual(json.loads(ddns["content"][0]["text"])["provider"], "tp-link")

        iptv = call_tool_with_fake_router("iptv_status")
        self.assertFalse(iptv["isError"])
        self.assertEqual(json.loads(iptv["content"][0]["text"])["mode"], "Bridge")


if __name__ == "__main__":
    unittest.main()
