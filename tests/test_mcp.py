import contextlib
import io
import json
import tempfile
import unittest
from unittest.mock import patch

from test_cli import FakeRouter, PROFILE_SCRUB

from tplink_admin import cli, mcp


# Tool-behavior tests run under an explicit profile that permits every tool;
# the read-only default is asserted separately in test_default_profile_is_read_only.
ADMIN = {**PROFILE_SCRUB, "TPLINK_MCP_PROFILE": "network-admin"}


def call_tool_with_fake_router(name, arguments=None, env=ADMIN, version=mcp.PROTOCOL_VERSION):
    with tempfile.TemporaryDirectory() as tmp:
        with (
            patch.dict("os.environ", {"XDG_CONFIG_HOME": tmp, **env}, clear=False),
            patch.object(cli, "build_router", return_value=FakeRouter()),
        ):
            return mcp.call_tool(name, arguments or {}, version)


def call_tool_in_config(tmp, name, arguments=None):
    with (
        patch.dict("os.environ", {"XDG_CONFIG_HOME": tmp, **ADMIN}, clear=False),
        patch.object(cli, "build_router", return_value=FakeRouter()),
    ):
        return mcp.call_tool(name, arguments or {})


def stdio(*lines):
    """Drive the real stdio loop; return parsed output messages in order."""
    raw = "".join(line if isinstance(line, str) else json.dumps(line) + "\n" for line in lines)
    output = io.StringIO()
    with contextlib.redirect_stderr(io.StringIO()):
        mcp.serve(io.BytesIO(raw.encode()), output)
    return [json.loads(line) for line in output.getvalue().splitlines()]


def init(version="2025-11-25", rid=1):
    return {"jsonrpc": "2.0", "id": rid, "method": "initialize",
            "params": {"protocolVersion": version, "capabilities": {},
                       "clientInfo": {"name": "test", "version": "0"}}}


def req(rid, method, params=None):
    message = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        message["params"] = params
    return message


