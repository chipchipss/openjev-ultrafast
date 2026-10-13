"""Measure why r103 (Stack Overflow) fills the search box twice and never submits.

Zero model calls: navigate + observe + call the skill functions directly, driving the
product's own act()/observe() so the settle waits are the real ones.
Run ONLY when no batch is in flight (owned headless Chrome on :9222).

b16 (`logs/real-1009-b16-fixu-1009-184158/r103.jsonl`) is 2 steps, both `fill Search`,
then correct_abandon:

    1 fill Search | TYPE_TEXT | https://stackoverflow.com/questions
    2 fill Search | TYPE_TEXT | https://stackoverflow.com/questions

Three candidate causes, measured here rather than assumed:
  (a) the fill never takes (React combobox: value not committed, so `search_type` re-fires),
  (b) the fill DOES take but `search_submit` finds no submit affordance in the index,
  (c) the second fill is the same decision because `search_submit`'s page-state dedupe
      (Fix O) thinks the search was already submitted.
"""
import io
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, ".")
os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:2080")
os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:2080")

from jev_ultrafast.browser import Browser, StalePage        # noqa: E402
from jev_ultrafast import skills as S                        # noqa: E402

GOAL = "Search Stack Overflow for 'python slice step' and open the first question in the results."
URL = "https://stackoverflow.com/questions"


def observe(b, tries=8):
    p = None
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


def dump(b, p, hist, label):
    idx = S.indexed_actions(p.get("actions") or [])
    by_choice = {c: a for c, a in idx}
    fills = [(a.get("id"), str(a.get("label") or "")[:36], a.get("role"))
             for _, a in idx if a.get("kind") == "fill"]
    clicks = [(a.get("id"), str(a.get("label") or "")[:36], a.get("role"))
              for _, a in idx if a.get("kind") == "click"]
    scr = (p.get("scroll") or {})
    print("  [%s] url=%s y=%s h=%s" % (label, p.get("url"), scr.get("y"), scr.get("height")))
    print("      fills  = %s" % (fills or "NONE",))
    print("      clicks = %s" % (clicks[:12],))
    for name in ("search_type", "search_submit", "entity_fill", "first_result",
                 "explicit_target", "form_submit", "first_action_floor"):
        d = getattr(S, name)(p, GOAL, hist)
        if isinstance(d, dict):
            picked = by_choice.get(str(d.get("target")))
            print("      %-14s -> op=%s choice=%s label=%r text=%r"
                  % (name, d.get("operation"), d.get("choice"),
                     str((picked or {}).get("label") or "")[:38], d.get("text")))
        else:
            print("      %-14s -> %s" % (name, "None" if d is None else d))
    rt = S.route(p, GOAL, hist)
    if rt:
        picked = by_choice.get(str(rt.get("target")))
        print("      route -> skill=%s op=%s label=%r text=%r"
              % (rt.get("skill"), rt.get("operation"),
                 str((picked or {}).get("label") or "")[:38], rt.get("text")))
    else:
        print("      route -> None")
    return rt


b = None
try:
    b = Browser(URL)
    p = observe(b)
    print("=== A. start page ===")
    print("  _goal_query=%r  goal_phrases=%r" % (S._goal_query(GOAL), S.goal_phrases(GOAL)))
    rt = dump(b, p, [], "start")
    hist = []
    if not rt:
        print("  floor abstains on the start page -- nothing to replay")
        sys.exit(0)

    print("=== B. execute the floor decision (tick 2 of the real run) ===")
    action = next(a for _, a in S.indexed_actions(p.get("actions") or []) if a.get("id") == rt["choice"])
    b.act(action, p, text=rt.get("text"))
    p2 = observe(b)
    hist.append({"step": 1, "kind": action["kind"], "action": action.get("label"),
                 "choice": action.get("id"), "skill": rt.get("skill"),
                 "text": rt.get("text"), "page_changed": None, "url": p["url"]})
    print("      window value now = %r" % (b.evaluate(
        "(() => {const c=window.__jevFast?.nodes.get(%s); return c ? c.value : null})()"
        % action.get("node")),))
    dump(b, p2, hist, "after-fill")

    print("=== C. execute the next floor decision, twice (does it repeat?) ===")
    cur, cur_hist = p2, hist
    for tick in (2, 3):
        rt = S.route(cur, GOAL, cur_hist)
        if not rt:
            print("  tick %d: route -> None (model takes over)" % tick)
            break
        action = next(a for _, a in S.indexed_actions(cur.get("actions") or [])
                      if a.get("id") == rt["choice"])
        print("  tick %d: %s %s %r" % (tick, rt.get("skill"), rt.get("operation"),
                                       action.get("label")))
        cur_hist = cur_hist + [{"step": tick, "kind": action["kind"],
                                 "action": action.get("label"), "choice": action.get("id"),
                                 "skill": rt.get("skill"), "text": rt.get("text"),
                                 "page_changed": None, "url": cur["url"]}]
        b.act(action, cur, text=rt.get("text"))
        cur = observe(b)
        dump(b, cur, cur_hist, "tick%d" % tick)

    print("=== D. what the results page offers first_result ===")
    b2 = Browser("https://stackoverflow.com/search?q=python+slice+step")
    p3 = observe(b2)
    print("  _FIRST_RESULT_RE on goal = %s" % bool(S._FIRST_RESULT_RE.search(GOAL)))
    dump(b2, p3, [], "results")
    b2.close()
finally:
    for x in (b,):
        try:
            if x:
                x.close()
        except Exception:
            pass
