import concurrent.futures
import contextlib
from copy import deepcopy
import http.client
import io
import json
from pathlib import Path
import secrets
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator
from openapi_spec_validator import validate

from http_router import Router, WebResponse
from tplink_admin import api, cli, mcp, openapi, registry


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        tmp = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.stack.enter_context(patch.dict("os.environ", {
            "XDG_CONFIG_HOME": tmp, "TPLINK_PROFILE": "", "TPLINK_MCP_PROFILE": "dangerous",
            "TPLINK_ENABLE_COMMANDS": "", "TPLINK_DISABLE_COMMANDS": "", "TPLINK_PASSWORD": "",
        }))
        self.router = Router()
        self.real_build_router = cli.build_router
        self.stack.enter_context(patch.object(cli, "build_router", return_value=self.router))
        self.stack.enter_context(patch.object(cli.requests, "get", return_value=WebResponse()))
        self.tokens = {name: secrets.token_urlsafe(32) for name in ("admin", "other", "reader", "device")}
        self.app = api.Application({
            self.tokens["admin"]: api.Principal("operator-a", "network-admin"),
            self.tokens["other"]: api.Principal("operator-b", "network-admin"),
            self.tokens["reader"]: api.Principal("operator-a", "read-only"),
            self.tokens["device"]: api.Principal("device-operator", "device-admin"),
        })
        self.server = api.create_server(self.app, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def request(self, method, path, payload=None, *, actor="admin", headers=None, raw=None):
        conn = http.client.HTTPConnection(*self.server.server_address, timeout=10)
        head = {"Authorization": "Bearer " + self.tokens[actor], "Content-Type": "application/json"}
        head.update(headers or {})
        body = raw if raw is not None else json.dumps(payload) if payload is not None else None
        try:
            conn.request(method, path, body=body, headers=head)
            response = conn.getresponse()
            value = json.loads(response.read())
            self.assertEqual(response.getheader("Cache-Control"), "no-store")
            return response.status, value
        finally:
            conn.close()

    def led_plan(self, **kwargs):
        status, result = self.request("POST", "/v1/router/led/plans", {"action": "off", **kwargs})
        self.assertEqual(status, 200, result)
        return result

    def test_every_read_route_uses_router_and_schema(self):
        for item in registry.tools():
            if item.get("http", {}).get("method") != "get":
                continue
            with self.subTest(operation=item["name"]):
                path = item["http"]["path"].replace("{query}", "fixture-device")
                status, result = self.request("GET", path, actor="reader")
                self.assertEqual(status, 200, result)
                Draft202012Validator(registry.http_output(item)).validate(result)
        self.assertEqual(self.router.writes, [])
        self.assertGreater(len(self.router.requests), 0)

    def test_read_result_matches_cli_and_mcp_and_redacts(self):
        status, result = self.request("GET", "/v1/vpn/wireguard")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            cli.main(["--json", "--no-input", "wireguard"])
        tool = mcp.call_tool("wireguard_status")
        self.assertEqual(status, 200, result)
        self.assertEqual(result["data"], json.loads(output.getvalue()))
        self.assertEqual(result["data"], json.loads(tool["content"][0]["text"]))
        self.assertNotIn(self.router.secret, json.dumps(result))
        self.assertEqual(result["data"]["public_key"], "fixture-public")

    def test_plan_confirmation_exactly_once_and_audit(self):
        reason = secrets.token_urlsafe(24)
        plan = self.led_plan(reason=reason)
        self.assertEqual(self.router.writes, [])
        self.assertEqual(plan["diff"], [{"field": "enabled", "before": True, "after": False}])
        self.assertEqual(plan["rollback"]["commands"], [["tplinkctl", "led", "on", "--yes"]])
        self.assertTrue(plan["rollback"]["supported"])
        self.assertFalse(plan["rollback"]["automatic"])
        self.assertGreater(datetime_parse(plan["expires_at"]), time.time())
        payload = {"action": "off", "plan_id": plan["plan_id"], "confirm": True, "reason": reason}
        status, result = self.request("PUT", "/v1/router/led", payload)
        self.assertEqual(status, 200, result)
        self.assertFalse(result["data"]["enabled"])
        self.assertEqual(self.request("PUT", "/v1/router/led", payload)[0], 409)
        self.assertEqual(len(self.router.writes), 1)
        events = cli.read_jsonl(self.app.events)
        self.assertEqual([e["event"] for e in events], ["plan", "execute_attempt", "execute"])
        for event in events:
            self.assertEqual(event["profile"], "network-admin")
            self.assertEqual(event["operation"], "led_set")
            self.assertIn("target", event)
            self.assertEqual(event["reason"], "[redacted]")
        self.assertEqual(events[-1]["result"], "success")
        audit = self.app.events.read_text()
        for forbidden in [reason, plan["plan_id"], self.router.secret, *self.tokens.values()]:
            self.assertNotIn(forbidden, audit)

    def test_unplanned_false_missing_and_wrong_type_confirmation(self):
        plan = self.led_plan()
        for body in ({"action": "off", "confirm": True},
                     {"action": "off", "plan_id": plan["plan_id"]},
                     {"action": "off", "plan_id": plan["plan_id"], "confirm": False},
                     {"action": "off", "plan_id": plan["plan_id"], "confirm": "true"}):
            status, value = self.request("PUT", "/v1/router/led", body)
            self.assertEqual(status, 409, value)
            self.assertEqual(value["error"]["kind"], "confirmation_required")
        self.assertEqual(self.router.writes, [])

    def test_expiry_actor_argument_profile_and_operation_binding(self):
        plan = self.led_plan()
        payload = {"action": "off", "plan_id": plan["plan_id"], "confirm": True}
        for actor, change, expected in (("other", {}, 409), ("reader", {}, 403),
                                        ("admin", {"action": "on"}, 409)):
            status, result = self.request("PUT", "/v1/router/led", {**payload, **change}, actor=actor)
            self.assertEqual(status, expected, result)
        status, result = self.request("PUT", "/v1/wifi/host_5g/configuration",
                                      {"channel": "44", "plan_id": plan["plan_id"], "confirm": True})
        self.assertEqual(status, 409, result)
        self.app.plans[plan["plan_id"]].deadline = time.monotonic() - 1
        self.assertEqual(self.request("PUT", "/v1/router/led", payload)[0], 409)
        self.assertEqual(self.router.writes, [])

    def test_concurrent_execution_consumes_one_plan(self):
        plan = self.led_plan()
        payload = {"action": "off", "plan_id": plan["plan_id"], "confirm": True}
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            responses = list(pool.map(lambda _: self.request("PUT", "/v1/router/led", payload)[0], range(6)))
        self.assertEqual(sorted(responses), [200, 409, 409, 409, 409, 409])
        self.assertEqual(len(self.router.writes), 1)

    def test_device_target_change_rejected_and_valid_block_unblock(self):
        path = "/v1/devices/fixture-device"
        status, plan = self.request("POST", path + "/plans", {"action": "block"}, actor="device")
        self.assertEqual(status, 200, plan)
        self.router.device["_macaddr"] = "02-00-00-00-00-02"
        payload = {"plan_id": plan["plan_id"], "confirm": True}
        self.assertEqual(self.request("PUT", path + "/block", payload, actor="device")[0], 409)
        self.assertEqual(self.router.writes, [])
        self.router.device["_macaddr"] = self.router.mac
        _, plan = self.request("POST", path + "/plans", {"action": "block", "enforce": True}, actor="device")
        self.assertFalse(plan["rollback"]["supported"])
        self.assertIn("global Access Control", " ".join(plan["rollback"]["limitations"]))
        status, result = self.request("PUT", path + "/block", {"plan_id": plan["plan_id"], "confirm": True, "enforce": True}, actor="device")
        self.assertEqual(status, 200, result)
        self.assertTrue(result["data"]["blocked"])
        self.assertEqual(self.router.forms[cli.ACCESS_BLACK_LIST][0]["mac"], self.router.mac)
        _, plan = self.request("POST", path + "/plans", {"action": "unblock"}, actor="device")
        status, result = self.request("DELETE", path + "/block", {"plan_id": plan["plan_id"], "confirm": True}, actor="device")
        self.assertEqual(status, 200, result)
        self.assertEqual(self.router.forms[cli.ACCESS_BLACK_LIST], [])

    def test_state_drift_and_unknown_outcome_consume_plans(self):
        plan = self.led_plan()
        self.router.forms[cli.LED_GENERAL]["enable"] = "off"
        status, result = self.request("PUT", "/v1/router/led", {"action": "off", "plan_id": plan["plan_id"], "confirm": True})
        self.assertEqual(status, 409, result)
        self.assertEqual(self.router.writes, [])
        plan = self.led_plan()
        self.assertEqual(plan["rollback"]["commands"][0][2], "off")  # actual prior state, not opposite request
        self.router.fail_writes = True
        body = {"action": "off", "plan_id": plan["plan_id"], "confirm": True}
        status, result = self.request("PUT", "/v1/router/led", body)
        self.assertEqual(status, 502, result)
        self.assertNotIn(self.router.secret, json.dumps(result))
        self.assertEqual(self.request("PUT", "/v1/router/led", body)[0], 409)
        self.assertEqual(cli.read_jsonl(self.app.events)[-1]["result"], "failed_or_unknown")

    def test_wifi_plan_execution_and_secret_redaction(self):
        path = "/v1/wifi/host_5g"
        status, plan = self.request("POST", path + "/plans", {"channel": "44"})
        self.assertEqual(status, 200, plan)
        self.assertEqual(plan["diff"], [{"field": "channel", "before": "36", "after": "44"}])
        self.assertNotIn(self.router.secret, json.dumps(plan))
        status, value = self.request("PUT", path + "/configuration", {"channel": "44", "confirm": True, "plan_id": plan["plan_id"]})
        self.assertEqual(status, 200, value)
        self.assertEqual(value["data"]["channel"], "44")

    def test_auth_and_validation_fail_closed_before_router(self):
        cases = [
            ("GET", "/v1/devices", None, {"Authorization": ""}, 401),
            ("GET", "/v1/devices?profile=dangerous", None, {}, 400),
            ("GET", "/v1/devices?top=bad", None, {}, 400),
            ("GET", "/v1/devices?active=invalid", None, {}, 400),
            ("GET", "/v1/devices?top=1&top=2", None, {}, 400),
            ("GET", "/v1/devices", None, {"Origin": "https://example.invalid"}, 403),
            ("POST", "/v1/router/led/plans", {"action": "off", "profile": "dangerous"}, {}, 400),
            ("POST", "/v1/router/led/plans", {"action": "schedule"}, {}, 400),
            ("POST", "/v1/router/led/plans", {"action": "off", "enabled": True}, {}, 400),
            ("POST", "/v1/router/led/plans", {"action": "schedule", "enabled": True, "start": "25:00"}, {}, 400),
            ("POST", "/v1/router/led/plans", {"action": "off"}, {"Content-Type": "text/plain"}, 400),
            ("GET", "/v1/audit", None, {}, 404),
            ("GET", "/v1/tools/router_status", None, {}, 404),
        ]
        for method, path, body, headers, expected in cases:
            with self.subTest(path=path, body=body):
                status, value = self.request(method, path, body, headers=headers)
                self.assertEqual(status, expected, value)
                Draft202012Validator(registry.ERROR_SCHEMA).validate(value)
        for raw in ('{"action":"off","action":"on"}', '{"action":NaN}', '[]'):
            self.assertEqual(self.request("POST", "/v1/router/led/plans", raw=raw)[0], 400)
        self.assertEqual(self.router.requests, [])
        self.assertEqual(self.router.writes, [])

    def test_error_parity_for_not_found(self):
        status, result = self.request("GET", "/v1/devices/missing")
        self.assertEqual(status, 404)
        self.assertEqual(result["error"]["kind"], "not_found")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.run(["--json", "--no-input", "device", "missing"]), 3)
        response = mcp.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "device_show", "arguments": {"query": "missing"}}})
        self.assertTrue(response["result"]["isError"])

    def test_nested_router_errors_do_not_expose_diagnostics(self):
        marker = secrets.token_urlsafe(24)
        private_path = "/private/fixture/diagnostics"
        with patch.object(self.router, "request", side_effect=RuntimeError(marker + " " + private_path)):
            status, result = self.request("GET", "/v1/wifi")
        self.assertEqual(status, 200)
        self.assertNotIn(marker, json.dumps(result))
        self.assertNotIn(private_path, json.dumps(result))
        self.assertIsInstance(result["data"]["errors"], dict)

    def test_enforcement_binds_full_policy_membership(self):
        before = {"mac": "02-00-00-00-00-03", "name": "fixture-other"}
        self.router.forms[cli.ACCESS_BLACK_LIST] = [before]
        path = "/v1/devices/fixture-device"
        status, plan = self.request("POST", path + "/plans", {"action": "block", "enforce": True}, actor="device")
        self.assertEqual(status, 200, plan)
        self.router.forms[cli.ACCESS_BLACK_LIST] = [{"mac": "02-00-00-00-00-04", "name": "fixture-replacement"}]
        status, result = self.request("PUT", path + "/block", {"enforce": True, "confirm": True, "plan_id": plan["plan_id"]}, actor="device")
        self.assertEqual(status, 409, result)
        self.assertEqual(self.router.writes, [])
        self.assertIn(before["mac"], json.dumps(plan["target"]))

    def test_failed_readback_is_not_success_and_consumes_plan(self):
        original = deepcopy(self.router.forms)
        cases = [
            ("/v1/wifi/host_5g/plans", "/v1/wifi/host_5g/configuration", {"channel": "44"}, {"channel": "44"}),
            ("/v1/router/led/plans", "/v1/router/led", {"action": "schedule", "enabled": True, "start": "23:00"}, {"action": "schedule", "enabled": True, "start": "23:00"}),
            ("/v1/devices/fixture-device/plans", "/v1/devices/fixture-device/block", {"action": "block", "enforce": True}, {"enforce": True}),
        ]
        for plan_path, execute_path, planning, executing in cases:
            with self.subTest(resource=execute_path):
                self.router.forms = deepcopy(original)
                self.router.forms[cli.ACCESS_BLACK_LIST] = [{"mac": self.router.mac, "name": "fixture-device"}]
                self.router.ignore_writes = True
                status, plan = self.request("POST", plan_path, planning)
                self.assertEqual(status, 200, plan)
                body = {**executing, "confirm": True, "plan_id": plan["plan_id"]}
                status, result = self.request("PUT", execute_path, body)
                self.assertEqual(status, 502, result)
                self.assertEqual(cli.read_jsonl(self.app.events)[-1]["result"], "failed_or_unknown")
                self.assertEqual(self.request("PUT", execute_path, body)[0], 409)

    def test_server_issued_hyphen_plan_id_executes(self):
        with patch.object(api.secrets, "token_urlsafe", return_value="-" + "A" * 42):
            plan = self.led_plan()
        status, result = self.request("PUT", "/v1/router/led", {"action": "off", "confirm": True, "plan_id": plan["plan_id"]})
        self.assertEqual(status, 200, result)
        self.assertEqual(len(self.router.writes), 1)

    def test_missing_unblock_has_semantic_error_across_transports(self):
        status, result = self.request("POST", "/v1/devices/missing/plans", {"action": "unblock"})
        self.assertEqual(status, 404, result)
        self.assertEqual(result["error"]["kind"], "not_found")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = cli.run(["--json", "--no-input", "device", "unblock", "missing", "--plan"])
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(stderr.getvalue().splitlines()[-1])["error"]["kind"], "not_found")
        response = mcp.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "device_plan", "arguments": {"query": "missing", "action": "unblock"}}})
        self.assertTrue(response["result"]["isError"])
        self.assertEqual(json.loads(response["result"]["content"][0]["text"])["error"]["kind"], "not_found")

    def test_upstream_auth_does_not_challenge_valid_bearer(self):
        # Exercise the real CLI's missing-password guard, not a fabricated
        # error from HTTP. The SDK constructor must never run.
        with patch.object(cli, "build_router", wraps=self.real_build_router), patch.object(cli, "TplinkRouterSG") as sdk:
            connection = http.client.HTTPConnection(*self.server.server_address, timeout=10)
            try:
                connection.request("GET", "/v1/router/led", headers={"Authorization": "Bearer " + self.tokens["reader"]})
                response = connection.getresponse()
                result = json.loads(response.read())
                self.assertEqual(response.status, 502, result)
                self.assertEqual(result["error"]["kind"], "auth")
                self.assertIsNone(response.getheader("WWW-Authenticate"))
            finally:
                connection.close()
            sdk.assert_not_called()
        self.assertEqual(self.request("GET", "/v1/router/led", headers={"Authorization": ""})[0], 401)

    def test_bind_defaults_and_profile_startup(self):
        with self.assertRaises(ValueError):
            api.create_server(self.app, "0.0.0.0", 0)
        with self.assertRaises(ValueError):
            api.create_server(self.app, "localhost", 0)
        with self.assertRaises(ValueError):
            api.Application({})
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        self.assertEqual(self.request("POST", "/v1/router/led/plans", {"action": "off"}, actor="reader")[0], 403)
        self.assertEqual(self.request("POST", "/v1/router/led/plans", {"action": "off"}, actor="device")[0], 403)
        self.assertEqual(self.router.requests, [])