class McpTests(unittest.TestCase):
    def test_initialize_response(self):
        response = mcp.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        self.assertEqual(response["result"]["serverInfo"]["name"], "tplinkctl-mcp")
        self.assertIn("tools", response["result"]["capabilities"])

    def test_protocol_version_negotiation(self):
        # Supported client versions are echoed; missing means latest supported;
        # anything else gets the latest supported version (#17 follow-up).
        for requested in mcp.SUPPORTED_PROTOCOL_VERSIONS:
            response = mcp.handle_request(
                {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"protocolVersion": requested}})
            self.assertEqual(response["result"]["protocolVersion"], requested)
        response = mcp.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        self.assertEqual(response["result"]["protocolVersion"], mcp.PROTOCOL_VERSION)
        # Lifecycle MUST: an unsupported request gets another version the server
        # supports (the latest), not an error; the client decides to disconnect.
        for unsupported in ("1999-01-01", "2026-07-28", 20251125):
            response = mcp.handle_request(
                {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"protocolVersion": unsupported}})
            self.assertEqual(response["result"]["protocolVersion"], mcp.PROTOCOL_VERSION)

    def test_initialize_includes_instructions_and_honest_capabilities(self):
        response = mcp.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        instructions = response["result"]["instructions"]
        self.assertIn("confirm=true", instructions)
        self.assertIn("plan", instructions.lower())
        self.assertFalse(response["result"]["capabilities"]["tools"]["listChanged"])

    def test_notifications_are_never_answered(self):
        # JSON-RPC notifications (no id) must be consumed silently, any method.
        for method in ("notifications/initialized", "notifications/cancelled",
                       "notifications/anything"):
            self.assertIsNone(mcp.handle_request({"jsonrpc": "2.0", "method": method}))

    def test_tools_list_advertises_output_schema_and_annotations(self):
        response = mcp.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        manifest = {t["name"]: t for t in cli.tool_manifest()["tools"]}
        for tool in response["result"]["tools"]:
            self.assertEqual(tool["outputSchema"], mcp.mcp_output_schema(manifest[tool["name"]]))
            # MCP requires object output schemas through 2025-11-25, even for
            # registry tools whose CLI payload is a top-level array.
            self.assertEqual(tool["outputSchema"]["type"], "object")
            annotations = tool["annotations"]
            self.assertFalse(annotations["openWorldHint"])  # one local router
            item = manifest[tool["name"]]
            if tool["name"] == "state_snapshot":
                # Writes a snapshot file: additive, not read-only, not idempotent.
                self.assertEqual(annotations, {"readOnlyHint": False, "destructiveHint": False,
                                               "idempotentHint": False, "openWorldHint": False})
            elif item["read_only"]:
                # destructive/idempotent are only meaningful when readOnlyHint is false.
                self.assertEqual(annotations, {"readOnlyHint": True, "openWorldHint": False})
            else:
                # Router mutations overwrite or delete state and are set-to-value.
                self.assertTrue(annotations["destructiveHint"], tool["name"])
                self.assertTrue(annotations["idempotentHint"], tool["name"])

    def test_tools_list_pagination_walks_full_ordered_catalog(self):
        with patch.dict("os.environ", {"TPLINK_MCP_PAGE_SIZE": "2"}):
            seen, cursor = [], None
            while True:
                params = {} if cursor is None else {"cursor": cursor}
                response = mcp.handle_request(
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": params})
                seen.extend(t["name"] for t in response["result"]["tools"])
                cursor = response["result"].get("nextCursor")
                if cursor is None:
                    break
        full = mcp.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertEqual(seen, [t["name"] for t in full["result"]["tools"]])
        bad = mcp.handle_request(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {"cursor": "bogus"}})
        self.assertEqual(bad["error"]["code"], -32602)

    def test_structured_content_matches_text_and_output_schema(self):
        from jsonschema import Draft202012Validator
        result = call_tool_with_fake_router("device_show", {"query": "fixture"})
        text_payload = json.loads(result["content"][0]["text"])
        self.assertEqual(result["structuredContent"], text_payload)
        manifest = {t["name"]: t for t in cli.tool_manifest()["tools"]}
        errors = list(Draft202012Validator(
            manifest["device_show"]["output_schema"]).iter_errors(result["structuredContent"]))
        self.assertEqual(errors, [])

    def test_structured_content_wraps_array_payloads(self):
        # device_list returns a top-level array over the CLI; MCP structured
        # content must be an object, wrapped as {"items": [...]}.
        result = call_tool_with_fake_router("device_list")
        self.assertIsInstance(result["structuredContent"]["items"], list)
        # Tools SHOULD return the serialized structured content as text.
        self.assertEqual(json.loads(result["content"][0]["text"]), result["structuredContent"])

    def test_rate_limit_returns_tool_error_with_retry_hint(self):
        mcp._reset_rate_limiter()
        try:
            with tempfile.TemporaryDirectory() as tmp, patch.dict(
                "os.environ", {"XDG_CONFIG_HOME": tmp,
                               "TPLINK_MCP_RATE_LIMIT_PER_MINUTE": "2",
                               **PROFILE_SCRUB}, clear=False,
            ), patch.object(cli, "build_router", return_value=FakeRouter()):
                def call(i):
                    return mcp.handle_request(
                        {"jsonrpc": "2.0", "id": i, "method": "tools/call",
                         "params": {"name": "led_status", "arguments": {}}})
                self.assertFalse(call(1)["result"]["isError"])
                self.assertFalse(call(2)["result"]["isError"])
                limited = call(3)
                self.assertTrue(limited["result"]["isError"])
                payload = json.loads(limited["result"]["content"][0]["text"])
                self.assertEqual(payload["error"]["kind"], "rate_limited")
                self.assertGreaterEqual(payload["error"]["retry_after_seconds"], 1)
        finally:
            mcp._reset_rate_limiter()

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
        result = call_tool_with_fake_router("device_show", {"query": "fixture"})
        payload = json.loads(result["content"][0]["text"])
        self.assertFalse(result["isError"])
        self.assertEqual(payload["hostname"], "fixture-device")

    def test_firmware_audit_tool_is_read_only(self):
        result = call_tool_with_fake_router("firmware_audit")
        payload = json.loads(result["content"][0]["text"])
        self.assertFalse(result["isError"])
        self.assertTrue(payload["update"]["available"])
        self.assertFalse(payload["action_taken"])

    def test_device_plan_tool_does_not_mutate(self):
        result = call_tool_with_fake_router("device_plan", {"action": "block", "query": "fixture", "enforce": True})
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
                "params": {"name": "device_block", "arguments": {"query": "fixture"}},
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

    def test_stdio_round_trip_writes_newline_delimited_json(self):
        # MCP stdio transport contract: one JSON-RPC message per line.
        # The official MCP client rejects Content-Length (LSP) framing.
        raw = json.dumps(init()) + "\n" + json.dumps({"jsonrpc": "2.0", "id": 4, "method": "tools/list"}) + "\n"
        output = io.StringIO()
        with contextlib.redirect_stderr(io.StringIO()):
            mcp.serve(io.BytesIO(raw.encode()), output)
        written = output.getvalue()
        self.assertFalse(written.startswith("Content-Length:"))
        self.assertTrue(written.endswith("\n"))
        lines = written.splitlines()
        self.assertEqual(len(lines), 2)
        response = json.loads(lines[1])
        self.assertEqual(response["id"], 4)
        self.assertIn("tools", response["result"])

    def test_stdio_accepts_legacy_content_length_input(self):
        # Earlier builds of this server (and their clients) framed input with
        # Content-Length headers; the reader must keep accepting that.
        raw = b""
        for message in (init(), {"jsonrpc": "2.0", "id": 4, "method": "tools/list"}):
            body = json.dumps(message)
            raw += f"Content-Length: {len(body.encode('utf-8'))}\r\n\r\n{body}".encode()
        output = io.StringIO()
        with contextlib.redirect_stderr(io.StringIO()):
            mcp.serve(io.BytesIO(raw), output)
        response = json.loads(output.getvalue().splitlines()[1])
        self.assertEqual(response["id"], 4)
        self.assertIn("tools", response["result"])

    def test_audit_tail_tool_reads_cli_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            call_tool_in_config(tmp, "device_plan", {"action": "block", "query": "fixture"})
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
        self.assertEqual(json.loads(pf["content"][0]["text"])["items"][0]["name"], "fixture-https")

        ps = call_tool_with_fake_router("port_speed")
        self.assertFalse(ps["isError"])
        self.assertEqual(json.loads(ps["content"][0]["text"])["speed"], "1000F")

        ip6 = call_tool_with_fake_router("ipv6_status")
        self.assertFalse(ip6["isError"])
        self.assertTrue(json.loads(ip6["content"][0]["text"])["wan"]["enabled"])

        mesh = call_tool_with_fake_router("mesh_devices")
        self.assertFalse(mesh["isError"])
        self.assertEqual(json.loads(mesh["content"][0]["text"])["items"][0]["role"], "main_router")

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


