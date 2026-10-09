"""Would an Enter-submit mechanism actually buy r103, or does Stack Overflow wall it?

Zero model calls: it drives the product's own act() for the fill, then dispatches the Enter
key the way a future mechanism would, and prints where the page ends up.
Run ONLY when no batch is in flight (owned headless Chrome on :9222).

Probe reason (2026-10-09, after b16): `m2/probe_r103_submit.py` measured that on
stackoverflow.com/questions the floor fills the header combobox successfully
(`window value now = 'python slice step'`) and then **the whole floor abstains** --
`search_submit` finds no submit button and no `role=option` row, so the model takes over
and re-issues TYPE_TEXT (b16's 2-step correct_abandon). The only remaining way to submit is
Enter, which is a NEW action kind in the execution layer. Before paying for that, prove the
page answers it: stage D of the first probe hit `/nocaptcha?...` on a direct search URL, so
"SO walls search" is a live alternative explanation.
"""
import io
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, ".")
os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:2080")
os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:2080")

from jev_ultrafast.browser import Browser, StalePage        # noqa: E402
from jev_ultrafast import skills as S                        # noqa: E402

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
        if S._indexed(p.get("actions") or []):
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
    action = next(a for _, a in S._indexed(p.get("actions") or []) if a.get("id") == st["choice"])
    print("=== fill the header combobox (product act path) ===")
    b.act(action, p, text=st["text"])
    state(b, "after-fill")

    print("=== Enter keydown/keyup on the focused field (what a mechanism would send) ===")
    b.call("Input.dispatchKeyEvent", type="keyDown", key="Enter", code="Enter",
           windowsVirtualKeyCode=13, nativeVirtualKeyCode=13, text="\r", unmodifiedText="\r")
    b.call("Input.dispatchKeyEvent", type="keyUp", key="Enter", code="Enter",
           windowsVirtualKeyCode=13, nativeVirtualKeyCode=13)
    time.sleep(1.5)
    state(b, "after-enter")
    try:
        p2 = b.observe(screenshot=False)
        print("  observed url=%s" % p2.get("url"))
    except StalePage:
        time.sleep(1.5)
        p2 = observe(b)
        print("  observed url=%s (after StalePage retry)" % p2.get("url"))
    hist = [{"step": 1, "kind": "fill", "action": action.get("label"),
             "choice": action.get("id"), "skill": "search_type", "text": st["text"],
             "page_changed": True, "url": URL}]
    for name in ("first_result", "explicit_target", "search_submit", "goal_reached"):
        d = getattr(S, name)(p2, GOAL, hist)
        picked = None
        if isinstance(d, dict):
            picked = {c: a for c, a in S._indexed(p2.get("actions") or [])}.get(str(d.get("target")))
        print("      %-15s -> %s" % (name, "%s %r %r" % (d.get("operation"), d.get("choice"),
              (picked or {}).get("label")) if isinstance(d, dict) else d))
    print("=== second Enter / wait: does the result list render rows? ===")
    time.sleep(1.5)
    p3 = observe(b)
    idx = S._indexed(p3.get("actions") or [])
    rows = [(a.get("id"), str(a.get("label") or "")[:52]) for _, a in idx
            if a.get("kind") == "click" and (a.get("role") or "") == "link"
            and len(str(a.get("label") or "")) > 25]
    print("  url=%s link rows with long labels=%d" % (p3.get("url"), len(rows)))
    for r in rows[:6]:
        print("    ", r)
    d = S.first_result(p3, GOAL, hist)
    print("  first_result -> %s" % (d and (d.get("operation"), d.get("choice"))))
finally:
    if b:
        try:
            b.close()
        except Exception:
            pass
