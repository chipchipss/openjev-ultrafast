"""读 reports/m2.json：五判据 + 抽取 manifest 摘要（5.4 收官用）。"""
import json
import sys

r = json.load(open(sys.argv[1], encoding="utf-8"))
s = r["summary"]
keep = ("total", "pass", "fail", "unknown", "error", "quadrants",
        "failure_modes", "decision_total", "teacher_shadow_total",
        "budget", "per_round")
print(json.dumps({k: s.get(k) for k in keep}, ensure_ascii=False, indent=1))
print("acceptance:", json.dumps(r.get("acceptance"), ensure_ascii=False, indent=1))
m = r.get("extract_manifest")
print("manifest:", json.dumps(m, ensure_ascii=False, indent=1)[:2200] if m else None)
