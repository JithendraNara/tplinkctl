#!/usr/bin/env python3
"""Compatibility wrapper for the installable tplinkctl CLI."""

from tplink_admin.cli import run as main


if __name__ == "__main__":
    raise SystemExit(main())
