"""Can a SCROLL bring the goal's target into the indexed action set?

The shape probe (`m2/probe_homepage_shape.py`, 2026-10-09) split the "首页出不去" family into
two diseases, and only one of them is reachable from here:
  r105 github.com/            needle in the whole DOM = 0   -> target NOT on the page
  r122 rfc-editor.org/        needle in the whole DOM = 0   -> target NOT on the page
  r116 doc.rust-lang.org/stable/  needle in DOM = 1, in FIRST VIEWPORT = 0, at +1812px
                              -> the link is there, the snapshot just cannot see it
A snapshot indexes viewport-visible actions only (memory item 20), so for the third shape no
score tier in `explicit_target` can help; the only thing that can is making the page move.
This probe answers, per site, with the SAME wheel event the product issues
(`browser.py:456`: mouseWheel at 550,650, deltaY = the control's delta):
  after at most N scrolls, does the target become an INDEXED click action, and at which
  scroll count?  A site where it never becomes indexed is not a viewport problem.
Zero model calls: navigate + observe + dispatch the wheel directly.
Run ONLY when no batch is in flight (it drives the owned headless Chrome on :9222).
"""
import io
import json
import os
import sys
import time
from urllib.parse import urlparse

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, ".")
os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:2080")
os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:2080")

from jev_ultrafast.browser import Browser, StalePage                 # noqa: E402
from jev_ultrafast import skills as S                                # noqa: E402

DELTA = 560          # the product's own scroll_down delta
MAX_SCROLLS = 6      # _PATH_SCROLL_MAX's neighbourhood; more than a model would ever pay

CASES = [
    # (name, start url, goal, href needle (path fragment), label phrase the goal quotes, max scrolls)
    ("r116 rust doc root", "https://doc.rust-lang.org/",
     "From the Rust documentation home, open 'The Cargo Book'.",
     "/cargo/", "The Cargo Book", MAX_SCROLLS),
    ("r102 arxiv results page",
     "https://arxiv.org/search/?query=Attention+Is+All+You+Need&searchtype=all",
     "Search arXiv for the paper 'Attention Is All You Need' and open its abstract page.",
     "1706.03762", "Attention Is All You Need", 4),
    ("r105 github root", "https://github.com/",
     "Open the Releases page of the pytorch/pytorch repository.",
     "pytorch/pytorch/releases", "Releases", MAX_SCROLLS),
    ("r122 rfc-editor root", "https://www.rfc-editor.org/",
     "Open RFC 9110, 'HTTP Semantics'.",
     "rfc9110", "HTTP Semantics", MAX_SCROLLS),
    ("r118 gnu home", "https://www.gnu.org/",
     "From the GNU homepage, open the 'Bash Reference Manual' node index page.",
     "bash/manual/html_node", "Bash Reference Manual", MAX_SCROLLS),
    # 反向对照：这两题今天**是 PASS**，本刀不许把它们从"用站内搜索"拐成"先滚"。
    # 要的是读数，不是猜想：它们的引号目标在起点页上到底滚不滚得出来。
    ("r113 peps home (PASS today)", "https://peps.python.org/",
     "Open PEP 8, 'Style Guide for Python Code'.",
     "pep-0008", "Style Guide for Python Code", MAX_SCROLLS),
    ("t002 selenium home (PASS today)", "https://www.selenium.dev/",
     "On selenium.dev, expand the 'Documentation' dropdown in the navigation.",
     "/documentation", "Documentation", MAX_SCROLLS),
    ("s002 docs.python (PASS today)", "https://docs.python.org/3/",
     "Use the site search on docs.python.org to find the page about 'asyncio'.",
     "library/asyncio.html", "asyncio", MAX_SCROLLS),
]


def observe_settled(b, tries=6):
    """Product-shaped init: bounded backoff on StalePage, and a snapshot with zero real
    actions is treated as 'not rendered yet' rather than as a measurement."""
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


def indexed_clicks(p):
    host = urlparse(p.get("url") or "").netloc.lower()
    out = []
    for i, a in S.indexed_actions(p.get("actions") or []):
        if a.get("kind") != "click":
            continue
        h = str(a.get("href") or "")
        hv = "/".join(h.lower().split("%2f"))
        out.append((i, str(a.get("label") or "")[:50], h, hv, host))
    return out


def hit(rows, needle, label):
    n = needle.lower().lstrip("/")
    lab = " ".join(label.lower().split("_"))
    return [r for r in rows if n in r[3] or lab in r[1].lower()]


for name, url, goal, needle, label, max_scrolls in CASES:
    print("=" * 78)
    print("%s\n  %s" % (name, url))
    b = None
    try:
        b = Browser(url)
        p = observe_settled(b)
        rows = indexed_clicks(p)
        print("  landed=%s  actions=%d  scroll=%s"
              % (p.get("url"), len(rows), json.dumps(p.get("scroll"))))
        found = hit(rows, needle, label)
        print("  at scroll 0: indexed=%d  target indexed=%s %s"
              % (len(found), bool(found),
                 ("<- %r -> %s" % (found[0][1], found[0][2][:60]) if found else "")))
        # 起点页上"谁先说话"——本刀抢的就是 scroll 到 search/点击 之间这一拍
        for fn in ("scroll_to_named_target", "search_type"):
            f = getattr(S, fn, None)
            try:
                r = f(p, goal, []) if f is not None else "(no such function)"
            except Exception as e:                                          # noqa: BLE001
                r = "EXC %s: %s" % (type(e).__name__, e)
            print("    at scroll 0: %s -> %s"
                  % (fn, None if r is None else "%s %s" % (r.get("operation"), r.get("choice"))))
        for k in range(1, max_scrolls + 1):
            try:
                b.call("Input.dispatchMouseEvent", type="mouseWheel",
                       x=550, y=650, deltaX=0, deltaY=DELTA)
            except Exception as e:                                      # noqa: BLE001
                print("  scroll %d FAILED: %s: %s" % (k, type(e).__name__, e))
                break
            time.sleep(0.35)
            try:
                p = observe_settled(b)
            except Exception as e:                                      # noqa: BLE001
                print("  observe after scroll %d FAILED: %s: %s" % (k, type(e).__name__, e))
                break
            rows = indexed_clicks(p)
            found = hit(rows, needle, label)
            print("  at scroll %d: actions=%d  target indexed=%s %s  y=%s"
                  % (k, len(rows), bool(found),
                     ("<- %r -> %s" % (found[0][1], found[0][2][:60]) if found else ""),
                     (p.get("scroll") or {}).get("y")))
            if found:
                print("  -> REACHABLE after %d scroll(s) of %d px" % (k, DELTA))
                break
        else:
            print("  -> NOT REACHABLE within %d scrolls: the target is not a below-the-fold "
                  "link on this page" % max_scrolls)
        for fn in ("scroll_to_named_target", "explicit_target", "goto_path", "first_result"):
            try:
                r = getattr(S, fn)(p, goal, [])
            except Exception as e:                                      # noqa: BLE001
                r = "EXC %s: %s" % (type(e).__name__, e)
            print("  %s at final page -> %s" % (fn, r))
    except Exception as e:                                              # noqa: BLE001
        print("  EXC %s: %s" % (type(e).__name__, e))
    finally:
        if b is not None:
            b.close()
