"""Zero-model probe for r119's steps=0 death (Hugging Face homepage).

Reproduces the run without a browser race: what does the skill floor say, and
if it abstains, can the code path that a model TYPE_TEXT lands on actually
obtain a value?

Run:  C:/Users/Administrator/miniconda3/envs/jev/python.exe scripts/probe_r119_helper.py
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("HTTPX_PROXY", "http://127.0.0.1:2080")
os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:2080")

from jev_ultrafast import skills                          # noqa: E402
from jev_ultrafast.browser import Browser, StalePage      # noqa: E402
from jev_ultrafast.model import field_context, field_text  # noqa: E402

URL = "https://huggingface.co/"
GOAL = ("Search Hugging Face for 'bert-base-uncased' and open the model page "
        "'google-bert/bert-base-uncased'.")


def main() -> int:
    print("TEXT_HELPER_BASE_URL =", repr(os.environ.get("TEXT_HELPER_BASE_URL")))
    print("TEXT_HELPER_FALLBACK_BASE_URL =",
          repr(os.environ.get("TEXT_HELPER_FALLBACK_BASE_URL")))

    b = Browser(URL)
    try:
        page = b.observe(screenshot=False)
    except StalePage as e:
        print("observe failed:", e)
        b.close()
        return 2
    print(f"\nurl   {page['url']}")
    print(f"title {page.get('title')!r}")
    print(f"fp    {(page.get('fingerprint') or '')[:12]}  actions={len(page['actions'])}")
    print("\n-- first 12 actions --")
    for a in page["actions"][:12]:
        print(f"  {a['id']:>4} {a['kind']:<7} label={a.get('label')!r:<45} "
              f"node={str(a.get('node'))[:40]!r}")

    fills = [a for a in page["actions"] if a["kind"] == "fill"]
    print(f"\nfillable actions: {[a['id'] for a in fills] or 'NONE'}")

    d = skills.route(page, GOAL, [])
    print("\n-- skill floor --")
    print("  route() ->", json.dumps(d, ensure_ascii=False)[:220] if d else None)

    print("\n-- what a model TYPE_TEXT would do --")
    target = next((a for a in fills if a["id"] == "e2"), fills[0] if fills else None)
    if target is None:
        print("  no fill action on the page: TYPE_TEXT could not be offered at all")
    else:
        ctx = field_context(GOAL, target, page, [])
        print(f"  field={target['id']} label={target.get('label')!r}")
        print(f"  context keys={list(ctx)} field_desc="
              f"{json.dumps(ctx.get('field'), ensure_ascii=False)[:160]}")
        try:
            value, helper = field_text(ctx)
            print(f"  field_text OK -> {value!r} via {helper['model']}")
        except Exception as e:                              # noqa: BLE001
            print(f"  field_text RAISED {type(e).__name__}: {e}")
            print("  -> agent.py catches this and blocks after 3 in a row "
                  "(helper_fail_run >= 3): 3 model decisions, steps=0.")
    b.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
