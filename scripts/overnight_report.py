"""一次性产物：2026-10-07 当晚的盘点打印器，**不是闸门也不是工具**。

它按 1007 的 glob 读报告并印出那一晚的结论（n001 的"模型能力项"判断被 C2b 诊断推翻、
n004 的真因是初始早读）。两条结论的权威记录在 `m1/m1-log.md` 与 `m2/real-log.md`，
本文件留着只为可追溯；n004/n001 在今晚的冻结 19/19×3（`reports/m1-baseline-1011-2251/2258/2304.json`）里全 PASS。
"""
import json, glob, os

print("=" * 62)
print("OVERNIGHT RESULTS - 2026-10-07")
print("=" * 62)

print()
print("1) FROZEN ROUNDS (3 rounds, code frozen after C2b fix)")
today = sorted(glob.glob('reports/m1-baseline-1007-*.json'))
for f in today:
    d = json.load(open(f, encoding='utf-8'))
    s = d['summary']
    fails = [r['task_id'] for r in d.get('results', [])
             if isinstance(r.get('result'), dict) and r['result'].get('result') == 'FAIL']
    print(f"  {os.path.basename(f)}: {s['pass']}/{s['total']} fp={s['false_positive']} fails={fails}")

print()
print("2) WHAT FIXED n001 (was: 3-round stable FAIL, judged 'model capability item')")
print("  Overnight diagnosis REVERSED that: the agent hit docs.python.org on STEP 1.")
print("  goal_reached missed it: C1 title lacks 'python documentation'; C2 URL says")
print("  'docs' not 'documentation'. Agent then clicked the logo away and looped.")
print("  Fix: C2b expands the goal head word to URL abbreviations (documentation ->")
print("  docs), host-only match (python.org's own /doc/ intermediate page must not fire).")

print()
print("3) n004 REGRESSION WATCH (round 3): floor chain went Subscribe->Create account")
print("  (a wrong turn, page_changed=False stopped it), then model BLOCKED at 0.76 -")
print("  the known SPA-early-read gap (next on the plan: settle detection). Not a")
print("  C2b regression: rounds 1-2 had n004 PASS, variance is the SPA timing.")

print()
print("4) SCORE: 19 + 19 + 18 = 56/57 over three frozen rounds, fp=0 throughout.")
print("   Project-best. n001 fixed; n004 remains the last FAIL (2/3 rounds it passed).")
