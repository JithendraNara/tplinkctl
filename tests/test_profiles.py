"""Safety profiles are packaged data; these tests pin their contract."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tplink_admin import cli, mcp, registry

PROFILE_DIR = Path(cli.__file__).parent / "profiles"
ORDER = ["read-only", "device-admin", "network-admin", "dangerous"]

# Minimal valid arguments for tools with required inputs.
SAMPLE_ARGUMENTS = {
    "device_show": {"query": "fixture"},
    "led_plan": {"action": "off"},
    "led_set": {"action": "off", "confirm": True},
    "device_plan": {"action": "block", "query": "fixture"},
    "device_block": {"query": "fixture", "confirm": True},
    "device_unblock": {"query": "fixture", "confirm": True},
    "wifi_config_plan": {"connection": "host_5g", "channel": "149"},
    "wifi_config": {"connection": "host_5g", "channel": "149", "confirm": True},
    "watch": {"target": "devices", "count": 1},
    "audit_tail": {"tail": 5},
    "state_snapshot": {"name": "fixture"},
    "state_diff": {"before": "a", "after": "b"},
}


def allowed_operations(name):
    profile = cli.POLICY_PROFILES[name]
    if "*" in profile["allow_operations"]:
        return cli.READ_OPERATIONS | cli.MUTATION_OPERATIONS
    return set(profile["allow_operations"]) - set(profile["deny_operations"])


class ProfileDataTests(unittest.TestCase):
    def test_packaged_files_are_the_profiles(self):
        files = sorted(p.stem for p in PROFILE_DIR.glob("*.json"))
        self.assertEqual(files, sorted(ORDER))
        self.assertEqual(sorted(cli.POLICY_PROFILES), sorted(ORDER))
        for name in ORDER:
            doc = json.loads((PROFILE_DIR / f"{name}.json").read_text())
            self.assertEqual(doc["name"], name)
            for key in ("allow_commands", "allow_operations", "deny_operations"):
                self.assertEqual(doc[key], sorted(set(doc[key])), f"{name}.{key} must be sorted and unique")

    def test_malformed_profiles_fail_loudly(self):
        good = {"name": "x", "description": "d", "allow_commands": [], "allow_operations": [], "deny_operations": []}
        cases = {
            "missing key": {k: v for k, v in good.items() if k != "deny_operations"},
            "unknown key": {**good, "allow_everything": True},
            "name mismatch": {**good, "name": "y"},
            "non-list": {**good, "allow_operations": "device.block"},
            "empty string": {**good, "allow_commands": [""]},
        }
        for label, doc in cases.items():
            with self.subTest(label), tempfile.TemporaryDirectory() as tmp:
                Path(tmp, "x.json").write_text(json.dumps(doc))
                with self.assertRaises(RuntimeError):
                    cli.load_policy_profiles(Path(tmp))
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(RuntimeError):
            cli.load_policy_profiles(Path(tmp))

    def test_operations_named_in_profiles_exist(self):
        known = cli.READ_OPERATIONS | cli.MUTATION_OPERATIONS | {"*"}
        for name, profile in cli.POLICY_PROFILES.items():
            for key in ("allow_operations", "deny_operations"):
                with self.subTest(profile=name, key=key):
                    self.assertEqual(set(profile[key]) - known, set())

    def test_read_only_allows_no_mutation(self):
        self.assertEqual(allowed_operations("read-only") & cli.MUTATION_OPERATIONS, set())
        self.assertEqual(set(cli.POLICY_PROFILES["read-only"]["deny_operations"]), cli.MUTATION_OPERATIONS)

    def test_profiles_widen_monotonically(self):
        for narrower, wider in zip(ORDER, ORDER[1:]):
            with self.subTest(narrower=narrower, wider=wider):
                self.assertLessEqual(allowed_operations(narrower), allowed_operations(wider))

    def test_advertised_tool_profiles_match_enforcement(self):
        # registry `profiles` gates HTTP and is advertised over MCP; it must
        # agree with what the CLI policy actually enforces for each tool.
        items = {item["name"]: item for item in registry.tools()}
        self.assertEqual(set(mcp.TOOL_BUILDERS), set(items))
        parser = cli.build_parser()
        for name, builder in sorted(mcp.TOOL_BUILDERS.items()):
            for profile in ORDER:
                with self.subTest(tool=name, profile=profile), \
                        patch.dict(os.environ, {"TPLINK_MCP_PROFILE": profile}):
                    args = parser.parse_args(builder(SAMPLE_ARGUMENTS.get(name, {})))
                    enforced = cli.profile_denial(profile, args.command, cli.operation_id(args)) is None
                    self.assertEqual(enforced, profile in items[name]["profiles"])


if __name__ == "__main__":
    unittest.main()
