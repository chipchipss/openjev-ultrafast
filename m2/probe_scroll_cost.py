"""What does a `scroll_to_named_target` campaign COST the page it scrolls?

b15 (2026-10-09, `reports/real-1009-b15-fixs2-1009-164410.json`) bought r116 and lost r114:
r114 passed in b14 via `search_type` -> `search_submit` (2 steps, docs.djangoproject.com/
.../intro/tutorial01), and in b15 the SAME task spent all 4 allowed scrolls on
www.djangoproject.com/ and then the model chose BLOCKED. The hypothesis this probe tests:

  scrolling down un-indexes the control that was going to solve the task,
  because the snapshot only records viewport-visible actions (`snapshot.js:124` rect filter)
  and the Django search box lives in the header at the top of the page.

If that is the mechanism, the campaign is not "wasted steps" - it is a one-way door,
and the guard must be about reversibility (scroll_top exists, `snapshot.js:163`), not about
how many steps we are willing to burn.

Reads, per site, at each scroll count:
  - which floor skill would fire (route order matters: explicit_target, scroll_to_named_target, search_type)
  - is a text input (kind='fill') still in the INDEXED action set?
  - does the quoted target appear in the viewport text at all?
  - is the target indexed as a click action?
Zero model calls: navigate + observe + dispatch the wheel directly (same event as the product,
`browser.py:456`: mouseWheel at 550,650, deltaY=560).
Run ONLY when no batch is in flight (it drives the owned headless Chrome on :9222).
"""
import io
import json
import os
import re
import sys
import time
from urllib.parse import urlparse

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, ".")
os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:2080")
os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:2080")

from jev_ultrafast.browser import Browser, StalePage                 # noqa: E402
from jev_ultrafast import skills as S                                # noqa: E402

DELTA = 560
MAX_SCROLLS = 4          # _PATH_SCROLL_MAX

CASES = [
    # (name, url, goal as written in m2/tasks_real.jsonl, href needle, quoted target)
    ("r114 django home  [LOST in b15]", "https://www.djangoproject.com/",
     "From the Django homepage, open the page titled 'Writing your first Django app, part 1'.",
     "intro/tutorial01", "Writing your first Django app, part 1"),
    ("r116 rust home    [GAIN in b15]", "https://doc.rust-lang.org/",
     "From the Rust documentation home, open 'The Cargo Book'.",
     "/cargo/", "The Cargo Book"),
    ("r113 peps home    [PASS in b15]", "https://peps.python.org/",
     "Open PEP 8, 'Style Guide for Python Code'.",
     "pep-0008", "Style Guide for Python Code"),
    ("r105 github home  [FAIL]", "https://github.com/",
     "Open the Releases page of the pytorch/pytorch repository.",
     "pytorch/pytorch/releases", "Releases"),
    ("r122 rfc home     [FAIL]", "https://www.rfc-editor.org/",
     "Open RFC 9110, 'HTTP Semantics'.",
     "rfc9110", "HTTP Semantics"),
]


def observe_settled(b, tries=6):
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


def inventory(p):
    idx = S.indexed_actions(p.get("actions") or [])
    kinds = {}
    fills = []
    for _, a in idx:
        kinds[a.get("kind")] = kinds.get(a.get("kind"), 0) + 1
        if a.get("kind") == "fill":
            fills.append(str(a.get("label") or "")[:40])
    return kinds, fills


def target_state(p, needle, quoted):
    idx = S.indexed_actions(p.get("actions") or [])
    lab_hit = []
    for i, a in idx:
        if a.get("kind") != "click":
            continue
        h = "/".join(str(a.get("href") or "").lower().split("%2f"))
        lab = str(a.get("label") or "").lower()
        if needle.lower().lstrip("/") in h or " ".join(quoted.lower().split()) in lab:
            lab_hit.append((i, str(a.get("label") or "")[:44]))
    txt = (p.get("text") or "").lower()
    return lab_hit, ("PHRASE-IN-VIEWPORT-TEXT" if " ".join(quoted.lower().split()) in txt else "-"), \
        ("NEEDLE-IN-TEXT" if needle.lower().lstrip("/") in txt else "-")


for name, url, goal, needle, quoted in CASES:
    print("=" * 78)
    print("%s\n  %s" % (name, url))
    b = None
    try:
        b = Browser(url)
        p = observe_settled(b)
        for k in range(0, MAX_SCROLLS + 1):
            kinds, fills = inventory(p)
            hits, ph, nd = target_state(p, needle, quoted)
            fired = {}
            for fn in ("explicit_target", "scroll_to_named_target", "search_type", "first_result"):
                try:
                    r = getattr(S, fn)(p, goal, [])
                    fired[fn] = (r or {}).get("skill") if r else None
                except Exception as e:                                  # noqa: BLE001
                    fired[fn] = "EXC %s" % type(e).__name__
            first_firing = None
            for fn in ("explicit_target", "scroll_to_named_target", "search_type"):
                if fired[fn]:
                    first_firing = fn
                    break
            scr = p.get("scroll") or {}
            print("  scroll %-2s y=%-6s h=%-6s kinds=%s" % (k, scr.get("y"), scr.get("height"), kinds))
            print("           fills=%s" % (fills or "NONE"))
            print("           target indexed=%s  %s  %s" % (hits[:2] or "no", ph, nd))
            print("           skills -> %s   | first in route order: %s" % (fired, first_firing))
            if k == MAX_SCROLLS:
                break
            try:
                b.call("Input.dispatchMouseEvent", type="mouseWheel",
                       x=550, y=650, deltaX=0, deltaY=DELTA)
            except Exception as e:                                      # noqa: BLE001
                print("     wheel FAILED: %s: %s" % (type(e).__name__, e))
                break
            time.sleep(0.35)
            try:
                p = observe_settled(b)
            except Exception as e:                                      # noqa: BLE001
                print("     observe FAILED: %s: %s" % (type(e).__name__, e))
                break
        # does a scroll_top control exist to undo the campaign?
        # NOTE: `scroll` is NOT in KIND_TO_OP, so `indexed_actions()` filters the synthetic scroll
        # controls out (skills.py:53).  Reading them from `indexed_actions` returns [] on every page
        # and would have "proved" the campaign is irreversible — measured 2026-10-09, the
        # instrument was wrong, not the page.  Read the RAW actions / `_scroll_ctl` instead.
        tops = [a.get("id") for a in (p.get("actions") or [])
                if a.get("kind") == "scroll"]
        print("  at the bottom of the campaign, scroll controls = %s  (undo available: %s)"
              % (tops, bool(S._scroll_ctl(p, "top") or S._scroll_ctl(p, "up"))))
    except Exception as e:                                              # noqa: BLE001
        print("  EXC %s: %s" % (type(e).__name__, e))
    finally:
        if b is not None:
            b.close()
