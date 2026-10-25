"""Deterministic OpenAPI 3.1.2 generation, offline and without router access.

Usage: python -m tplink_admin.openapi > docs/openapi.json
       python -m tplink_admin.openapi --check docs/openapi.json
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import re
import sys

from . import __version__, registry


def document() -> dict:
    paths = {}
    schemas = {"Error": registry.ERROR_SCHEMA, "Plan": registry.PLAN_SCHEMA}
    local = []
    for item in registry.tools():
        if item["local_only"]:
            local.append(item)
            continue
        name = item["name"]
        route = item["http"]
        request = registry.http_input(item)
        schemas[name + "Input"] = deepcopy(item["input_schema"])
        schemas[name + "Output"] = registry.http_output(item)
        path_names = re.findall(r"\{(\w+)\}", route["path"])
        operation = {
            "operationId": name, "summary": item["description"],
            "tags": [route["path"].split("/")[2]],
            "x-tplinkctl-read-only": item["read_only"],
            "x-tplinkctl-risk": item["risk"],
            "x-tplinkctl-profile": item["profiles"],
            "x-tplinkctl-plan-operation": item["plan_operation"],
            "x-tplinkctl-rollback": item["rollback_contract"],
            "x-tplinkctl-command": item["command"],
            "x-tplinkctl-input-schema": {"$ref": "#/components/schemas/" + name + "Input"},
            "parameters": [],
            "responses": {
                "200": {"description": "Plan or redacted command result",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/" + name + "Output"}}}},
            },
        }
        for status in sorted(set(registry.ERROR_STATUS.values())):
            kinds = [k for k, s in registry.ERROR_STATUS.items() if s == status]
            operation["responses"][str(status)] = {
                "description": ", ".join(kinds),
                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}},
            }
        for key, prop in request["properties"].items():
            if key in path_names or route["method"] == "get":
                operation["parameters"].append({"name": key, "in": "path" if key in path_names else "query",
                    "required": key in path_names or key in request.get("required", []), "schema": prop})
        if route["method"] != "get":
            request["properties"] = {k: v for k, v in request["properties"].items() if k not in path_names}
            request["required"] = [k for k in request.get("required", []) if k not in path_names]
            schemas[name + "Request"] = request
            operation["requestBody"] = {"required": True, "content": {"application/json": {
                "schema": {"$ref": "#/components/schemas/" + name + "Request"}}}}
        paths.setdefault(route["path"], {})[route["method"]] = operation
    return {
        "openapi": "3.1.2", "jsonSchemaDialect": "https://json-schema.org/draft/2020-12/schema",
        "info": {"title": "tplinkctl local API", "version": __version__, "description": (
            "Bearer-authenticated, server-profile-controlled router resources. Mutations require a single-use "
            "plan_id plus confirm=true. Plans expire after 120 seconds by default and are invalid after restart. "
            "Plans bind actor, profile, operation, arguments and target. Changed router state requires replanning. "
            "No automatic rollback or exactly-once delivery guarantee after an upstream failure. "
            "Non-loopback exposure requires an explicit bind and a trusted TLS proxy or encrypted tunnel.")},
        "servers": [{"url": "http://127.0.0.1:8765", "description": "Default loopback listener"}],
        "security": [{"bearerAuth": []}], "paths": paths,
        "components": {"securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}}, "schemas": schemas},
        "x-tplinkctl-local-only": local,
        "x-tplinkctl-error-status": registry.ERROR_STATUS,
        "x-tplinkctl-upstream-error-status": {"auth": 502},
    }


def render() -> str:
    return json.dumps(document(), indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", type=Path, help="Fail if checked-in JSON differs from deterministic generation")
    args = parser.parse_args(argv)
    output = render()
    if args.check:
        if not args.check.exists() or args.check.read_text(encoding="utf-8") != output:
            print("OpenAPI artifact is stale; regenerate with python -m tplink_admin.openapi", file=sys.stderr)
            return 1
        return 0
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
