#!/usr/bin/env python3
"""Public CLI regression tests; --docker-failure exercises real Forge failure."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/forge_generate.py"
FIXTURE = ROOT / "tooling/forge/probe.json"
DOCKER_FAILURE = False


class ForgeContract(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="forge-contract-", dir=os.environ.get("TMPDIR"))
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name)
        self.spec = self.work / "input.json"
        self.document = json.loads(FIXTURE.read_text())
        self.spec.write_text(json.dumps(self.document))

    def run_cli(self, command="validate", *arguments):
        process = subprocess.run([sys.executable, str(SCRIPT), command, "--spec", str(self.spec), *map(str, arguments)],
                                 capture_output=True, text=True, timeout=600)
        # Public diagnostics must not expose upstream stderr, machine paths, or
        # arbitrary schema descriptions. They are safe for artifact upload.
        self.assertNotIn(str(self.work), process.stdout + process.stderr)
        self.assertNotIn("SYNTHETIC_PRIVATE_MARKER", process.stdout + process.stderr)
        self.assertEqual(process.stderr, "")
        return process.returncode, json.loads(process.stdout)

    def write_spec(self):
        self.spec.write_text(json.dumps(self.document))

    def test_valid_bundled_spec_without_docker(self):
        code, report = self.run_cli()
        self.assertEqual(code, 0)
        self.assertEqual(report["operation_count"], 1)

    def test_rejects_invalid_contracts_without_echoing_input(self):
        for case in ("duplicate", "external", "invalid-schema"):
            with self.subTest(case=case):
                self.document = json.loads(FIXTURE.read_text())
                op = self.document["paths"]["/v1/router/status"]["get"]
                if case == "duplicate":
                    self.document["paths"]["/v1/duplicate"] = {"get": op}
                elif case == "external":
                    self.document["components"]["schemas"]["Status"] = {"$ref": "http://127.0.0.1:9/SYNTHETIC_PRIVATE_MARKER"}
                else:
                    self.document["components"]["schemas"]["Status"]["type"] = "SYNTHETIC_PRIVATE_MARKER"
                self.write_spec()
                code, report = self.run_cli()
                self.assertEqual(code, 1)
                self.assertEqual(report["status"], "failed")
                self.assertEqual(report["phase"], "validate")

    def test_report_cannot_clobber_input_or_output(self):
        original = self.spec.read_bytes()
        code, report = self.run_cli("validate", "--report", self.spec)
        self.assertEqual(code, 1)
        self.assertEqual(report["error"], "report-exists-use-new-path")
        self.assertEqual(self.spec.read_bytes(), original)
        output = self.work / "output"
        code, report = self.run_cli("generate", "--output", output, "--report", output)
        self.assertEqual(code, 1)
        self.assertEqual(report["error"], "unsafe-report-path")
        self.assertFalse(output.exists())

    @unittest.skipUnless(sys.platform == "linux", "Linux-only generator")
    def test_existing_output_is_preserved_before_generation(self):
        output = self.work / "last-good"
        output.mkdir()
        sentinel = output / "sentinel"
        sentinel.write_text("previous successful artifact")
        code, report = self.run_cli("generate", "--output", output)
        self.assertEqual(code, 1)
        self.assertEqual(report["error"], "output-exists-use-new-versioned-directory")
        self.assertEqual(sentinel.read_text(), "previous successful artifact")
        self.assertEqual(list(output.iterdir()), [sentinel])

    def test_real_generator_failure_leaves_no_partial_output(self):
        if not DOCKER_FAILURE:
            self.skipTest("enable --docker-failure for actual upstream failure")
        # At this pinned revision, the merger assumes api/resources exists.
        # A legal ungrouped spec reaches Fern then triggers its real ENOENT.
        del self.document["paths"]["/v1/router/status"]["get"]["tags"]
        self.write_spec()
        output = self.work / "failed-output"
        report_file = self.work / "safe-report.json"
        code, report = self.run_cli("generate", "--output", output, "--report", report_file)
        self.assertEqual(code, 1)
        self.assertEqual(report["phase"], "generate")
        self.assertIn("fern-validation-passed", report["diagnostics"])
        self.assertIn("missing-file", report["diagnostics"])
        self.assertFalse(output.exists())
        self.assertFalse(list(self.work.glob(".forge-stage-*")))
        self.assertEqual(json.loads(report_file.read_text()), report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker-failure", action="store_true")
    args = parser.parse_args()
    DOCKER_FAILURE = args.docker_failure
    unittest.main(argv=[sys.argv[0]], verbosity=2)