def datetime_parse(text):
    from datetime import datetime
    return datetime.fromisoformat(text).timestamp()


class ContractTests(unittest.TestCase):
    def test_openapi_validation_determinism_and_artifact(self):
        validate(openapi.document())
        self.assertEqual(openapi.render(), openapi.render())
        self.assertEqual(Path("docs/openapi.json").read_text(), openapi.render())

    def test_registry_cli_mcp_http_parameters_and_safety(self):
        items = {i["name"]: i for i in cli.tool_manifest()["tools"]}
        schema = cli.schema_document()
        self.assertEqual({i["name"]: i for i in schema["x-tplinkctl-tools"]}, items)
        definitions = {i["name"]: i for i in mcp.handle_request({"id": 1, "method": "tools/list"})["result"]["tools"]}
        self.assertEqual(set(definitions), set(items))
        self.assertEqual(set(mcp.TOOL_BUILDERS), set(items))
        doc = openapi.document()
        operations = {v["operationId"]: v for path in doc["paths"].values() for v in path.values()}
        local = {i["name"] for i in doc["x-tplinkctl-local-only"]}
        self.assertEqual(set(operations) | local, set(items))
        self.assertFalse(set(operations) & local)
        self.assertEqual(local, {"watch", "audit_tail", "state_snapshot", "state_diff"})
        for name, item in items.items():
            with self.subTest(name=name):
                tool = definitions[name]
                self.assertEqual(tool["inputSchema"], item["input_schema"])
                self.assertEqual(tool["annotations"]["readOnlyHint"], item["read_only"])
                for key in ("risk", "profiles", "plan_operation", "rollback_contract", "local_only", "output_schema"):
                    self.assertEqual(tool["_meta"]["tplinkctl"][key], item[key])
                if name in local:
                    continue
                operation = operations[name]
                self.assertEqual(operation["x-tplinkctl-read-only"], item["read_only"])
                for suffix, key in (("risk", "risk"), ("profile", "profiles"), ("plan-operation", "plan_operation"), ("rollback", "rollback_contract")):
                    self.assertEqual(operation["x-tplinkctl-" + suffix], item[key])
                self.assertEqual(doc["components"]["schemas"][name + "Input"], item["input_schema"])
                props = {p["name"]: p["schema"] for p in operation["parameters"]}
                required = {p["name"] for p in operation["parameters"] if p["required"]}
                if "requestBody" in operation:
                    body = doc["components"]["schemas"][name + "Request"]
                    props.update(body["properties"])
                    required.update(body["required"])
                expected = registry.http_input(item)
                self.assertEqual(props, expected["properties"])
                self.assertEqual(required, set(expected.get("required", [])))
                if not item["read_only"]:
                    self.assertIn("plan_id", required)
                    self.assertIn("confirm", required)
                    self.assertIn(item["plan_operation"], operations)
                    self.assertFalse(operation["x-tplinkctl-rollback"]["automatic"])
        self.assertEqual(doc["x-tplinkctl-error-status"], registry.ERROR_STATUS)
        self.assertEqual(doc["x-tplinkctl-upstream-error-status"], {"auth": 502})
        self.assertEqual(set(registry.ERROR_STATUS), set(cli.ERROR_CATALOG))


if __name__ == "__main__":
    unittest.main()
