"""r102: pick the Relevance select (e17's row, value for relevance) then click Go (e18),
then measure whether 1706.03762 appears indexed. The select action needs 'value' =
the option value to submit; check what act() sends for kind=select. Zero model."""
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
    rel = next((a for _, a in idx if a.get("kind") == "select"
                and "Relevance" in str(a.get("label") or "")), None)
    print("relevance row:", rel and (rel.get("id"), rel.get("value"), rel.get("label")))
    b.act(rel, p)
    p2 = observe(b)
    print("url after select:", p2.get("url"))
    idx2 = S.indexed_actions(p2.get("actions") or [])
    go = next((a for _, a in idx2 if str(a.get("label") or "") == "Go"), None)
    if go:
        b.act(go, p2)
        p3 = observe(b)
        print("url after Go:", p3.get("url"))
        idx3 = S.indexed_actions(p3.get("actions") or [])
        arts = [(i, str(a.get("label") or "")[:40], str(a.get("href") or "")[:52])
                for i, a in idx3 if re.search(r"/abs/1706\.03762", str(a.get("href") or ""))]
        print("1706.03762 indexed:", len(arts), arts[:2])
        print("indexed=%d" % len(idx3))
        print("---- first 20 ----")
        for i, a in idx3[:20]:
            print("   %-4s %-7s %-44s %s" % (i, a.get("kind"),
                  str(a.get("label") or "")[:44], str(a.get("href") or "")[:48]))
finally:
    b.close()
