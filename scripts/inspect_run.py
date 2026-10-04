"""Summarise a per-task report dir: quadrant, steps, model_calls, final_url.

Usage: python scripts/inspect_run.py reports/baseline-1004-1659
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    d = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    rows = []
    for f in sorted(d.glob("*.json")):
        if f.name.startswith("m1-"):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        res = data.get("results", [{}])[0].get("result")
        tid = f.stem
        if not isinstance(res, dict):
            rows.append((tid, "ERROR", "-", "-", "-", "-"))
            continue
        m = res.get("meta", {})
        rows.append((tid, res.get("result", "?"), res.get("quadrant") or "-",
                     m.get("steps"), m.get("model_calls"),
                     (res.get("evidence", {}).get("final_url") or "-")[:44]))
    print("%-6s %-5s %-16s %4s %6s  %s" % ("task", "res", "quadrant", "stp", "calls", "final_url"))
    print("-" * 104)
    for r in rows:
        print("%-6s %-5s %-16s %4s %6s  %s" % r)
    zero = [r for r in rows if r[3] == 0]
    dead = [r for r in rows if "chrome-error" in str(r[5])]
    print()
    print("steps==0      : %d  %s" % (len(zero), " ".join(r[0] for r in zero)))
    print("chrome-error  : %d  %s" % (len(dead), " ".join(r[0] for r in dead)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())