"""Zero-model probe: what does the floor see on rfc-editor's search RESULTS page?

n004's rounds now hinge on one low-confidence MODEL click landing on the
'RFC   9110 :' row (freeze rounds: PASS when it did, FAIL when it kept pressing
'Submit search'). This checks whether the row is even in `actions` and what
route() proposes there -- no model, one page shape.

Run:  C:/Users/Administrator/miniconda3/envs/jev/python.exe scripts/probe_n004_result_page.py
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("HTTPX_PROXY", "http://127.0.0.1:2080")

from jev_ultrafast import skills                      # noqa: E402
from jev_ultrafast.browser import Browser, StalePage   # noqa: E402

URL = "https://www.rfc-editor.org/search/?q=RFC+9110"
GOAL = "Open RFC 9110 from the RFC index."

# the shape round 3 (m1-baseline-1008-1336) had reached when it started looping
HIST = [
    {"kind": "fill", "choice": "e13", "operation": "TYPE_TEXT", "action": "Search RFCs",
     "text": "RFC 9110", "outcome": {"url_changed": True}},
    {"kind": "click", "choice": "e15", "operation": "CLICK", "action": "Submit search",
     "text": None, "outcome": {"url_changed": True}},
    {"kind": "click", "choice": "e10", "operation": "CLICK", "action": "Submit search",
     "text": None, "outcome": {"url_changed": False}},
]


def main() -> int:
    b = Browser(URL)
    try:
        page = b.observe(screenshot=False)
    except StalePage as e:
        print("observe failed:", e)
        b.close()
        return 2
    print(f"url   {page['url']}")
    print(f"title {page.get('title')!r}")
    print(f"actions={len(page['actions'])}  page_height={page.get('height')}")

    print("\n-- rows whose label mentions 9110 --")
    for a in page["actions"]:
        if "9110" in (a.get("label") or ""):
            print(f"  {a['id']:>5} {a['kind']:<6} {a.get('label')!r}")

    print("\n-- every CLICK whose score ladder could see the phrase --")
    for a in page["actions"][:40]:
        lab = (a.get("label") or "").strip()
        if lab:
            print(f"  {a['id']:>5} {a['kind']:<6} {lab[:58]!r}")

    print("\n-- floor --")
    d = skills.route(page, GOAL, HIST)
    print("  route() ->", json.dumps(d, ensure_ascii=False)[:200] if d else None)

    print("\n-- individual skills --")
    for fn in (skills.explicit_target, skills.first_result, skills.goto_path,
               skills.goal_reached, skills.search_type, skills.search_submit):
        try:
            r = fn(page, GOAL, HIST)
        except Exception as e:                          # noqa: BLE001
            r = f"EXC {type(e).__name__}: {e}"
        print(f"  {fn.__name__:<16} -> "
              f"{json.dumps(r, ensure_ascii=False)[:150] if isinstance(r, dict) else r}")
    b.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
