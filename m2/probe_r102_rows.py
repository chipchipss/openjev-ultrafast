"""Zoom into the arxiv results page: which rows are indexed vs. which are in the DOM,
and what the first indexed clickable label actually is (r102's failure shape)."""
import io
import json
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, ".")
os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:2080")
os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:2080")

from jev_ultrafast.browser import Browser, StalePage               # noqa: E402
from jev_ultrafast import skills as S                              # noqa: E402

URL = "https://arxiv.org/search/?query=Attention+Is+All+You+Need&searchtype=all"
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


b = Browser(URL)
try:
    p = observe(b)
    idx = S.indexed_actions(p.get("actions") or [])
    print("url=%s indexed=%d doc_h=%s scroll_y=%s"
          % (p.get("url"), len(idx), (p.get("scroll") or {}).get("height"),
             (p.get("scroll") or {}).get("y")))
    print("---- ALL indexed actions ----")
    for i, a in idx:
        print("   %-4s %-7s %-46s %s" % (i, a.get("kind"), str(a.get("label") or "")[:46],
                                         str(a.get("href") or "")[:56]))
    # how many arxiv-result rows exist in the live DOM vs how many are indexed
    dom = b.evaluate("""(() => {
      const rows = [...document.querySelectorAll('li.arxiv-result')];
      const firstLink = r => { const a = r.querySelector('p.list-title a[href]');
        return a ? {label: (a.innerText||'').trim(), href: a.getAttribute('href'),
                    top: Math.round(a.getBoundingClientRect().top)} : null; };
      const links = rows.map(firstLink).filter(Boolean);
      return {rows: rows.length, links: links.length,
              visibleRows: links.filter(l => l.top >= -20 && l.top < innerHeight).length,
              firstLinks: links.slice(0, 5)};
    })()""")
    print("---- live DOM arxiv rows ----")
    print(json.dumps(dom, ensure_ascii=False, indent=1)[:1800])
    hist = [{"step": 1, "kind": "fill", "action": "Search", "choice": "e5",
             "skill": "search_type", "text": "Attention Is All You Need",
             "outcome": {"url_changed": True}},
            {"step": 2, "kind": "click", "action": "Search", "choice": "e8",
             "skill": "search_submit", "outcome": {"url_changed": True}}]
    for name in ("first_result", "explicit_target", "goal_reached", "route"):
        d = getattr(S, name)(p, GOAL, hist)
        if isinstance(d, dict):
            picked = {c: a for c, a in idx}.get(str(d.get("target")))
            print("%-14s -> skill=%s op=%s choice=%s label=%r"
                  % (name, d.get("skill"), d.get("operation"), d.get("choice"),
                     str((picked or {}).get("label") or "")[:46]))
        else:
            print("%-14s -> %s" % (name, d))
finally:
    b.close()
