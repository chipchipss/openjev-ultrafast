"""r102 zoom: on the driven results page, click the result row the 'first result'
position rule would pick (arXiv:2610.10952 = e19) -- does the assertion page differ?
Also: what does the r105-shape route() see after arrival? Zero model."""
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

GOAL = "Search arXiv for the paper 'Attention Is All You Need' and open its abstract page."


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


b = Browser("https://arxiv.org/search/physics?query=Attention+Is+All+You+Need&searchtype=all&abstracts=show&order=-announced_date_first&size=50")
try:
    p = observe(b)
    idx = S.indexed_actions(p.get("actions") or [])
    print("url=%s indexed=%d" % (p.get("url"), len(idx)))
    first = next((a for _, a in idx if re.search(r"/abs/\d", str(a.get("href") or ""))), None)
    print("first indexed abs link:", first and (first.get("id") is None, str(first.get("label") or "")[:40],
                                                str(first.get("href") or "")[:60]))
    if first:
        b.act(first, p)
        p2 = observe(b)
        print("landed: url=%s title=%r" % (p2.get("url"), str(p2.get("title") or "")[:50]))
        hist = [{"step": 3, "kind": "click", "action": str(first.get("label") or ""),
                 "choice": "e19", "skill": "first_result",
                 "outcome": {"url_changed": True},
                 "url": p2.get("url")}]
        gr = S.goal_reached(p2, GOAL, hist)
        print("goal_reached on landed page ->",
              (gr.get("operation"), gr.get("skill")) if gr else gr)
        # would the assertion pass? evaluator itself:
        from jev_ultrafast.evaluator import _eval_assertion
        ok, traces = _eval_assertion(
            {"type": "url_matches", "pattern": r"arxiv\.org/abs/1706\.03762"},
            {"url": p2.get("url") or ""}, [])
        print("assertion url_matches 1706.03762 ->", ok)
finally:
    b.close()
