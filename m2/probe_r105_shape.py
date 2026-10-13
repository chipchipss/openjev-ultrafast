"""Measure github's two page shapes before cutting #25's r105 half.

Zero model calls: navigate + observe + call the skill functions directly.
Run ONLY when no batch is in flight (it drives the owned headless Chrome on :9222).

b16 (`logs/real-1009-b16-fixu-1009-184158/r105.jsonl`) ends at one step:
`first_action_floor` CLICKs node 12 = "Open Enter your email" (the footer email disclosure),
page_changed=False, and the model then BLOCKs (0.596). Two things are unmeasured behind that:
(a) what else the homepage indexes -- is there a search control the floor should prefer, and
(b) whether a search for `pytorch/pytorch` even answers without a login.
"""
import io
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, ".")
os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:2080")
os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:2080")

from jev_ultrafast.browser import Browser, StalePage       # noqa: E402
from jev_ultrafast import skills as S                       # noqa: E402

GOAL = "Open the Releases page of the pytorch/pytorch repository."


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


def show(b, p, history, label):
    idx = S.indexed_actions(p.get("actions") or [])
    by_choice = {c: a for c, a in idx}
    kinds, clicks, fills = {}, [], []
    for _, a in idx:
        kinds[a.get("kind")] = kinds.get(a.get("kind"), 0) + 1
        if a.get("kind") == "click":
            clicks.append((a.get("id"), str(a.get("label") or "")[:40], a.get("role")))
        if a.get("kind") == "fill":
            fills.append((a.get("id"), str(a.get("label") or "")[:40], a.get("role")))
    raw_fills = [(a.get("id"), str(a.get("label") or "")[:40], a.get("role"))
                 for a in (p.get("actions") or []) if a.get("kind") == "fill"]
    print("  [%s] url=%s y=%s h=%s omitted=%s" %
          (label, p.get("url"), (p.get("scroll") or {}).get("y"),
           (p.get("scroll") or {}).get("height"), p.get("omitted_actions")))
    print("      indexed kinds=%s" % (kinds,))
    print("      indexed clicks   = %s" % (clicks[:10],))
    print("      indexed fills    = %s" % (fills or "NONE",))
    print("      RAW fills        = %s" % (raw_fills or "NONE",))
    print("      _goal_query=%r" % (S._goal_query(GOAL),))
    print("      goal_phrases=%r" % (S.goal_phrases(GOAL),))
    for fn in list(S.SKILLS) + [S.first_action_floor]:
        name = fn.__name__
        try:
            d = fn(p, GOAL, history)
        except Exception as e:
            d = "EXC %s: %s" % (type(e).__name__, e)
        if isinstance(d, dict):
            picked = by_choice.get(str(d.get("target")))
            print("      %-22s -> op=%s choice=%s target=%s label=%r text=%r"
                  % (name, d.get("operation"), d.get("choice"), d.get("target"),
                     str((picked or {}).get("label") or "")[:44], d.get("text")))
        elif d is not None:
            print("      %-22s -> %s" % (name, d))
    rt = S.route(p, GOAL, history)
    rtp = by_choice.get(str((rt or {}).get("target"))) if rt else None
    print("      route -> skill=%s op=%s label=%r"
          % ((rt or {}).get("skill"), (rt or {}).get("operation"),
             str((rtp or {}).get("label") or "")[:44]))
    return rt


browsers = []
try:
    b = Browser("https://github.com/")
    browsers.append(b)
    p = observe(b)
    print("=== A. homepage as r105 sees it ===")
    show(b, p, [], "home")

    print("=== B. after one scroll_down (does a repo/releases link enter?) ===")
    ctl = S._scroll_ctl(p, "down")
    if ctl:
        b.act(ctl, p)
        p2 = observe(b)
        show(b, p2, [], "scrolled")
    else:
        print("  no scroll control indexed")

    print("=== C. click the header search button: does a fillable box appear? ===")
    opener = next((a for _, a in S.indexed_actions(p.get("actions") or [])
                   if a.get("kind") == "click"
                   and str(a.get("label") or "").lower().startswith("search or jump")), None)
    hist = [{"skill": "first_action_floor", "kind": "click", "choice": opener.get("id")}] if opener else []
    if opener is None:
        print("  no 'Search or jump to' control indexed")
    else:
        print("  opener id=%s label=%r" % (opener.get("id"), opener.get("label")))
        b.act(opener, p)
        p5 = observe(b)
        show(b, p5, hist, "after-open")
        q = S._goal_query(GOAL)
        for guess in (None, "pytorch/pytorch"):
            st = S.search_type(p5, GOAL, hist) if guess is None else None
            print("      search_type(goal) -> %s" % ((st or {}).get("skill") or "None"))
            ent = S.entity_fill(p5, GOAL, hist)
            print("      entity_fill       -> %s text=%r"
                  % ((ent or {}).get("skill") or "None", (ent or {}).get("text")))
            sel = S.select_first(p5, GOAL, hist)
            print("      select_first      -> %s" % ((sel or {}).get("skill") or "None"))
            opts = [(a.get("id"), str(a.get("label") or "")[:40], a.get("role"))
                    for a in (p5.get("actions") or []) if (a.get("role") or "") == "option"]
            print("      role=option rows  = %s" % (opts[:8] or "NONE",))
            break

    print("=== D. github's own search results page for the repo id ===")
    b2 = Browser("https://github.com/search?q=pytorch%2Fpytorch&type=repositories")
    browsers.append(b2)
    p3 = observe(b2)
    show(b2, p3, [], "search")
    print("=== E. the repository page itself (what the assertion wants one hop from) ===")
    b3 = Browser("https://github.com/pytorch/pytorch")
    browsers.append(b3)
    p4 = observe(b3)
    show(b3, p4, [], "repo")
finally:
    for x in browsers:
        try:
            x.close()
        except Exception:
            pass