class McpConformanceTests(unittest.TestCase):
    """Regression tests for the #17 second-pass audit, one per finding.

    Each drives the real stdio loop or request handler and asserts the reason
    for an error, not merely that one occurred.
    """

    def setUp(self):
        mcp._reset_rate_limiter()

    # A. lifecycle version negotiation is covered in McpTests.test_protocol_version_negotiation.

    def test_malformed_lines_do_not_kill_the_server(self):
        out = stdio(init(), "{not json\n", "\n", "42\n", req(2, "ping"))
        self.assertEqual([m.get("id") for m in out], [1, None, None, 2])
        self.assertEqual(out[1]["error"]["code"], -32700)  # parse error
        self.assertEqual(out[2]["error"]["code"], -32600)  # scalar is not a request
        self.assertEqual(out[3]["result"], {})              # blank line ignored, still alive
        # 2025-11-25: unreadable-id errors omit "id" (optional, non-null in the schema).
        self.assertNotIn("id", out[1])
        # Older revisions require an id field and keep JSON-RPC 2.0's null.
        out = stdio(init("2025-06-18"), "{not json\n")
        self.assertIn("id", out[1])
        self.assertIsNone(out[1]["id"])

    def test_batches_only_for_protocol_2025_03_26(self):
        notification = {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 9}}
        out = stdio(init("2025-03-26"), [req(2, "ping"), notification, req(3, "ping")])
        self.assertIsInstance(out[1], list)  # MUST receive batches in 2025-03-26
        self.assertEqual([r["id"] for r in out[1]], [2, 3])
        out = stdio(init("2025-03-26"), [init(rid=5)])
        self.assertEqual(out[1]["error"]["code"], -32600)  # initialize must not be batched
        out = stdio(init("2025-11-25"), [req(2, "ping")])
        self.assertEqual(out[1]["error"]["code"], -32600)  # batching removed in 2025-06-18

    def test_unknown_tool_and_malformed_calls_are_protocol_errors(self):
        cases = {
            "unknown tool": {"name": "no_such_tool", "arguments": {}},
            "missing name": {},
            "arguments not an object": {"name": "device_show", "arguments": "nope"},
        }
        for label, params in cases.items():
            with self.subTest(label):
                response = mcp.handle_request(req(1, "tools/call", params))
                self.assertEqual(response["error"]["code"], -32602, response)
                self.assertNotIn("result", response)
        response = mcp.handle_request(req(1, "tools/call", ["device_show"]))
        self.assertEqual(response["error"]["code"], -32602)

    def test_inputs_validated_against_input_schema_before_router_access(self):
        never = AssertionError("router must not be reached")
        cases = [
            ("device_show", {"query": "fixture", "bogus": 1}, "bogus"),
            ("device_list", {"top": "ten"}, "(top)"),
            ("device_list", {"sort": "nonsense"}, "(sort)"),
            ("led_plan", {"action": "explode"}, "(action)"),
            ("device_show", {"query": ""}, "(query)"),
        ]
        for name, arguments, needle in cases:
            with self.subTest(name=name, arguments=arguments), tempfile.TemporaryDirectory() as tmp, \
                    patch.dict("os.environ", {"XDG_CONFIG_HOME": tmp, **ADMIN}, clear=False), \
                    patch.object(cli, "build_router", side_effect=never) as router:
                result = mcp.call_tool(name, arguments)
                payload = json.loads(result["content"][0]["text"])
                self.assertTrue(result["isError"])
                self.assertEqual(payload["error"]["kind"], "usage")
                self.assertIn(f"Invalid arguments for {name}", payload["error"]["message"])
                self.assertIn(needle, payload["error"]["message"])
                router.assert_not_called()

    def test_upstream_exception_text_never_reaches_the_client(self):
        import requests
        token, host = "SESSIONSECRET123", "192.0.2.1"
        failures = {
            "router": requests.ConnectionError(
                f"HTTPConnectionPool(host='{host}', port=80): url: /cgi-bin/luci/;stok={token}/admin/status"),
            "internal": RuntimeError(f"{token} /private/fixture/diagnostics"),
        }
        for kind, exc in failures.items():
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp, \
                    patch.dict("os.environ", {"XDG_CONFIG_HOME": tmp, **ADMIN}, clear=False), \
                    patch.object(cli, "build_router", side_effect=exc):
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    result = mcp.call_tool("router_status")
                text = result["content"][0]["text"]
                self.assertTrue(result["isError"])
                self.assertEqual(json.loads(text)["error"]["kind"], kind)
                for secret in (token, host, "/private/fixture"):
                    if kind == "internal" and secret == host:
                        continue
                    self.assertNotIn(secret, text)
                self.assertNotIn(token, stderr.getvalue())  # stderr logs are redacted too
        self.assertIn(";stok=<redacted>", mcp._redact(f"/cgi-bin/luci/;stok={token}/x"))

    def test_invalid_envelopes(self):
        self.assertEqual(mcp.handle_request({"jsonrpc": "2.0", "id": None, "method": "ping"})["error"]["code"], -32600)
        self.assertEqual(mcp.handle_request({"jsonrpc": "2.0", "id": True, "method": "ping"})["error"]["code"], -32600)
        self.assertEqual(mcp.handle_request({"id": 1, "method": "ping"})["error"]["code"], -32600)
        self.assertEqual(mcp.handle_request({"jsonrpc": "2.0", "id": 1, "method": 7})["error"]["code"], -32600)
        # Responses to (nonexistent) server requests and malformed notifications are ignored.
        self.assertIsNone(mcp.handle_request({"jsonrpc": "2.0", "id": 1, "result": {}}))
        self.assertIsNone(mcp.handle_request({"method": "notifications/cancelled"}))

    def test_requests_before_initialize_fail_deterministically(self):
        out = stdio(req(1, "tools/list"), req(2, "tools/call", {"name": "router_status"}),
                    req(3, "ping"), req(4, "server/discover"))
        self.assertEqual(out[0]["error"]["code"], -32600)
        self.assertEqual(out[1]["error"]["code"], -32600)
        self.assertEqual(out[2]["result"], {})                 # ping is always allowed
        self.assertEqual(out[3]["error"]["code"], -32601)      # modern probe -> legacy fallback

    def test_responses_shaped_for_negotiated_version(self):
        expectations = {
            "2024-11-05": (set(), False),
            "2025-03-26": ({"annotations"}, False),
            "2025-06-18": ({"annotations", "title", "outputSchema", "_meta"}, True),
            "2025-11-25": ({"annotations", "title", "outputSchema", "_meta"}, True),
        }
        base = {"name", "description", "inputSchema"}
        for version, (extra, structured) in expectations.items():
            with self.subTest(version=version):
                out = stdio(init(version), req(2, "tools/list"))
                for tool in out[1]["result"]["tools"]:
                    self.assertEqual(set(tool), base | extra, tool["name"])
                info = out[0]["result"]["serverInfo"]
                self.assertEqual("title" in info, version >= "2025-06-18")
                self.assertEqual("websiteUrl" in info, version >= "2025-11-25")
                result = call_tool_with_fake_router("led_status", version=version)
                self.assertEqual("structuredContent" in result, structured)

    def test_every_tool_payload_conforms_to_advertised_output_schema(self):
        from jsonschema import Draft202012Validator
        arguments = {
            "device_show": {"query": "fixture"}, "led_plan": {"action": "off"},
            "led_set": {"action": "off", "confirm": True},
            "device_plan": {"action": "block", "query": "fixture"},
            "device_block": {"query": "fixture", "confirm": True},
            "device_unblock": {"query": "fixture", "confirm": True},
            "wifi_config_plan": {"connection": "host_5g", "channel": "149"},
            "wifi_config": {"connection": "host_5g", "channel": "149", "confirm": True},
            "watch": {"target": "devices", "count": 1}, "audit_tail": {"tail": 5},
            "state_snapshot": {"name": "sweep"}, "state_diff": {"before": "sweep", "after": "sweep"},
        }
        tools = {t["name"]: t for t in mcp.tool_definitions()}
        checked = 0
        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict("os.environ", {"XDG_CONFIG_HOME": tmp, **{**ADMIN, "TPLINK_MCP_PROFILE": "dangerous"}}, clear=False), \
                patch.object(cli, "build_router", side_effect=lambda *a, **k: FakeRouter()):
            for name in sorted(tools, key=lambda n: (n == "state_diff", n)):
                with self.subTest(name=name):
                    result = mcp.call_tool(name, arguments.get(name, {}))
                    if result["isError"]:
                        # Only a fixture-driven semantic failure is acceptable here.
                        self.assertEqual(name, "device_unblock", result)
                        continue
                    errors = list(Draft202012Validator(tools[name]["outputSchema"]).iter_errors(
                        result["structuredContent"]))
                    self.assertEqual(errors, [], name)
                    self.assertEqual(json.loads(result["content"][0]["text"]), result["structuredContent"])
                    checked += 1
        self.assertEqual(checked, len(tools) - 1)

    def test_watch_duration_is_bounded(self):
        for arguments, needle in (({"count": 61}, "(count)"), ({"count": 10, "interval": 20}, "must be <=")):
            with self.subTest(arguments=arguments):
                result = call_tool_with_fake_router("watch", arguments)
                self.assertTrue(result["isError"])
                self.assertIn(needle, json.loads(result["content"][0]["text"])["error"]["message"])

    def test_default_profile_is_read_only(self):
        blocked = call_tool_with_fake_router("device_block", {"query": "fixture", "confirm": True}, env=PROFILE_SCRUB)
        self.assertTrue(blocked["isError"])
        self.assertEqual(json.loads(blocked["content"][0]["text"])["error"]["kind"], "permission")
        allowed = call_tool_with_fake_router("router_status", env=PROFILE_SCRUB)
        self.assertFalse(allowed["isError"])

    def test_unknown_tool_names_do_not_grow_rate_limiter_state(self):
        for i in range(5):
            mcp.handle_request(req(i, "tools/call", {"name": f"bogus_{i}"}))
        self.assertFalse(any(k.startswith("bogus_") for k in mcp._RATE_LIMITER._calls))

    def test_stray_stdout_writes_cannot_corrupt_the_protocol_stream(self):
        import os as _os
        import subprocess
        import sys as _sys
        script = (
            "import os\n"
            "from tplink_admin import cli, mcp\n"
            "def noisy(argv):\n"
            "    os.write(1, b'STRAY-FD1\\n')\n"
            "    print('{}')\n"
            "cli.main = noisy\n"
            "raise SystemExit(mcp.main())\n"
        )
        lines = [init(), req(2, "tools/call", {"name": "time_status"}), req(3, "ping")]
        env = {**_os.environ, "PYTHONPATH": "src", **ADMIN}
        proc = subprocess.run([_sys.executable, "-c", script], input="".join(json.dumps(m) + "\n" for m in lines),
                              capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        messages = [json.loads(line) for line in proc.stdout.splitlines()]  # every line is JSON
        self.assertEqual([m["id"] for m in messages], [1, 2, 3])
        self.assertIn("STRAY-FD1", proc.stderr)
