"""Measure the SHAPE OF THE PAGE each "首页出不去" task is stuck on, so the next 刀 is
scheduled on evidence instead of on the guess that the link the goal names is somewhere
the floor can reach.

Run ONLY when no batch is in flight (it drives the owned headless Chrome on :9222).
Zero model calls: navigate + observe + call the skill functions directly.

Why (2026-10-09, after b14 = 14/22): four tasks fail with `failure_mode=decision` at 1-3
steps, each parked on a page --
    r105  github.com/                         (goal: "the Releases page of pytorch/pytorch")
    r116  doc.rust-lang.org/stable/std/       (goal: open 'The Cargo Book')
    r118  www.gnu.org/                        (goal: open the 'Bash Reference Manual' node index)
    r122  www.rfc-editor.org/                 (goal: open RFC 9110)
and one (r103) that fills a box and never lands on a results page.
Before touching `skills.py` each one must be answered with a measurement:
  1. how many actions does the snapshot index at all (it only indexes viewport-visible
     ones -- an invisible link is NOT "absent", and a fix that assumes otherwise is a guess);
  2. of those, how many are ON-SITE (the corrected rule from the HN probe: a relative href
     with no scheme is on-site; `href.startswith("/")` alone under-counts badly);
  3. where does the goal's target word actually live -- label, href path segment, or only in
     the raw HTML below the fold;
  4. what do `explicit_target` / `goto_path` / `first_result` return on that real page.
If the answer is "the target is in the raw HTML but never in an indexed action", the disease
is viewport coverage, not scoring, and NO tier added to `explicit_target` can buy it.
"""
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
from jev_ultrafast import skills as S                                # noqa: E402

CASES = [
    # (task, start url, goal, needle that must appear in the winning href, landed page in b14)
    ("r105 github root", "https://github.com/",
     "Open the Releases page of the pytorch/pytorch repository.",
     "pytorch/pytorch/releases", "https://github.com/"),
    ("r116 rust doc root", "https://doc.rust-lang.org/",
     "From the Rust documentation home, open 'The Cargo Book'.",
     "/cargo/", "https://doc.rust-lang.org/stable/std/index.html"),
    ("r116 where b14 sits", "https://doc.rust-lang.org/stable/std/index.html",
     "From the Rust documentation home, open 'The Cargo Book'.",
     "/cargo/", ""),
    ("r118 gnu home", "https://www.gnu.org/",
     "From the GNU homepage, open the 'Bash Reference Manual' node index page.",
     "bash/manual/html_node", "https://www.gnu.org/"),
    ("r122 rfc-editor root", "https://www.rfc-editor.org/",
     "Open RFC 9110, 'HTTP Semantics'.",
     "rfc9110", "https://www.rfc-editor.org/"),
    ("r103 stackoverflow", "https://stackoverflow.com/",
     "Search Stack Overflow for 'python slice step' and open the first question in the results.",
     "/questions/", "https://stackoverflow.com/questions"),
]


DOM_SHAPE_JS = """(() => {
  const want = __NEEDLE__.toLowerCase();
  const anchors = [...document.querySelectorAll('a[href]')];
  const href = a => { try {
      return new URL(a.getAttribute('href'), location.href).href.toLowerCase().split('%2f').join('/');
    } catch (e) { return ''; } };
  const hit = anchors.filter(a => href(a).includes(want));
  const vh = innerHeight;
  const vis = hit.filter(a => { const r = a.getBoundingClientRect();
    return r.width && r.height && r.bottom > 0 && r.top < vh &&
      a.checkVisibility({checkOpacity: true, checkVisibilityCSS: true}); });
  const body = document.body ? document.body.innerText : '';
  return {anchors: anchors.length, hit: hit.length, hitVisible: vis.length,
          htmlOccurrences: document.documentElement.outerHTML.toLowerCase().split(want).length - 1,
          inWholeBodyText: body.toLowerCase().includes(want.split('_').join(' ')),
          viewportH: vh,
          hitSamples: hit.slice(0, 6).map(a => ({
            label: (a.innerText || a.textContent || '').trim().slice(0, 60),
            href: (a.getAttribute('href') || '').slice(0, 90),
            topPx: Math.round(a.getBoundingClientRect().top)}))};
})()"""


