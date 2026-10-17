"""r102 final shape probe: the /search/physics results page in the LIVE browser --
what does the 'arXiv:2610.10952' first-row click land on, and does the r102
search_type flow even reach a results page where the target row exists on page 1?
Already measured: it does not (rank absent from page 1 of 50). This probe measures
whether the sort select (e16 = Relevance) is a reachable control and what it yields.
Zero model."""
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
    # the sort select row
    sort_rows = [(i, a.get("label"), a.get("value")) for i, a in idx
                 if "Relevance" in str(a.get("label") or "")]
    print("sort-select rows:", sort_rows)
    # pick the select action with value indicating relevance
    rel = next(((i, a) for i, a in idx
                if a.get("kind") == "select" and "Relevance" in str(a.get("label") or "")), None)
    print("relevance select row:", rel and (rel[0], rel[1].get("id")))
    if rel:
        b.act(rel[1], p)
        p2 = observe(b)
        print("after sort select: url=%s" % p2.get("url"))
        idx2 = S.indexed_actions(p2.get("actions") or [])
        import re as _re
        arts = [(i, str(a.get("label") or "")[:40], str(a.get("href") or "")[:52])
                for i, a in idx2 if _re.search(r"/abs/1706\.03762", str(a.get("href") or ""))]
        print("1706.03762 in indexed after Relevance sort:", len(arts), arts[:2])
        # submit the Go button
        go = next(((i, a) for i, a in idx2 if str(a.get("label") or "") == "Go"), None)
        print("Go control:", go and (go[0], go[1].get("id")))
finally:
    b.close()
