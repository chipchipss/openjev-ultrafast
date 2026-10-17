"""r103 zoom D: on a real question page, does the 'slice' text clause pass? Pick the
'Slice the extension .txt' question and evaluate both clauses there. Zero model."""
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
from jev_ultrafast.evaluator import _eval_assertion

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


for url in ("https://stackoverflow.com/questions/79771175/slice-the-extension-txt-from-file-names-duplicate",
            "https://stackoverflow.com/questions/79604226/performance-of-list-extend-slice-vs-islice"):
    print("=" * 70)
    b = Browser(url)
    try:
        p = observe(b)
        print("url=%s" % p.get("url"))
        print("title=%r" % str(p.get("title") or "")[:60])
        print("text_chars=%d" % len(p.get("text") or ""))
        ok1, _ = _eval_assertion({"type": "url_matches",
                                  "pattern": r"stackoverflow\.com/questions/\d+"},
                                 {"url": p.get("url") or ""}, [])
        ok2, _ = _eval_assertion({"type": "text_contains", "value": "slice"},
                                 {"text": p.get("text") or ""}, [])
        print("url_matches -> %s ; text_contains 'slice' -> %s" % (ok1, ok2))
        hist = [{"step": 2, "kind": "click", "action": "question", "choice": "e1",
                 "skill": "first_result", "outcome": {"url_changed": True}, "url": p.get("url")}]
        gr = S.goal_reached(p, GOAL, hist)
        print("goal_reached ->", (gr.get("operation"), gr.get("skill")) if gr else gr)
    finally:
        b.close()
