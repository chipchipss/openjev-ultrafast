"""Why did explicit_target abstain on n004's results page inside the round?

Offline replay: take the *real* step history from the failing freeze round
(m1-baseline-1008-1336 / n004) and feed it, together with the live results page,
to skills.route(). The same page with a 3-entry history picks the row at conf
1.0 (probe_n004_result_page.py), so if route() abstains with the real history the
suppression is a history guard -- then bisect it entry by entry.

Run:  C:/Users/Administrator/miniconda3/envs/jev/python.exe scripts/probe_n004_history_replay.py
"""
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
os.environ.setdefault("HTTPX_PROXY", "http://127.0.0.1:2080")

from jev_ultrafast import skills                        # noqa: E402
from jev_ultrafast.browser import Browser, StalePage     # noqa: E402

URL = "https://www.rfc-editor.org/search/?q=RFC+9110"
GOAL = "Open RFC 9110 from the RFC index."
TRACES = [REPO / "reports/baseline-1008-1336/logs/n004/n004.jsonl",
          REPO / "reports/baseline-1008-1331/logs/n004/n004.jsonl"]


def steps_of(path: Path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("event") != "step":
            continue
        out.append({"step": e.get("step"), "kind": e.get("kind"),
                    "choice": e.get("choice"), "action": e.get("action"),
                    "text": e.get("text"), "operation": e.get("operation"),
                    "page_changed": (e.get("outcome") or {}).get("url_changed"),
                    "url": e.get("url")})
    return out


def main() -> int:
    trace = next((p for p in TRACES if p.exists()), None)
    if trace is None:
        print("no trace found in", TRACES)
        return 2
    hist = steps_of(trace)
    print(f"trace {trace.name}: {len(hist)} steps")
    for h in hist:
        print(f"   {h['step']} {h['kind']:<6} {h['choice']:<5} {h['action']!r} "
              f"text={h['text']!r} url_changed={h['page_changed']}")

    b = Browser(URL)
    try:
        page = b.observe(screenshot=False)
    except StalePage as e:
        print("observe failed:", e)
        b.close()
        return 2
    rows = [a["id"] for a in page["actions"] if "9110" in (a.get("label") or "")]
    print(f"\npage: actions={len(page['actions'])} row ids={rows}")

    print("\n-- route() with no history  ->",
          (skills.route(page, GOAL, []) or {}).get("choice"))
    d = skills.route(page, GOAL, hist)
    print("-- route() with the round's history ->",
          json.dumps(d, ensure_ascii=False)[:160] if d else None)

    if d is None and rows:
        print("\n-- bisect: drop history entries from the end --")
        for n in range(len(hist), 0, -1):
            dd = skills.route(page, GOAL, hist[:n])
            print(f"   hist[:{n}] -> "
                  f"{(dd or {}).get('choice') if dd else None}"
                  f"{'  skill=' + str(dd.get('skill')) if dd else ''}")
            if dd:
                print(f"   => the guard is entry #{n} "
                      f"({hist[n-1]['kind']} {hist[n-1]['action']!r})")
                break
    b.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
