"""Why does the snapshot see only 5 actions on httpbin.org?

Counts every anchor in the DOM vs the ones that survive snapshot.js's filters,
and reports which filter drops them.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from jev_ultrafast.browser import Browser  # noqa: E402

JS = r"""
(() => {
  const all = [...document.querySelectorAll('a[href]')];
  const rows = all.map(e => {
    const r = e.getBoundingClientRect();
    return {
      href: (e.getAttribute('href')||'').slice(0,60),
      label: (e.textContent||'').trim().slice(0,40),
      w: Math.round(r.width), h: Math.round(r.height),
      x: Math.round(r.x), y: Math.round(r.y),
      vw: innerWidth, vh: innerHeight,
      inViewport: !(r.x<0 || r.y<0 || r.x+r.width>=innerWidth || r.y+r.height>=innerHeight),
      visible: !!(r.width>0 && r.height>0),
    };
  });
  return JSON.stringify({
    total: all.length,
    forms_post: all.filter(e => (e.getAttribute('href')||'').includes('/forms/post')).length,
    bodyH: document.body.scrollHeight,
    rows: rows.slice(0, 40),
  });
})()
"""


def main() -> int:
    b = Browser("https://httpbin.org/")
    import time
    time.sleep(2.0)
    raw = b.evaluate(JS)
    d = json.loads(raw) if isinstance(raw, str) else raw
    ident = b.evaluate(
        "JSON.stringify({title:document.title,"
        " url:location.href,"
        " text:(document.body?document.body.innerText:'').replace(/\\s+/g,' ').slice(0,600)})"
    )
    try:
        i = json.loads(ident) if isinstance(ident, str) else ident
    except Exception:
        i = {"title": str(ident)[:300]}
    print(f"TITLE : {i.get('title')}")
    print(f"URL   : {i.get('url')}")
    print(f"TEXT  : {i.get('text')}")
    print()
    print(f"anchors in DOM      : {d['total']}")
    print(f"...with /forms/post  : {d['forms_post']}")
    print(f"document scrollHeight: {d['bodyH']}   viewport: see rows")
    print()
    print(f"{'inVP':<6}{'w':>5}{'h':>5}{'x':>6}{'y':>7}  {'href':<40} label")
    for r in d["rows"]:
        if "/forms/post" in r["href"] or not r["inViewport"] or r["w"] == 0:
            mark = "YES" if "/forms/post" in r["href"] else ""
            print(f"{str(r['inViewport']):<6}{r['w']:>5}{r['h']:>5}{r['x']:>6}{r['y']:>7}  "
                  f"{r['href'][:38]:<40} {r['label'][:24]} {mark}")
    b.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())