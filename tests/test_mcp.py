import contextlib
import io
import json
import tempfile
import unittest
from unittest.mock import patch

from tplink_admin import cli
from tplink_admin import mcp
from test_cli import FakeRouter


def call_tool_with_fake_router(name, arguments=None):
    with tempfile.TemporaryDirectory() as tmp:
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
        self.assertIn("device_plan", names)
        self.assertIn("watch", names)

    def test_device_show_tool_uses_cli_json(self):
        result = call_tool_with_fake_router("device_show", {"query": "debian"})
        payload = json.loads(result["content"][0]["text"])
        self.assertFalse(result["isError"])
        self.assertEqual(payload["hostname"], "debian_linux")

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


if __name__ == "__main__":
    unittest.main()
