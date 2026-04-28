#!/usr/bin/env python3
"""Download enough of the router UI to run route/endpoint discovery locally."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import urljoin

import requests


IMPORT_RE = re.compile(r"""["']\./([^"']+\.js)["']""")


def fetch(session: requests.Session, url: str, path: Path) -> str:
    response = session.get(url, timeout=20)
    response.raise_for_status()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(response.text, encoding="utf-8")
    return response.text


def main() -> int:
    parser = argparse.ArgumentParser(description="Mirror TP-Link UI bundles for local discovery.")
    parser.add_argument("--host", default="http://192.168.0.1")
    parser.add_argument("--out", default=".", help="output directory")
    parser.add_argument("--depth", type=int, default=1, help="import-follow depth")
    args = parser.parse_args()

    out = Path(args.out)
    session = requests.Session()
    root = args.host.rstrip("/") + "/webpages/"
    html = fetch(session, urljoin(root, "index.html"), out / "index.html")

    pending = [match.group(1) for match in IMPORT_RE.finditer(html)]
    seen: set[str] = set()
    for _ in range(args.depth + 1):
        next_pending: list[str] = []
        for rel in pending:
            if rel in seen:
                continue
            seen.add(rel)
            text = fetch(session, urljoin(root, rel), out / rel)
            next_pending.extend(match.group(1) for match in IMPORT_RE.finditer(text))
        pending = next_pending

    print(f"Downloaded {len(seen)} JS bundles into {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
