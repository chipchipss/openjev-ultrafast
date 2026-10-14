"""After a `scroll_top` undo, is the header search box actually back in the index?

Pre-registered criterion 3 of #47 (Fix T) said r114 would go
`scroll x(2~4) -> top -> search_type -> search_submit -> arrive`. The first real run
(`reports/one-r114-1009-172047.json`, `logs/one-r114-1009-172047/r114.jsonl`) shows the undo
firing (`step5 SCROLL_TOP page_changed=True`) and then the **whole floor abstaining** on the
post-undo page — the model chose BLOCKED (0.71). `m2/probe_scroll_cost.py` measured that a
fresh load at y=0 indexes `fills=['Search']`, and b14 solved this task in 2 steps via
`search_type`, so either:

  (a) the post-undo snapshot is NOT the top-of-page (wheel scroll of deltaY=-scrollY is one
      synthetic event; `scroll` has no settle cap — `browser.py:318` SETTLE_CAPS_MS covers
      click/select/fill only — so an in-flight smooth scroll is read as if it were done), or
  (b) the page really is at y=0 but the box is not re-indexed (sticky/hidden header, focus,
      lazy DOM change), or
  (c) a skill guard mutes `search_type` (`_STUCK` after a no-effect tick, `done`, value check).

This probe replays the PRODUCT's exact act sequence — 4x scroll_down then the skill's own
scroll_top, via `Browser.act`, re-observing the way the agent does — and prints, per tick:
y/height, the indexed kinds, the indexed fill labels, whether the raw action set carries a
search-labelled input that `indexed_actions` dropped, what `_goal_query`/`search_type` return, and
what `skills.route` decides. It also observes TWICE after the undo (immediate, then after a
quiet wait) because (a) predicts exactly that difference.

Zero model calls. Drives the owned headless Chrome only (`Browser` pins the CDP endpoint and
asserts profile ownership). Run only when no batch is in flight.
"""
import io
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, ".")
os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:2080")
os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:2080")

from jev_ultrafast.browser import Browser, StalePage                 # noqa: E402
from jev_ultrafast import skills as S                                 # noqa: E402

URL = "https://www.djangoproject.com/"
GOAL = ("From the Django homepage, open the page titled "
        "'Writing your first Django app, part 1'.")
MAX_TICKS = 10


def observe(b, tries=6):
    for attempt in range(tries):
        try:
            p = b.observe(screenshot=False)
        except StalePage:
            time.sleep(0.4 * (attempt + 1))
            continue
        if S.indexed_actions(p.get("actions") or []):
            return p
        time.sleep(0.5 * (attempt + 1))
    return p


def report(b, p, history, label):
    idx = S.indexed_actions(p.get("actions") or [])
    kinds, fills = {}, []
    for _, a in idx:
        kinds[a.get("kind")] = kinds.get(a.get("kind"), 0) + 1
        if a.get("kind") == "fill":
            fills.append(str(a.get("label") or "")[:34])
    raw_fills = [(str(a.get("id")), str(a.get("label") or "")[:34])
                 for a in (p.get("actions") or []) if a.get("kind") == "fill"]
    scr = p.get("scroll") or {}
    print("  %-10s y=%-6s h=%-6s fp=%s…  omitted=%s"
          % (label, scr.get("y"), scr.get("height"), (p.get("fingerprint") or "")[:12],
             p.get("omitted_actions")))
    print("             indexed kinds=%s fills=%s" % (kinds, fills or "NONE"))
    print("             RAW fill actions=%s" % (raw_fills or "NONE"))
    print("             scroll controls=%s"
          % [a.get("id") for a in (p.get("actions") or []) if a.get("kind") == "scroll"])
    q = S._goal_query(GOAL)
    st = S.search_type(p, GOAL, history)
    rt = S.route(p, GOAL, history)
    print("             _goal_query=%r" % (q,))
    print("             search_type -> %s" % ((st or {}).get("skill") or "None"))
    print("             route      -> skill=%s op=%s choice=%s"
          % ((rt or {}).get("skill"), (rt or {}).get("operation"), (rt or {}).get("choice")))
    # 走公开读接口：内层形状变了（{"task":…,"ticks":{…}}），手抄形状的打印下一次就会静默读到空
    print("             _STUCK=%s counters=%s" % ({k: S.stuck_ticks(k) for k in list(S._STUCK)},
                                                  S.stuck_counters()))
    return rt


b = None
try:
    b = Browser(URL)
    p = observe(b)
    history = []
    print("=" * 78)
    print("r114 replay: %s\n  goal=%s" % (URL, GOAL))
    for tick in range(MAX_TICKS):
        print("-" * 78)
        rt = report(b, p, history, "tick %d" % (tick + 1))
        if rt is None:
            print("  floor abstained -> model would decide. stop.")
            break
        act_id = rt["choice"]
        action = next((a for a in p["actions"] if a.get("id") == act_id), None)
        if action is None:
            print("  decision choice %r not in raw actions. stop." % act_id)
            break
        before_fp = p["fingerprint"]
        try:
            b.act(action, p, text=rt.get("text"))
        except Exception as e:                                        # noqa: BLE001
            print("  act %r FAILED: %s: %s" % (act_id, type(e).__name__, e))
            break
        history.append({"step": tick + 1, "action": action.get("label"),
                        "kind": action.get("kind"), "choice": act_id,
                        "skill": rt.get("skill"), "text": rt.get("text"),
                        "page_changed": None})
        time.sleep(0.35)
        try:
            p = observe(b)
        except Exception as e:                                        # noqa: BLE001
            print("  observe FAILED: %s: %s" % (type(e).__name__, e))
            break
        history[-1]["page_changed"] = p["fingerprint"] != before_fp
        if action.get("kind") == "scroll":
            imy = (p.get("scroll") or {}).get("y")
            time.sleep(1.2)
            try:
                p2 = observe(b)
                y2 = (p2.get("scroll") or {}).get("y")
                if y2 != imy:
                    print("  TIMING: y right after the wheel = %s, after 1.2s quiet = %s"
                          " -> the product read a still-moving page" % (imy, y2))
                    p = p2
            except Exception as e:                                    # noqa: BLE001
                print("  re-observe FAILED: %s: %s" % (type(e).__name__, e))
    print("=" * 78)
finally:
    if b is not None:
        b.close()
