"""上游 jev-ultrafast 的 Google Flights 任务，跑在我们的栈上（本地 decider-2b + 技能层）。

上游公开口径（docs/performance.md）：TypeSafe jev-1.13.0 + Mercury 助手，
Zürich→London 单程，中位 7.092s，3/3 通过；中位决策延迟 178ms。

本脚本：
  - 用上游完全相同的 URL 与 goal
  - 用上游的独立验证函数（逐字段核对 one_way/origin/destination/date/results）
  - 计时边界对齐上游：从"首页观察后的第一次预测"到"被接受的 DONE"
用法：python m4a/run_flights_ours.py [--out reports/flights-ours-v2.json]
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import statistics
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FLIGHTS_URL = "https://www.google.com/travel/flights?hl=en"


def resolve_date(spec: str) -> dt.date:
    """任务日期。默认"今天 + 21 天"。

    上游 goal 硬编码 2026-09-20，该日期现已过去（系统日期 2026-09-30）——
    Google Flights 会静默夹到最近可订日（实测：点 Sep 20 日格无任何效果，
    点 Sep 30 立刻生效 → Departure = "Wed, Sep 30"），date/year/results
    三项检查因此永远不可能通过。上游那份 7.092s/3-3 是在该日期仍在未来时测的。
    --date 可显式指定 YYYY-MM-DD；传 auto 或留空走默认。
    """
    if spec and spec != "auto":
        return dt.date.fromisoformat(spec)
    return dt.date.today() + dt.timedelta(days=21)


def build_goal(d: dt.date) -> str:
    return (
        f"Find one-way flights from Zurich to London on "
        f"{d.strftime('%B')} {d.day}, {d.year}, for one adult in economy. "
        f"Stop when matching flight options are visible. "
        f"Do not select or book a flight."
    )
# 上游公开检查 2：Wikipedia 打开 Gödel 不完备性定理条目（其性能文档 2.798s）
WIKI_URL = "https://en.wikipedia.org/wiki/Main_Page"
WIKI_GOAL = "Open the Wikipedia article on Gödel's incompleteness theorems."


def verify_wiki(page: dict) -> dict:
    url = page.get("url") or ""
    ok = "G%C3%B6del%27s_incompleteness_theorems" in url or "Gödel's_incompleteness_theorems" in url
    return {"passed": ok, "checks": {"article_url": ok}, "final_url": url}


def verify(page: dict, d: dt.date) -> dict:
    """上游 verify() 的等价实现（我们的 page dict：url/actions/text）。"""
    parsed = urlparse(page.get("url") or "")
    encoded = parse_qs(parsed.query).get("tfs", [""])[0]
    try:
        date_in_url = d.isoformat().encode() in base64.urlsafe_b64decode(
            encoded + "=" * (-len(encoded) % 4))
    except ValueError:
        date_in_url = False
    actions = page.get("actions") or []
    values = {(a.get("label") or "").strip(): a.get("value") for a in actions}
    flights = [a.get("label") for a in actions if "Select flight" in (a.get("label") or "")]
    short = f"{d.strftime('%a, %b')} {d.day}"      # Google Departure 字段的值格式
    long_ = f"{d.strftime('%A, %B')} {d.day}"      # 结果行里的日期串
    checks = {
        "search_page": parsed.hostname == "www.google.com"
        and parsed.path == "/travel/flights/search",
        "one_way": values.get("Change ticket type. One way") == "One way",
        "origin": values.get("Where from?") == "Zürich",
        "destination": values.get("Where to?") == "London",
        "date": values.get("Departure") == short,
        "year": date_in_url or f"departing {d.isoformat()}" in (page.get("text") or ""),
        "results": bool(flights) and all(long_ in f for f in flights),
    }
    return {"passed": all(checks.values()), "checks": checks, "visible_flights": flights}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="flights", choices=("flights", "wikipedia"))
    ap.add_argument("--out", default="")
    ap.add_argument("--date", default="auto",
                    help="航班日期 YYYY-MM-DD；auto=今天+21 天（默认）。"
                         "上游硬编码的 2026-09-20 已成过去，Google 会夹到最近可订日。")
    args = ap.parse_args()
    target_date = resolve_date(args.date)
    if args.task == "wikipedia":
        url, goal, verifier = WIKI_URL, WIKI_GOAL, verify_wiki
        domain, out_default = "en.wikipedia.org", "reports/wiki-ours.json"
    else:
        url, goal = FLIGHTS_URL, build_goal(target_date)
        verifier = lambda page: verify(page, target_date)   # noqa: E731
        domain, out_default = "www.google.com", "reports/flights-ours-v2.json"
    print(f"[{args.task}] date={target_date.isoformat()} goal={goal[:80]}...", flush=True)
    out = args.out or out_default
    spec = {"task_id": args.task, "goal": goal, "domain": domain,
            "category": "search", "budget": {"steps": 20}}
    from jev_ultrafast.agent import Agent  # noqa: WPS433

    agent = Agent(url=url, goals=goal, task_spec=spec, screenshots=False)
    t0 = time.perf_counter()
    try:
        for _ in agent.run():
            pass
    except Exception as e:                                  # noqa: BLE001
        print(f"[{args.task}] agent loop raised: {type(e).__name__}: {e}", flush=True)
    wall = time.perf_counter() - t0

    state = agent.state
    decs = state.get("decisions") or []
    lats = [d.get("latency_ms") for d in decs if isinstance(d.get("latency_ms"), (int, float))]
    result = {
        "status": state.get("status"),
        "wall_s": round(wall, 2),
        "steps": len(state.get("history") or []),
        "n_decisions": len(decs),
        "decision_lat_p50": int(statistics.median(lats)) if lats else None,
        "decision_lat_max": int(max(lats)) if lats else None,
        "final_url": (state.get("page") or {}).get("url"),
        "history": [
            {"step": h.get("step"), "kind": h.get("kind"), "action": h.get("action"),
             "text": h.get("text"), "page_changed": h.get("page_changed"),
             "outcome": (h.get("outcome") or {}).get("status")}
            for h in (state.get("history") or [])
        ],
        "decisions": [
            {"i": i, "choice": d.get("choice"), "skill": d.get("skill"),
             "operation": d.get("operation"), "target": d.get("target"),
             "reason": d.get("reason"),
             # 判断 provider 质量用：laya 前置/回退的门槛就靠这两个数调（缺陷#38）。
             "confidence": d.get("confidence"),
             "op_conf": d.get("operation_confidence"),
             # P0：结果页等不到时的现场（url/元素数/flight 命中/是否重载过），
             # 用于当场区分"外部没渲染"与"我们没看见"。
             "diag": d.get("diag"),
             "pre": {k: v for k, v in (d.get("pre_execute") or {}).items()
                     if k in ("loop_detection", "validator", "validator_retry",
                              "policy", "done_guard", "step_budget")}}
            for i, d in enumerate(decs)
        ],
        "target_date": target_date.isoformat(),
    }
    result["verification"] = verifier(state.get("page") or {})
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: result[k] for k in
                      ("status", "wall_s", "steps", "n_decisions",
                       "decision_lat_p50", "decision_lat_max", "final_url")},
                     ensure_ascii=False))
    print("verification:", json.dumps(result["verification"]["checks"], ensure_ascii=False))
    print("PASSED:", result["verification"]["passed"])
    agent.close()


if __name__ == "__main__":
    main()