def dom_shape(b, needle):
    """Ask the browser that is holding the page how the page really looks.

    The earlier leg fetched the URL with `requests` and counted needle occurrences; it
    returned 0 for every site INCLUDING stackoverflow, whose indexed hrefs obviously
    contain '/questions/' -- one shared failure mode across all six cases means the fetch,
    not the pages, was wrong (different client, JS-rendered or blocked content).  The DOM
    the agent's own snapshot was taken from is the only page this probe may speak about.
    """
    try:
        js = DOM_SHAPE_JS.replace("__NEEDLE__", json.dumps(needle))
        return b.evaluate(js)
    except Exception as e:                                          # noqa: BLE001
        print("    (DOM leg failed: %s: %s)" % (type(e).__name__, e))
        return None


def observe_like_the_agent(b):
    """Same bounded backoff `Agent.__init__` uses (E1), plus one rule this probe needs:

    a snapshot that indexed ZERO actions is not a measurement of the page, it is a
    measurement of a page that had not rendered yet -- so wait and look again, and print
    how many looks it took (the batch's own r118 saw 34 actions; a probe that reads 0
    would schedule a 刀 on an artifact).
    """
    for attempt in range(6):
        try:
            p = b.observe(screenshot=False)
        except StalePage:
            time.sleep(0.4 * (attempt + 1))
            continue
        if (p.get("actions") or []):
            return p, attempt + 1
        time.sleep(0.5 * (attempt + 1))
    try:
        return b.observe(screenshot=False), "6+ (still no actions)"
    except Exception:                                               # noqa: BLE001
        return p, "6+ (observation failed)"


for name, url, goal, needle, landed in CASES:
    print("=" * 78)
    print("%s\n  %s" % (name, url))
    b = Browser(url)
    try:
        p, looks = observe_like_the_agent(b)
        acts = S.indexed_actions(p.get("actions") or [])
        clicks = [(i, str(a.get("label") or "")[:44], str(a.get("href") or ""))
                  for i, a in acts if a.get("kind") == "click"]
        page_host = ""
        try:
            from urllib.parse import urlparse as _up
            page_host = _up(p.get("url") or url).netloc.lower()
        except Exception:
            pass

        def on_site(href):
            # corrected HN rule: no scheme + no leading netloc = relative = on-site
            if not href:
                return False
            h = _up(href)
            if not h.netloc:
                return True
            return h.netloc.lower() == page_host

        n_site = sum(1 for _, _, h in clicks if on_site(h))
        print("  landed=%s  observes attempted=%s" % (p.get("url"), looks))
        print("  actions=%d  click=%d  on-site click=%d  text_chars=%d"
              % (len(acts), len(clicks), n_site, len(p.get("text") or "")))

        seg_hit = [(i, lab, h) for i, lab, h in clicks
                   if needle.lower().lstrip("/") in h.lower().replace("%2f", "/")]
        lab_hit = [(i, lab, h) for i, lab, h in clicks
                   if needle.lower().replace("_", " ") in lab.lower()]
        print("  needle %r: in href=%d in label=%d in visible text=%s"
              % (needle, len(seg_hit), len(lab_hit),
                 needle.lower().replace("_", " ") in (p.get("text") or "").lower()))
        for row in (seg_hit or lab_hit)[:3]:
            print("    candidate e%s %r -> %s" % (row[0], row[1], row[2][:70]))

        dom = dom_shape(b, needle)
        if dom:
            print("  DOM: <a href>=%d  needle in href=%d (of which in first viewport=%d) "
                  "occurrences in served HTML=%d  needle in whole body text=%s"
                  % (dom["anchors"], dom["hit"], dom["hitVisible"],
                     dom["htmlOccurrences"], dom["inWholeBodyText"]))
            for s in dom["hitSamples"]:
                print("    dom e top=%+dpx %r -> %s" % (s["topPx"], s["label"], s["href"]))

        print("  phrases=%s" % (S.goal_phrases(goal),))
        for fn in ("explicit_target", "goto_path", "first_result"):
            f = getattr(S, fn, None)
            if f is None:
                print("  %s -> (no such function)" % fn)
                continue
            try:
                r = f(p, goal, [])
                print("  %s -> %s" % (fn, (r if r is None else
                      "%s %s" % (r.get("operation"), r.get("choice")))))
            except TypeError:
                try:
                    r = f(p, goal)
                    print("  %s -> %s" % (fn, r))
                except Exception as e:                              # noqa: BLE001
                    print("  %s EXC %s: %s" % (fn, type(e).__name__, e))
            except Exception as e:                                  # noqa: BLE001
                print("  %s EXC %s: %s" % (fn, type(e).__name__, e))
    except Exception as e:                                          # noqa: BLE001
        print("  EXC %s: %s" % (type(e).__name__, e))
    finally:
        b.close()
