"""r103 zoom C: on the SO /questions page, after the product fill, are there ANY
question links indexed before the wall (could a tag-page route reach a question row)?
Also dump the tag page rows. Zero model."""
import io
import json
import os
import re
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, ".")
os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:2080")
os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:2080")

from jev_ultrafast.browser import Browser, StalePage               # noqa: E402
from jev_ultrafast import skills as S                              # noqa: E402

GOAL = "Search Stack Overflow for 'python slice step' and open the first question in the results."


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


b = Browser("https://stackoverflow.com/questions/tagged/python+slice?tab=newest")
try:
    p = observe(b)
    idx = S.indexed_actions(p.get("actions") or [])
    q = [(i, str(a.get("label") or "")[:52], str(a.get("href") or "")[:56])
         for i, a in idx if re.search(r"/questions/\d+", str(a.get("href") or ""))]
    print("[tag page] indexed=%d question-links=%d" % (len(idx), len(q)))
    for r in q[:8]:
        print("    e%s %r -> %s" % r)
    # click the first question row and check first_result/goal_reached on the landing page
    if q:
        first = next(a for _, a in idx if str(a.get("href") or "").startswith("/questions/")
                     and re.search(r"/questions/\d+[^/]", str(a.get("href") or "") + " "))
        b.act(first, p)
        p2 = observe(b)
        print("landed: url=%s title=%r" % (p2.get("url"), str(p2.get("title") or "")[:50]))
        hist = [{"step": 2, "kind": "click", "action": str(first.get("label") or ""),
                 "choice": first.get("id"), "skill": "first_result",
                 "outcome": {"url_changed": True}, "url": p2.get("url")}]
        for name in ("first_result", "goal_reached"):
            d = getattr(S, name)(p2, GOAL, hist)
            print("  %s -> %s" % (name, (d.get("operation"), d.get("skill")) if d else d))
        from jev_ultrafast.evaluator import _eval_assertion
        ok, _ = _eval_assertion({"type": "url_matches",
                                 "pattern": r"stackoverflow\.com/questions/\d+"},
                                {"url": p2.get("url") or ""}, [])
        ok2, _ = _eval_assertion({"type": "text_contains", "value": "slice"},
                                 {"text": p2.get("text") or ""}, [])
        print("  assertion url_matches -> %s ; text_contains slice -> %s" % (ok, ok2))
finally:
    b.close()
