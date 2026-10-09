"""When does a scroll actually land, as seen by the PRODUCT's own read path?

Why this exists: r114 after #47 fired `SCROLL_TOP`, the agent re-observed, and decided on a
page whose fingerprint is byte-identical to the y=2240 frame of the replay — i.e. the
observation after a scroll act shows a position the page had *before* the wheel landed
(`m2/probe_undo_restores.py`, 2026-10-09; `scroll` has no entry in `SETTLE_CAPS_MS`,
`browser.py:318`).

The first measurement of "how late" sampled `window.scrollY` from a page-side `setInterval`
and reported single abrupt jumps at 1.0–2.9s. That number is not trustworthy: a throttled
background tab fires timers on a ~1s grid, so the *instrument* may have been the delay.
This version removes that confound and separates the three candidate causes:

  A. wheel alone            — what `browser.py:456` does today
  B. mouseMoved, then wheel — CDP input needs a hover target; without a prior move the wheel
                              may be queued until the next input flush
  C. window.scrollBy()      — a script-driven scroll: is it instant, or does it animate too?

For each mechanism we poll `window.scrollY` from PYTHON with `Runtime.evaluate` — the same
call the product's snapshot uses — every 50ms, and report the first sample time at which the
offset equals the final offset and stays there, plus the raw timeline. We also print
`document.visibilityState`, `document.hidden` and the computed `scroll-behavior`, because if
the tab is hidden, *any* measured latency is an artifact of throttling and the product's
latency has to be measured with the target activated.

Zero model calls; owned Chrome on :9222 only; run only when no batch is in flight.
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

from jev_ultrafast.browser import Browser, StalePage                    # noqa: E402
from jev_ultrafast import skills as S                                   # noqa: E402

SITES = [
    ("django home  (r114)", "https://www.djangoproject.com/"),
    ("rust stable  (r116)", "https://doc.rust-lang.org/stable/"),
    ("peps         (r113)", "https://peps.python.org/"),
    ("rfc-editor   (r122)", "https://www.rfc-editor.org/"),
]
POLL_S = 3.0
POLL_EVERY = 0.05


def ev(b, expr):
    return b.call("Runtime.evaluate", expression=expr, returnByValue=True) \
             .get("result", {}).get("value")


def y_of(b):
    try:
        v = ev(b, "Math.round(window.scrollY)")
        return int(v) if v is not None else -1
    except Exception:                                                   # noqa: BLE001
        return -1


def observe_settled(b, tries=6):
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


def wheel(b, delta):
    b.call("Input.dispatchMouseEvent", type="mouseWheel", x=550, y=650,
           deltaX=0, deltaY=delta)


def poll_until_still(b, expect_change=True):
    """Poll from Python like the product does. Return (timeline, landed_at_ms, final_y).

    landed_at = first sample whose y differs from the start and is then held for 3 samples
    (150ms); None if it never held.
    """
    t0 = time.perf_counter()
    timeline = []
    while time.perf_counter() - t0 < POLL_S:
        timeline.append([round((time.perf_counter() - t0) * 1000), y_of(b)])
        time.sleep(POLL_EVERY)
    landed = None
    if len(timeline) >= 4:
        start = timeline[0][1]
        for i in range(len(timeline) - 3):
            t, y = timeline[i]
            if y != start and all(timeline[j][1] == y for j in range(i, min(i + 3, len(timeline)))):
                landed = t
                break
    if landed is None and not expect_change:
        landed = 0
    return timeline, landed, timeline[-1][1] if timeline else None


def reset_top(b):
    ev(b, "window.scrollTo(0,0)")
    time.sleep(0.4)
    return y_of(b)


for name, url in SITES:
    print("=" * 78)
    print("%s\n  %s" % (name, url))
    b = None
    try:
        b = Browser(url)
        observe_settled(b)
        print("  visibilityState=%s hidden=%s scroll-behavior=%s html scrollHeight=%s"
              % (ev(b, "document.visibilityState"), ev(b, "document.hidden"),
                 ev(b, "getComputedStyle(document.documentElement).scrollBehavior"),
                 ev(b, "document.documentElement.scrollHeight")))
        y0 = reset_top(b)
        print("  scrollTo(0,0) -> window.scrollY=%s (script-driven read is immediate?)" % y0)

        # A. wheel alone from y=0
        wheel(b, 560)
        tl, landed, final = poll_until_still(b)
        print("  A wheel-alone      start=%-5s landed at %-6s final=%-5s | timeline %s"
              % (tl[0][1], str(landed) + "ms", final, json.dumps(tl[:40][::2])))

        # A2. second wheel alone (is the *first* event special?)
        wheel(b, 560)
        tl, landed2, final2 = poll_until_still(b)
        print("  A2 wheel-alone #2  start=%-5s landed at %-6s final=%-5s | timeline %s"
              % (tl[0][1], str(landed2) + "ms", final2, json.dumps(tl[:40][::2])))

        # B. mouseMoved then wheel, big undo distance
        reset_top(b)
        for _ in range(3):
            wheel(b, 560)
            time.sleep(1.0)
        before = y_of(b)
        b.call("Input.dispatchMouseEvent", type="mouseMoved", x=550, y=650, deltaX=0, deltaY=0)
        wheel(b, -before)
        tl, landedB, finalB = poll_until_still(b)
        print("  B mouseMoved+wheel undo from %-5s landed at %-6s final=%-5s | timeline %s"
              % (before, str(landedB) + "ms", finalB, json.dumps(tl[:40][::2])))

        # C. script-driven scrollBy
        reset_top(b)
        ev(b, "window.scrollBy(0, 560)")
        tl, landedC, finalC = poll_until_still(b)
        print("  C scrollBy(0,560)  start=%-5s landed at %-6s final=%-5s | timeline %s"
              % (tl[0][1], str(landedC) + "ms", finalC, json.dumps(tl[:40][::2])))
    except Exception as e:                                              # noqa: BLE001
        print("  EXC %s: %s" % (type(e).__name__, e))
    finally:
        if b is not None:
            b.close()
