#!/usr/bin/env python3
"""Verify a DALIL export bundle: python scripts/verify_export.py <bundle.json>

Exit 0 = all stored hashes match content; exit 1 = mismatch/invalid.
Remember: hashes detect post-export edits, they are not a digital signature.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.core.export import verify_bundle  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    try:
        with open(sys.argv[1], encoding="utf-8") as f:
            bundle = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"FAIL: cannot read bundle: {e}")
        return 1
    verdict = verify_bundle(bundle)
    print(f"schema: {verdict.get('schema_version')}")
    if verdict["ok"]:
        print("OK: all stored hashes match the bundle content")
        print("(hashes only detect edits; not a signature — see bundle['integrity']['limits'])")
        return 0
    print("FAIL: bundle does not verify")
    for pr in verdict["problems"]:
        print(f"  - {pr}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
