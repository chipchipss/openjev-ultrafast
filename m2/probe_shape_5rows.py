"""Road-A probe: the SHAPE OF THE PAGE for the five decision-family rows, measured
before any code change (handover section 7: measure shape first, no word lists).

Rows: r102 arxiv / r103 stackoverflow / r104 pubmed / r105 github / r122 rfc-editor.

Zero model calls: navigate + observe + call the skill functions directly.
Run ONLY when no batch is in flight (it drives the owned headless Chrome on :9222).

The four questions every row must answer with a measurement, not a guess
(same contract as m2/probe_homepage_shape.py):
  1. how many actions does the snapshot index at all -- it only indexes
     viewport-visible ones, so an invisible link is NOT "absent";
  2. of those, how many are ON-SITE (relative href with no scheme, or same host);
  3. where does the goal's target word actually live -- label, href path segment,
     page text, or only in the raw HTML below the fold;
  4. what do explicit_target / goto_path / first_result return on that real page.

Stage S measures the START page (what the agent sees at step 0, which is where
r105/r122 park). Stage R measures a RESULTS page for the three search rows
(r102/r103/r104), fetched by its own results URL. Stage D drives the search the
way the agent does -- search_type picks the box, act() types it, search_submit
clicks a submit control -- still zero model calls (same shape as
m2/probe_r103_enter.py and m2/probe_r104_shape.py).

Usage:
    python m2/probe_shape_5rows.py            # all stages
    python m2/probe_shape_5rows.py start      # stage S only
    python m2/probe_shape_5rows.py results    # stage R only
    python m2/probe_shape_5rows.py driven     # stage D only
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
from jev_ultrafast import skills as S                              # noqa: E402

STAGE = (sys.argv[1] if len(sys.argv) > 1 else "all").lower()

# task rows verbatim from m2/tasks_real_50.jsonl (the 50-row L2 set)
ROWS = [
    dict(row="r102", site="arxiv", url="https://arxiv.org/",
         goal="Search arXiv for the paper 'Attention Is All You Need' and open its abstract page.",
         needle="1706.03762", href_re=r"/abs/1706\.03762",
         results_url="https://arxiv.org/search/?query=Attention+Is+All+You+Need&searchtype=all"),
    dict(row="r103", site="stackoverflow", url="https://stackoverflow.com/",
         goal="Search Stack Overflow for 'python slice step' and open the first question in the results.",
         needle="/questions/", href_re=r"/questions/\d+",
         results_url="https://stackoverflow.com/search?q=python+slice+step"),
    dict(row="r104", site="pubmed", url="https://pubmed.ncbi.nlm.nih.gov/",
         goal="Search PubMed for 'CRISPR off-target' and open the first research article page.",
         needle="/36970624/", href_re=r"/\d{7,9}/?$",
         results_url="https://pubmed.ncbi.nlm.nih.gov/?term=CRISPR+off-target"),
    dict(row="r105", site="github", url="https://github.com/",
         goal="Open the Releases page of the pytorch/pytorch repository.",
         needle="pytorch/pytorch/releases", href_re=r"pytorch/pytorch/releases"),
    dict(row="r122", site="rfc-editor", url="https://www.rfc-editor.org/",
         goal="Open RFC 9110, 'HTTP Semantics'.",
         needle="rfc9110", href_re=r"rfc/rfc9110"),
]

# On-site rule, verbatim from m2/probe_homepage_shape.py (the corrected HN rule):
# a relative href with no scheme and no netloc is on-site; a leading "/" alone
# under-counts badly.
def _urlparse(u):
    from urllib.parse import urlparse
    return urlparse(u or "")


DOM_SHAPE_JS = """(() => {
  const cfg = __CFG__;
  const want = (cfg.needle || '').toLowerCase();
  const hrefRe = cfg.href_re ? new RegExp(cfg.href_re, 'i') : null;
  const anchors = [...document.querySelectorAll('a[href]')];
  const href = a => { try {
      return new URL(a.getAttribute('href'), location.href).href.toLowerCase().split('%2f').join('/');
    } catch (e) { return ''; } };
  const hit = anchors.filter(a => href(a).includes(want));
  const shape = hrefRe ? anchors.filter(a => {
      try { return hrefRe.test(new URL(a.getAttribute('href'), location.href).pathname); }
      catch (e) { return false; } }) : [];
  const vh = innerHeight;
  const vis = h => h.filter(a => { const r = a.getBoundingClientRect();
    return r.width && r.height && r.bottom > 0 && r.top < vh &&
      a.checkVisibility({checkOpacity: true, checkVisibilityCSS: true}); });
  const body = document.body ? document.body.innerText : '';
  return {anchors: anchors.length,
          needleHits: hit.length, needleVisible: vis(hit).length,
          shapeHits: shape.length, shapeVisible: vis(shape).length,
          htmlOccurrences: want ? document.documentElement.outerHTML.toLowerCase().split(want).length - 1 : 0,
          inWholeBodyText: want ? body.toLowerCase().includes(want.split('_').join(' ')) : null,
          viewportH: vh, docHeight: document.documentElement.scrollHeight,
          needleSamples: hit.slice(0, 6).map(a => ({
            label: (a.innerText || a.textContent || '').trim().slice(0, 60),
            href: (a.getAttribute('href') || '').slice(0, 90),
            topPx: Math.round(a.getBoundingClientRect().top)})),
          shapeSamples: shape.slice(0, 6).map(a => ({
            label: (a.innerText || a.textContent || '').trim().slice(0, 60),
            href: (a.getAttribute('href') || '').slice(0, 90),
            topPx: Math.round(a.getBoundingClientRect().top)}))};
})()"""


def dom_shape(b, cfg):
    """Ask the browser holding the page how the page really looks (the DOM the
    agent's own snapshot was taken from is the only page this probe may speak about)."""
    try:
        js = DOM_SHAPE_JS.replace("__CFG__", json.dumps(cfg))
        return b.evaluate(js)
    except Exception as e:                                          # noqa: BLE001
        print("    (DOM leg failed: %s: %s)" % (type(e).__name__, e))
        return None


def observe_like_the_agent(b, tries=8):
    """Bounded backoff, same contract as probe_homepage_shape.observe_like_the_agent:
    a snapshot that indexed ZERO actions is not a measurement of the page."""
    p = None
    for attempt in range(tries):
        try:
            p = b.observe(screenshot=False)
        except StalePage:
            time.sleep(0.4 * (attempt + 1))
            continue
        if S.indexed_actions(p.get("actions") or []):
            return p, attempt + 1
        time.sleep(0.5 * (attempt + 1))
    return p, "%d+ (still no actions)" % tries


def show_shape(b, p, cfg, label):
    """The shape table for one page state."""
    idx = S.indexed_actions(p.get("actions") or [])
    by_choice = {c: a for c, a in idx}
    kinds, clicks, fills = {}, [], []
    for _, a in idx:
        kinds[a.get("kind")] = kinds.get(a.get("kind"), 0) + 1
        if a.get("kind") == "click":
            clicks.append((a.get("id"), str(a.get("label") or "")[:44], a.get("role")))
        if a.get("kind") == "fill":
            fills.append((a.get("id"), str(a.get("label") or "")[:44], a.get("role")))
    page_host = _urlparse(p.get("url") or "").netloc.lower()

    def on_site(href):
        if not href:
            return False
        h = _urlparse(href)
        if not h.netloc:
            return True
        return h.netloc.lower() == page_host

    site_clicks = [(i, lab, h) for i, lab, h in clicks if on_site(h)]
    print("  [%s] url=%s scroll_y=%s doc_h=%s omitted=%s looks=%s"
          % (label, p.get("url"), (p.get("scroll") or {}).get("y"),
             (p.get("scroll") or {}).get("height"), p.get("omitted_actions"),
             p.get("_looks")))
    print("      indexed=%d kinds=%s | indexed clicks=%d (on-site %d) fills=%s"
          % (len(idx), kinds, len(clicks), len(site_clicks), fills or "NONE"))
    print("      raw action rows=%d  text_chars=%d  title=%r"
          % (len(p.get("actions") or []), len(p.get("text") or ""),
             str(p.get("title") or "")[:60]))
    print("      goal_phrases=%r" % (S.goal_phrases(cfg["goal"]),))
    print("      _goal_query=%r" % (S._goal_query(cfg["goal"]),))

    needle = cfg["needle"].lower()
    seg_hit = [(i, lab, h) for i, lab, h in clicks
               if needle.lstrip("/") in h.lower().replace("%2f", "/")]
    lab_hit = [(i, lab, h) for i, lab, h in clicks
               if needle.replace("_", " ") in lab.lower()]
    print("      needle %r: in indexed href=%d in indexed label=%d in visible text=%s"
          % (cfg["needle"], len(seg_hit), len(lab_hit),
             needle.replace("_", " ") in (p.get("text") or "").lower()))
    for row in (seg_hit or lab_hit)[:3]:
        print("        candidate e%s %r -> %s" % (row[0], row[1], row[2][:70]))

    dom = dom_shape(b, cfg)
    if dom:
        print("      DOM: <a href>=%d needle-in-href=%d (visible %d) shape-in-href=%d (visible %d)"
              % (dom["anchors"], dom["needleHits"], dom["needleVisible"],
                 dom["shapeHits"], dom["shapeVisible"]))
        print("      DOM: needle occurrences in served HTML=%d needle in whole body text=%s "
              "viewport=%d doc_h=%d"
              % (dom["htmlOccurrences"], dom["inWholeBodyText"],
                 dom["viewportH"], dom["docHeight"]))
        for s in dom["needleSamples"]:
            print("        dom top=%+dpx %r -> %s" % (s["topPx"], s["label"], s["href"][:70]))

    print("      -- skill returns on this real page --")
    for fn in (S.explicit_target, S.goto_path, S.first_result):
        try:
            r = fn(p, cfg["goal"], [])
        except Exception as e:                                      # noqa: BLE001
            r = "EXC %s: %s" % (type(e).__name__, e)
        if isinstance(r, dict):
            picked = by_choice.get(str(r.get("target")))
            print("        %-16s -> op=%s choice=%s label=%r"
                  % (fn.__name__, r.get("operation"), r.get("choice"),
                     str((picked or {}).get("label") or "")[:46]))
        else:
            print("        %-16s -> %s" % (fn.__name__, r))
    try:
        fl = S.first_action_floor(p, cfg["goal"], [])
        if isinstance(fl, dict):
            picked = by_choice.get(str(fl.get("target")))
            print("        %-16s -> op=%s choice=%s label=%r"
                  % ("first_action_floor", fl.get("operation"), fl.get("choice"),
                     str((picked or {}).get("label") or "")[:46]))
        else:
            print("        %-16s -> %s" % ("first_action_floor", fl))
    except Exception as e:                                          # noqa: BLE001
        print("        %-16s -> EXC %s: %s" % ("first_action_floor", type(e).__name__, e))
    try:
        rt = S.route(p, cfg["goal"], [])
        if isinstance(rt, dict):
            picked = by_choice.get(str(rt.get("target")))
            print("        %-16s -> skill=%s op=%s label=%r"
                  % ("route", rt.get("skill"), rt.get("operation"),
                     str((picked or {}).get("label") or "")[:46]))
        else:
            print("        %-16s -> %s" % ("route", rt))
    except Exception as e:                                          # noqa: BLE001
        print("        %-16s -> EXC %s: %s" % ("route", type(e).__name__, e))
    return idx


def stage_start():
    print("#" * 78)
    print("# STAGE S -- start pages (what the agent sees at step 0)")
    print("#" * 78)
    for cfg in ROWS:
        print("=" * 78)
        print("%s %s | %s" % (cfg["row"], cfg["site"], cfg["url"]))
        b = Browser(cfg["url"])
        try:
            p, looks = observe_like_the_agent(b)
            if p is None:
                print("  observe failed entirely")
                continue
            p = dict(p)
            p["_looks"] = looks
            show_shape(b, p, cfg, "start")
        except Exception as e:                                      # noqa: BLE001
            print("  EXC %s: %s" % (type(e).__name__, e))
        finally:
            try:
                b.close()
            except Exception:
                pass


def stage_results():
    print("#" * 78)
    print("# STAGE R -- results pages fetched by their own URL (zero model)")
    print("#" * 78)
    for cfg in ROWS:
        if "results_url" not in cfg:
            continue
        print("=" * 78)
        print("%s %s | %s" % (cfg["row"], cfg["site"], cfg["results_url"]))
        b = Browser(cfg["results_url"])
        try:
            p, looks = observe_like_the_agent(b)
            if p is None:
                print("  observe failed entirely")
                continue
            p = dict(p)
            p["_looks"] = looks
            show_shape(b, p, cfg, "results")
        except Exception as e:                                      # noqa: BLE001
            print("  EXC %s: %s" % (type(e).__name__, e))
        finally:
            try:
                b.close()
            except Exception:
                pass


def stage_driven():
    """Drive the search the way the agent does: search_type picks the box, act()
    types it, then a submit control if one is indexed. Zero model calls."""
    print("#" * 78)
    print("# STAGE D -- driven search on the START page (search_type + submit, zero model)")
    print("#" * 78)
    for cfg in ROWS:
        if cfg["site"] not in ("arxiv", "stackoverflow", "pubmed"):
            continue
        print("=" * 78)
        print("%s %s | %s" % (cfg["row"], cfg["site"], cfg["url"]))
        b = Browser(cfg["url"])
        try:
            p, looks = observe_like_the_agent(b)
            if p is None:
                print("  observe failed entirely")
                continue
            p = dict(p)
            p["_looks"] = looks
            st = S.search_type(p, cfg["goal"], [])
            if not st:
                print("  search_type abstains on the start page (nothing to drive)")
                show_shape(b, p, cfg, "start")
                continue
            action = next(a for _, a in S.indexed_actions(p.get("actions") or [])
                          if a.get("id") == st["choice"])
            print("  search_type -> TYPE_TEXT e%s label=%r text=%r"
                  % (st["target"], str(action.get("label") or "")[:40], st.get("text")))
            b.act(action, p, text=st["text"])
            p2, looks2 = observe_like_the_agent(b)
            if p2 is None:
                print("  observe after fill failed")
                continue
            p2 = dict(p2)
            p2["_looks"] = looks2
            print("  after fill: url=%s indexed=%d"
                  % (p2.get("url"), len(S.indexed_actions(p2.get("actions") or []))))
            sub = S.search_submit(p2, cfg["goal"],
                                  [{"kind": "fill", "action": action.get("label"),
                                    "choice": action.get("id"), "skill": "search_type",
                                    "text": st.get("text"),
                                    "outcome": {"url_changed": False}}])
            if isinstance(sub, dict):
                suba = next((a for _, a in S.indexed_actions(p2.get("actions") or [])
                             if a.get("id") == sub.get("choice")), None)
                print("  search_submit -> op=%s choice=%s label=%r"
                      % (sub.get("operation"), sub.get("choice"),
                         str((suba or {}).get("label") or "")[:40]))
                if suba is not None:
                    b.act(suba, p2)
                    p3, looks3 = observe_like_the_agent(b)
                    if p3 is not None:
                        p3 = dict(p3)
                        p3["_looks"] = looks3
                        show_shape(b, p3, cfg, "results")
            else:
                print("  search_submit -> %s" % (sub,))
                show_shape(b, p2, cfg, "after-fill")
        except Exception as e:                                      # noqa: BLE001
            print("  EXC %s: %s" % (type(e).__name__, e))
        finally:
            try:
                b.close()
            except Exception:
                pass


TARGET_PAGES = [
    dict(row="r102", site="arxiv", url="https://arxiv.org/abs/1706.03762",
         goal="Search arXiv for the paper 'Attention Is All You Need' and open its abstract page.",
         needle="1706.03762", href_re=r"/abs/1706\.03762"),
    dict(row="r103", site="stackoverflow", url="https://stackoverflow.com/questions/12454662/how-to-get-a-list-of-all-indices-of-repeated-elements-in-a-list",
         goal="Search Stack Overflow for 'python slice step' and open the first question in the results.",
         needle="/questions/", href_re=r"/questions/\d+"),
    dict(row="r104", site="pubmed", url="https://pubmed.ncbi.nlm.nih.gov/36970624/",
         goal="Search PubMed for 'CRISPR off-target' and open the first research article page.",
         needle="/36970624/", href_re=r"/\d{7,9}/?$"),
    dict(row="r105", site="github", url="https://github.com/pytorch/pytorch/releases",
         goal="Open the Releases page of the pytorch/pytorch repository.",
         needle="pytorch/pytorch/releases", href_re=r"pytorch/pytorch/releases"),
    dict(row="r122", site="rfc-editor", url="https://www.rfc-editor.org/rfc/rfc9110",
         goal="Open RFC 9110, 'HTTP Semantics'.",
         needle="rfc9110", href_re=r"rfc/rfc9110"),
]


def stage_targets():
    """The page the assertion asks for: is it reachable at all from this link, and
    does goal_reached fire there (the 0-step DONE guard)?"""
    print("#" * 78)
    print("# STAGE T -- the assertion's own target pages (zero model)")
    print("#" * 78)
    for cfg in TARGET_PAGES:
        print("=" * 78)
        print("%s %s | %s" % (cfg["row"], cfg["site"], cfg["url"]))
        b = Browser(cfg["url"])
        try:
            p, looks = observe_like_the_agent(b)
            if p is None:
                print("  observe failed entirely")
                continue
            p = dict(p)
            p["_looks"] = looks
            show_shape(b, p, cfg, "target")
            hist = [{"step": 1, "kind": "click", "action": "open", "choice": "e1",
                     "skill": "probe", "outcome": {"url_changed": True}}]
            try:
                gr = S.goal_reached(p, cfg["goal"], hist)
                print("      goal_reached(1 prior step) -> %s"
                      % ("%s %r" % (gr.get("operation"), gr.get("skill"))
                         if isinstance(gr, dict) else gr))
            except Exception as e:                                  # noqa: BLE001
                print("      goal_reached EXC %s: %s" % (type(e).__name__, e))
        except Exception as e:                                      # noqa: BLE001
            print("  EXC %s: %s" % (type(e).__name__, e))
        finally:
            try:
                b.close()
            except Exception:
                pass


SO_QUESTIONS = [
    dict(row="r103", site="stackoverflow", url="https://stackoverflow.com/questions/tagged/python+slice?tab=newest",
         goal="Search Stack Overflow for 'python slice step' and open the first question in the results.",
         needle="/questions/", href_re=r"/questions/\d+"),
    dict(row="r103", site="stackoverflow", url="https://stackoverflow.com/search?tab=relevance&q=python%20slice%20step",
         goal="Search Stack Overflow for 'python slice step' and open the first question in the results.",
         needle="/questions/", href_re=r"/questions/\d+"),
]


def stage_so_walls():
    """Stage W: does SO wall the search URL and the tag URL, or only some of them?"""
    print("#" * 78)
    print("# STAGE W -- stackoverflow wall check on two search-shaped URLs")
    print("#" * 78)
    for cfg in SO_QUESTIONS:
        print("=" * 78)
        print("%s %s | %s" % (cfg["row"], cfg["site"], cfg["url"]))
        b = Browser(cfg["url"])
        try:
            p, looks = observe_like_the_agent(b)
            if p is None:
                print("  observe failed entirely")
                continue
            p = dict(p)
            p["_looks"] = looks
            show_shape(b, p, cfg, "so-wall")
        except Exception as e:                                      # noqa: BLE001
            print("  EXC %s: %s" % (type(e).__name__, e))
        finally:
            try:
                b.close()
            except Exception:
                pass


ARXIV_TITLE = [
    dict(row="r102", site="arxiv", url="https://arxiv.org/search/?query=%22Attention+Is+All+You+Need%22&searchtype=title",
         goal="Search arXiv for the paper 'Attention Is All You Need' and open its abstract page.",
         needle="1706.03762", href_re=r"/abs/1706\.03762"),
]


def stage_arxiv_title():
    """Stage X: the title-restricted arxiv search -- the row the assertion wants
    is rank 36 of 36 in served HTML. What does the snapshot index of it?"""
    print("#" * 78)
    print("# STAGE X -- arxiv title-restricted search shape")
    print("#" * 78)
    for cfg in ARXIV_TITLE:
        print("=" * 78)
        print("%s %s | %s" % (cfg["row"], cfg["site"], cfg["url"]))
        b = Browser(cfg["url"])
        try:
            p, looks = observe_like_the_agent(b)
            if p is None:
                print("  observe failed entirely")
                continue
            p = dict(p)
            p["_looks"] = looks
            show_shape(b, p, cfg, "arxiv-title")
            dom = dom_shape(b, cfg)
            if dom:
                print("      DOM shapeSamples:")
                for s in dom["shapeSamples"][-4:]:
                    print("        top=%+dpx %r -> %s" % (s["topPx"], s["label"], s["href"][:70]))
        except Exception as e:                                      # noqa: BLE001
            print("  EXC %s: %s" % (type(e).__name__, e))
        finally:
            try:
                b.close()
            except Exception:
                pass


if __name__ == "__main__":
    print("probe_shape_5rows: stage=%s  (zero model calls; owned Chrome on :9222)" % STAGE)
    if STAGE in ("all", "start", "s"):
        stage_start()
    if STAGE in ("all", "results", "r"):
        stage_results()
    if STAGE in ("all", "driven", "d"):
        stage_driven()
    if STAGE in ("all", "targets", "t"):
        stage_targets()
    if STAGE in ("all", "walls", "w"):
        stage_so_walls()
    if STAGE in ("all", "arxivtitle", "x"):
        stage_arxiv_title()
    print("done")
