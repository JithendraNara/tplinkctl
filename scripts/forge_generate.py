#!/usr/bin/env python3
"""Pinned, offline-spec-first Cloudflare Forge downstream artifact gate."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "tooling" / "forge"
METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}


class Failure(Exception):
    """A public diagnostic whose text contains no upstream or user payload."""


def dump(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def operations(spec: dict) -> dict:
    return {
        operation["operationId"]: (method.upper(), path, operation)
        for path, item in spec["paths"].items()
        for method, operation in item.items()
        if method in METHODS
    }


def validate_spec(path: Path) -> dict:
    """Validate bundled OAS without Docker, HTTP fetching, or tplink imports."""
    from openapi_spec_validator import OpenAPIV31SpecValidator

    spec = json.loads(path.read_text())
    # Reject external references before any validating library can resolve them.
    def bundled(value: object) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {"$ref", "$dynamicRef"} and (
                    not isinstance(child, str) or not child.startswith("#/")
                ):
                    raise Failure("spec-external-reference")
                bundled(child)
        elif isinstance(value, list):
            for child in value:
                bundled(child)

    bundled(spec)
    if spec.get("openapi", "").split(".")[:2] != ["3", "1"]:
        raise Failure("spec-requires-openapi-3.1")
    OpenAPIV31SpecValidator(spec).validate()
    # OAS validates document structure but may accept malformed JSON Schema
    # vocabularies. Validate component and inline schemas independently.
    from jsonschema import Draft202012Validator
    for schema in spec.get("components", {}).get("schemas", {}).values():
        Draft202012Validator.check_schema(schema)
    def check_inline(value: object) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "schema" and isinstance(child, (dict, bool)):
                    Draft202012Validator.check_schema(child)
                check_inline(child)
        elif isinstance(value, list):
            for child in value:
                check_inline(child)
    check_inline(spec)
    ids = []
    for path, item in spec["paths"].items():
        for method, op in item.items():
            if method not in METHODS:
                continue
            name = op.get("operationId")
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                raise Failure("spec-operation-id-required")
            if op.get("x-fern-ignore"):
                raise Failure("spec-ignored-operation")
            ids.append(name)
    if not ids or len(ids) != len(set(ids)):
        raise Failure("spec-empty-or-duplicate-operations")
    return spec


def smoke_contract(spec: dict, operation_id: str, response: object) -> None:
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    entry = operations(spec).get(operation_id)
    if not entry:
        raise Failure("smoke-operation-missing")
    method, path, op = entry
    params = spec["paths"][path].get("parameters", []) + op.get("parameters", [])
    if (method != "GET" or op.get("x-tplinkctl-read-only") is not True
            or "{" in path or any(p.get("required") or "$ref" in p for p in params)
            or op.get("requestBody")):
        raise Failure("smoke-requires-parameterless-read-only-get")
    schema = op.get("responses", {}).get("200", {}).get("content", {}).get("application/json", {}).get("schema")
    if schema is None:
        raise Failure("smoke-json-response-schema-required")
    resource = Resource.from_contents(spec, default_specification=DRAFT202012)
    registry = Registry().with_resource("urn:tplinkctl:openapi", resource)
    pointer = "/paths/" + path.replace("~", "~0").replace("/", "~1")
    pointer += "/get/responses/200/content/application~1json/schema"
    Draft202012Validator({"$ref": "urn:tplinkctl:openapi#" + pointer}, registry=registry).validate(response)


def patch_once(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    if text.count(old) != 1:
        raise Failure("pinned-source-patch-anchor-changed")
    path.write_text(text.replace(old, new))


def prepare_source(source: Path, spec: Path, pins: dict) -> None:
    # The public source packager reads these untracked internal fixtures. Both
    # receive this run's input, never Cloudflare's API or a packaged baseline.
    shutil.copyfile(spec, source / "openapi.json")
    shutil.copyfile(spec, source / "packages/cloudflare-fern-config/fern/openapi.json")
    script = source / "packages/cloudflare-forge-sdk-ts/scripts/build-generator-image.sh"
    # Upstream assumes a version tag is immutable. Pin every source-image use;
    # preserve its wrapper generation and Fern's official local tag convention.
    patch_once(script, 'base="fernapi/fern-${lang}-sdk:${version}"',
               'base="fernapi/fern-${lang}-sdk:${version}"\nsource_image="' + pins["generator_image"] + '"')
    for old, new in [
        ('docker pull "${base}"', 'docker pull "${source_image}"'),
        ('docker create "${base}"', 'docker create "${source_image}"'),
        ('orig_entrypoint=$(docker inspect "${base}"', 'orig_entrypoint=$(docker inspect "${source_image}"'),
        ('FROM ${base}', 'FROM ${source_image}'),
    ]:
        patch_once(script, old, new)


def verify_bundle(bundle: Path, spec: dict) -> dict:
    for name in ["openapi.json", "sdk/index.ts", "sdk/Client.ts", "sdk/sdk-map.json"]:
        if not (bundle / name).is_file() or not (bundle / name).stat().st_size:
            raise Failure("forge-output-missing")
    if json.loads((bundle / "openapi.json").read_text()) != spec:
        raise Failure("forge-final-spec-drift")
    sdk_map = json.loads((bundle / "sdk/sdk-map.json").read_text())
    expected = operations(spec)
    if set(sdk_map) != set(expected):
        raise Failure("forge-sdk-map-coverage-drift")
    for name, (method, path, _) in expected.items():
        entry = sdk_map[name]
        if entry.get("httpMethod") != method or entry.get("path") != path:
            raise Failure("forge-sdk-map-route-drift")
        if not isinstance(entry.get("accessor"), list) or not isinstance(entry.get("method"), str):
            raise Failure("forge-sdk-map-callsite-missing")
    return sdk_map


def docs(bundle: Path, spec: dict, sdk_map: dict) -> None:
    lines = ["# Generated tplinkctl HTTP reference", "", "Generated from the finalized OpenAPI and Forge sdk-map. Not a runtime safety gate.", ""]
    for name, (method, path, op) in sorted(operations(spec).items()):
        entry = sdk_map[name]
        call = ".".join(["client", *entry["accessor"], entry["method"]])
        lines.extend([f"## `{name}`", "", f"`{method} {path}`", "", op.get("summary", ""), "", f"SDK: `{call}(...)`", ""])
        metadata = {k: v for k, v in op.items() if k.startswith("x-tplinkctl-")}
        lines.extend(["```json", json.dumps(metadata, indent=2, sort_keys=True), "```", ""])
    (bundle / "api-reference.md").write_text("\n".join(lines))


def generate(args: argparse.Namespace, pins: dict, report: dict) -> None:
    if sys.platform != "linux":
        raise Failure("generation-requires-linux-docker")
    import fcntl

    output = args.output.absolute()
    if output.exists() or output.is_symlink():
        raise Failure("output-exists-use-new-versioned-directory")
    if not output.parent.is_dir():
        raise Failure("output-parent-must-exist")
    # Fern mutates its local image tag. Serialize this integration for the user.
    lock_path = Path.home() / ".cache" / "tplinkctl-forge.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w") as lock, tempfile.TemporaryDirectory(prefix=".forge-stage-", dir=output.parent) as temporary:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        stage = Path(temporary)
        home, tmp = stage / "home", stage / "tmp"
        home.mkdir(mode=0o700)
        tmp.mkdir(mode=0o700)
        env = {"PATH": os.defpath + ":" + os.environ.get("PATH", ""), "HOME": str(home),
               "TMPDIR": str(tmp), "CI": "true", "NO_COLOR": "1", "SCARF_NO_ANALYTICS": "true",
               "FERN_TYPESCRIPT_SHARD_COUNT": "1", "FERN_NO_VERSION_REDIRECTION": "1"}

        def run(phase: str, command: list[str], cwd: Path = stage, timeout: int = 600) -> str:
            report["phase"] = phase
            result = subprocess.run(command, cwd=cwd, env=env, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, timeout=timeout)
            # Never emit upstream logs: schema values, environment, absolute
            # paths and Fern's inherited process environment may appear there.
            text = result.stdout.decode(errors="replace")
            if result.returncode:
                report["exit_code"] = result.returncode
                report["diagnostics"] = [label for marker, label in [
                    ("ENOENT", "missing-file"), ("All checks passed", "fern-validation-passed"),
                    ("error TS", "typescript-errors"), ("Cannot connect", "docker-unreachable"),
                    ("ERR_PNPM", "pnpm-error"), ("unresolved spec ops", "sdk-map-unresolved"),
                    ("ENOSPC", "disk-full"), ("permission denied", "permission-denied"),
                ] if marker in text]
                raise Failure("subprocess-failed-see-phase-and-diagnostics")
            report.setdefault("passed", []).append(phase)
            return text.strip()

        run("docker-preflight", ["docker", "info", "--format", "{{.ServerVersion}}"])
        source = stage / "forge"
        run("fetch", ["git", "init", str(source)])
        run("fetch-pin", ["git", "fetch", "--depth=1", pins["repository"], pins["revision"]], source)
        run("checkout-pin", ["git", "checkout", "--detach", "FETCH_HEAD"], source)
        if run("verify-pin", ["git", "rev-parse", "HEAD"], source) != pins["revision"]:
            raise Failure("forge-revision-mismatch")
        input_path = stage / "input.json"
        shutil.copyfile(args.spec, input_path)
        spec = validate_spec(input_path)
        response = json.loads(args.smoke_response.read_text())
        smoke_contract(spec, args.smoke_operation, response)
        prepare_source(source, input_path, pins)
        pnpm = ["npx", "--yes", "pnpm@" + pins["pnpm"]]
        run("install-locked", pnpm + ["--filter", "@cloudflare/forge-transformer-sdk-ts...", "install", "--frozen-lockfile"], source)
        run("build-forge", pnpm + ["--filter", "@cloudflare/forge-transformer-sdk-ts", "build"], source)
        bundle = stage / "bundle"
        cli = source / "packages/cloudflare-forge-transformer-sdk-ts/dist/cli.js"
        run("generate", ["node", str(cli), str(input_path), "--out", str(bundle)])
        report["phase"] = "verify-output"
        sdk_map = verify_bundle(bundle, spec)
        dump(bundle / "package.json", {"private": True, "type": "module"})
        shutil.copyfile(CONFIG / "tsconfig.json", bundle / "tsconfig.json")
        typescript = source / "node_modules/typescript/bin/tsc"
        run("typescript-compile", ["node", str(typescript), "--project", str(bundle / "tsconfig.json"),
                                   "--typeRoots", str(source / "node_modules/@types")])
        run("sdk-mock-http", ["node", str(CONFIG / "smoke.mjs"), str(bundle),
                              args.smoke_operation, str(args.smoke_response.absolute())])
        docs(bundle, spec, sdk_map)
        report.update({"phase": "publish", "operation_count": len(sdk_map),
                       "input_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
                       "status": "passed"})
        dump(bundle / "evidence.json", report)
        # Only a fully validated directory is visible. Never merge or overwrite
        # a previous successful output. Rename stays on the same filesystem.
        if output.exists() or output.is_symlink():
            raise Failure("output-appeared-during-generation")
        bundle.rename(output)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["validate", "generate"])
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", type=Path, help="Safe JSON summary, never raw subprocess logs")
    parser.add_argument("--smoke-operation", default="router_status")
    parser.add_argument("--smoke-response", type=Path, default=CONFIG / "smoke-response.json")
    args = parser.parse_args(argv)
    pins = json.loads((CONFIG / "pins.json").read_text())
    report = {"status": "failed", "phase": "validate", "pins": pins}
    report_allowed = False
    try:
        # A report cannot clobber input, output, fixtures, or tool configuration.
        if args.report:
            report_path = args.report.absolute()
            if report_path.exists() or report_path.is_symlink():
                raise Failure("report-exists-use-new-path")
            protected = [args.spec.resolve(), args.smoke_response.resolve(), CONFIG.resolve()]
            if args.output:
                protected.append(args.output.absolute())
            if any(report_path == p or p in report_path.parents for p in protected):
                raise Failure("unsafe-report-path")
            report_allowed = True
        spec = validate_spec(args.spec)
        if args.command == "validate":
            report.update({"status": "passed", "operation_count": len(operations(spec))})
        else:
            if args.output is None:
                raise Failure("output-required")
            generate(args, pins, report)
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = str(exc) if isinstance(exc, Failure) else type(exc).__name__
    if report_allowed and args.report and not args.report.exists() and not args.report.is_symlink():
        # Exclusive creation also prevents a racing invocation overwriting it.
        with args.report.open("x") as handle:
            handle.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
