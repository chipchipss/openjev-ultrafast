"""Is there a render window on rfc-editor where the result row is not yet there?

Freeze rounds 2/3 lost n004 the same way: after pressing Submit the agent sat on
/search/?q=RFC+9110, the floor proposed nothing, and the model kept clicking
'Submit search' (conf ~0.29). Navigating straight to that URL, `explicit_target`
DOES pick the row (probe_n004_result_page.py: e25, conf 1.0). So the difference
is not the page, it is *when* we looked at it.

No model: fill, submit, then observe at t=0 / +1s / +2s and report whether a row
containing '9110' is in `actions`.

Run:  C:/Users/Administrator/miniconda3/envs/jev/python.exe scripts/probe_n004_render_race.py
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("HTTPX_PROXY", "http://127.0.0.1:2080")

from jev_ultrafast.browser import Browser, StalePage   # noqa: E402

START = "https://www.rfc-editor.org/"
QUERY = "RFC 9110"


def shape(page, tag):
    labels = [a.get("label") or "" for a in page["actions"]]
    rows = [l for l in labels if "9110" in l]
    print(f"{tag:<10} url={page['url'][:52]:<52} actions={len(page['actions']):>3} "
          f"rows_with_9110={len(rows)} {rows[:1]!r}")
    return bool(rows)


def observe(b, tag):
    for attempt in range(5):
        try:
            return b.observe(screenshot=False)
        except StalePage as e:
            print(f"{tag:<10} StalePage({e}) -- retry {attempt + 1}")
            time.sleep(0.3)
    raise SystemExit(f"{tag}: could not observe")


def main() -> int:
    b = Browser(START)
    try:
        page = observe(b, "t=start")
        fill = next((a for a in page["actions"]
                     if a["kind"] == "fill"), None)
        if fill is None:
            print("no fillable action on the index page")
            return 2
        print(f"fill target: {fill['id']} {fill.get('label')!r}")
        b.act(fill, page, text=QUERY)
        page = observe(b, "t=filled")
        submit = next((a for a in page["actions"]
                       if a["kind"] == "click"
                       and "submit" in (a.get("label") or "").lower()), None)
        if submit is None:
            print("no 'Submit...' click after filling; actions="
                  f"{[a.get('label') for a in page['actions']][:12]}")
            return 2
        print(f"submit: {submit['id']} {submit.get('label')!r}")
        b.act(submit, page)

        page = observe(b, "t=0")
        found = shape(page, "t=0")
        for wait in (1.0, 2.0, 3.0):
            time.sleep(wait)
            page = observe(b, f"t+{wait}")
            found = shape(page, f"after +{wait}s") or found
        print("\nrow ever present:", found)

        # The round did not stop here: the model kept clicking 'Submit search'
        # on the results page (4x in m1-baseline-1008-1336). Does our own
        # re-submit destroy the rows -- i.e. is the in-round page shape really
        # the one where the floor has nothing to pick?
        print("\n-- re-submit loop, the way the failing round did --")
        for k in range(1, 4):
            again = next((a for a in page["actions"]
                          if a["kind"] == "click"
                          and (a.get("label") or "").strip().lower()
                          .startswith("submit")), None)
            if again is None:
                print(f"  press {k}: no 'Submit search' action left "
                      f"(labels={[a.get('label') for a in page['actions']][:8]!r})")
                break
            b.act(again, page)
            page = observe(b, f"press{k}")
            shape(page, f"press {k}")
        print("=> if a re-submit drops the row, the round's abstention is the "
              "page shape, not a floor guard.")
    finally:
        b.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
