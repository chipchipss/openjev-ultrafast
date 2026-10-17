"""r105 zoom B/C continued: full dump of the github search page + repo page so the
shape table says where 'Releases' actually lives. Zero model calls."""
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


def dump(p, label):
    idx = S.indexed_actions(p.get("actions") or [])
    print("[%s] url=%s indexed=%d" % (label, p.get("url"), len(idx)))
    for i, a in idx:
        print("   %-4s %-7s %-10s %-44s %s" % (i, a.get("kind"), a.get("role"),
                                               str(a.get("label") or "")[:44],
                                               str(a.get("href") or "")[:52]))
    return idx


print("=== B. github search results (full) ===")
b = Browser("https://github.com/search?q=pytorch%2Fpytorch&type=repositories")
try:
    p = observe(b)
    dump(p, "search")
finally:
    b.close()

print("=== C. repo page (full) ===")
b = Browser("https://github.com/pytorch/pytorch")
try:
    p = observe(b)
    idx = dump(p, "repo")
    dom = b.evaluate("""(() => {
      const as = [...document.querySelectorAll('a[href]')];
      const rel = as.filter(a => /\\/releases/.test(a.getAttribute('href') || ''));
      return {total: as.length, releases: rel.length,
              first: rel.slice(0, 4).map(a => ({label: (a.innerText||'').trim().slice(0,40),
                href: a.getAttribute('href'), top: Math.round(a.getBoundingClientRect().top)}))};
    })()""")
    print("live DOM: <a>=%d /releases links=%d" % (dom["total"], dom["releases"]))
    for s in dom["first"]:
        print("    top=%+d %r -> %s" % (s["top"], s["label"], s["href"]))
finally:
    b.close()
