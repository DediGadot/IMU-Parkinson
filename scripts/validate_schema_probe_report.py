#!/usr/bin/env python3
"""Validate a locally completed external-route schema-probe report.

This is a route-agnostic post-approval preflight for local scratch schema
notes. It prints only redacted pass/fail metadata and does not record protected
rows, target values, local paths, credentials, approval identities, or model
evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from validate_ppmi_verily_schema_probe_report import validate_report  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route-id", required=True)
    parser.add_argument("--report", required=True, help="Path to a completed local .md or .txt report")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        result = validate_report(Path(args.report), route_id=args.route_id)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
