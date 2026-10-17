"""r103 zoom B: after the product fill (act path), is there any submit mechanism the
floor can see? Enter keydown/keyup on the focused field (probe_r103_enter template),
then measure the resulting page. Zero model."""
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

GOAL = "Search Stack Overflow for 'python slice step' and open the first question in the results."
URL = "https://stackoverflow.com/questions"


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


def state(b, label):
    info = b.evaluate("""(() => ({
      url: location.href,
      active: document.activeElement ? (document.activeElement.getAttribute('aria-label')
              || document.activeElement.tagName) : null,
      value: document.activeElement && 'value' in document.activeElement
              ? document.activeElement.value : null,
      options: [...document.querySelectorAll('[role="option"]')].length,
      title: document.title,
    }))()""")
    print("  %-14s %s" % (label, info))
    return info


b = None
try:
    b = Browser(URL)
    p = observe(b)
    st = S.search_type(p, GOAL, [])
    if not st:
        print("search_type abstains on the start page -- nothing to replay")
        sys.exit(0)
    action = next(a for _, a in S.indexed_actions(p.get("actions") or []) if a.get("id") == st["choice"])
    print("=== fill the header combobox (product act path) ===")
    b.act(action, p, text=st["text"])
    state(b, "after-fill")

    print("=== Enter keydown/keyup on the focused field ===")
    b.call("Input.dispatchKeyEvent", type="keyDown", key="Enter", code="Enter",
           windowsVirtualKeyCode=13, nativeVirtualKeyCode=13, text="\r", unmodifiedText="\r")
    b.call("Input.dispatchKeyEvent", type="keyUp", key="Enter", code="Enter",
           windowsVirtualKeyCode=13, nativeVirtualKeyCode=13)
    time.sleep(2.0)
    state(b, "after-enter")
    try:
        p2 = b.observe(screenshot=False)
    except StalePage:
        time.sleep(1.5)
        p2 = observe(b)
    print("  observed url=%s title=%r" % (p2.get("url"), str(p2.get("title") or "")[:50]))
    idx = S.indexed_actions(p2.get("actions") or [])
    rows = [(a.get("id"), str(a.get("label") or "")[:52], a.get("href"))
            for _, a in idx if a.get("kind") == "click" and "/questions/" in str(a.get("href") or "")]
    print("  question links indexed=%d" % len(rows))
    for r in rows[:6]:
        print("    ", r)
    hist = [{"step": 1, "kind": "fill", "action": action.get("label"),
             "choice": action.get("id"), "skill": "search_type", "text": st["text"],
             "page_changed": True, "url": URL,
             "outcome": {"url_changed": "/search" in (p2.get("url") or "")}}]
    for name in ("first_result", "explicit_target", "search_submit", "goal_reached"):
        d = getattr(S, name)(p2, GOAL, hist)
        picked = None
        if isinstance(d, dict):
            picked = {c: a for c, a in idx}.get(str(d.get("target")))
        print("      %-14s -> %s" % (name, "%s %r %r" % (d.get("operation"), d.get("choice"),
              (picked or {}).get("label")) if isinstance(d, dict) else d))
finally:
    if b:
        try:
            b.close()
        except Exception:
            pass
