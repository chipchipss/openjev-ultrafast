"""t17 MEASURE-FIRST probe: what does each floor CLICK candidate actually DO on the
three start pages? (2026-10-18, zero model calls.)

Contract (t17): the t15 gate was rolled back (47871e9) because it blocked s005's
legitimate two-hop ('Web APIs' -> /docs/Web/API -> explicit_target reaches 'Fetch API').
Before re-landing any gate, the three start pages must be measured for CLICK EFFECT:

  (a) github.com footer email disclosure ('Open Enter your email') + rfc-editor.org
      'Subscribe to new RFCs' = measured dead-ends (zero effect, wrong target);
  (b) developer.mozilla.org 'Web APIs' = a goal-adjacent intermediate hop that
      leads toward the Fetch API page.

For each candidate: label/href/role/floor score, then click and record
page_changed + final URL. ONE FRESH PAGE PER CANDIDATE (a click mutates the page;
independent loads keep every reading comparable). This loop is O(candidates) page
loads -- bounded at 6 per page by MAX_PER_PAGE.

Pattern: m2/probe_shape_5rows.py (owned Chrome on :9222, proxy :2080, stopped after).
Run ONLY when no batch is in flight (it drives the owned headless Chrome on :9222).
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
from jev_ultrafast import skills as S                      # noqa: E402

R105_GOAL = "Open the Releases page of the pytorch/pytorch repository."
N004_GOAL = "Open RFC 9110 from the RFC index."
S005_GOAL = "Search MDN for 'fetch' and open the Fetch API reference page."

MAX_PER_PAGE = 6

# The candidates t17 names, verbatim labels from t4/t15 (measured shapes).
PAGES = [
    ("https://github.com/", R105_GOAL,
     ["Open Enter your email", "Start a free enterprise trial", "Product", "Search or jump to"]),
    ("https://www.rfc-editor.org/", N004_GOAL,
     ["Subscribe to new RFCs", "Datatracker", "RFC index", "Search"]),
    ("https://developer.mozilla.org/zh-CN/", S005_GOAL,
     ["Web APIs", "HTML", "CSS", "JavaScript", "Search MDN"]),
]


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


def indexed_clicks(p):
    return [(i, a) for i, a in S.indexed_actions(p.get("actions") or [])
            if a.get("kind") == "click"]


def one_reading(url, goal, want, done):
    """Fresh page -> find the wanted candidate -> click -> measure. One reading."""
    if done >= MAX_PER_PAGE:
        return None
    b = None
    try:
        b = Browser(url)
        p = observe(b)
        if p is None:
            print("  (observe failed on %s)" % url)
            return None
        hits = []
        for i, a in indexed_clicks(p):
            lab = str(a.get("label") or "").strip()
            if want.lower() in lab.lower():
                hits.append((i, a, lab))
        if not hits:
            return None                     # candidate not on this page state
        i, a, lab = hits[0]
        url0 = p.get("url") or ""
        fp0 = p.get("fingerprint") or ""
        try:
            b.act(a, p)
        except Exception as e:              # noqa: BLE001
            print("  [click failed] %r: %s: %s" % (lab[:40], type(e).__name__, str(e)[:80]))
            return None
        time.sleep(1.2)
        p2 = observe(b, tries=4)
        changed = False
        final = ""
        if p2 is not None:
            changed = (p2.get("url") or "") != url0 or                       (p2.get("fingerprint") or "") != fp0
            final = (p2.get("url") or "")[:84]
        score = S._floor_score(a) + S._goal_overlap(
            a, {t for t in S._tokens(goal) if t not in S.STOPWORDS})
        row = dict(page=url, label=lab[:44], href=(a.get("href") or "")[:56],
                   role=a.get("role"), floor_score=score,
                   page_changed=bool(changed), final_url=final)
        print("  %s | %r | href=%s | score=%s | page_changed=%s | final=%s"
              % (url[:38], lab[:40], (a.get("href") or "")[:44], score, changed, final))
        return row
    except Exception as e:                  # noqa: BLE001
        print("  EXC %s: %s: %s" % (url[:38], type(e).__name__, str(e)[:100]))
        return None
    finally:
        if b is not None:
            try:
                b.close()
            except Exception:
                pass


def main() -> int:
    print("probe_floor_gate_fix: zero model calls; owned Chrome on :9222")
    all_rows = []
    for url, goal, wants in PAGES:
        print("=" * 78)
        print("%s | goal=%s" % (url, goal))
        done = 0
        for want in wants:
            row = one_reading(url, goal, want, done)
            if row is not None:
                all_rows.append(row)
                done += 1
    print("=" * 78)
    print("READINGS (%d):" % len(all_rows))
    for r in all_rows:
        print("  %s | %r | score=%s | page_changed=%s | final=%s"
              % (r["page"][:38], r["label"], r["floor_score"], r["page_changed"], r["final_url"]))
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
