"""Run an arbitrary task with a natural-language goal.

    python scripts/run_task.py --url https://en.wikipedia.org/ \
        --goal "Open the article about the Apollo program"
    python scripts/run_task.py --url https://httpbin.org/ \
        --goal "Go to /forms/post and fill the comments field with 'hi', then submit the form."

Start Chrome with CDP yourself first (run_demo.ps1 does this for you), or pass
--start-chrome. Prints a verdict from the evidence you gave via --expect.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    # Windows 控制台是 GBK：页面文本含非 GBK 字符时 print 会直接崩。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                                   # noqa: BLE001
            pass

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", required=True, help="starting URL")
    ap.add_argument("--goal", required=True, help="natural-language goal")
    ap.add_argument("--steps", type=int, default=20, help="step budget (default 20)")
    ap.add_argument("--expect", action="append", default=[],
                    help="completion evidence: a substring that must appear in the "
                         "final page's URL or text. Repeatable. Without it the run "
                         "reports status only, not success.")
    ap.add_argument("--start-chrome", action="store_true",
                    help="kill+start a headless Chrome with CDP and the egress proxy")
    ap.add_argument("--headed", action="store_true", help="watch the browser work")
    args = ap.parse_args()

    proxy = os.environ.get("HTTPX_PROXY", "")
    if args.start_chrome:
        import shutil
        chrome = shutil.which("chrome") or r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"], capture_output=True)
        time.sleep(2)
        flags = ["--headless=new" if not args.headed else "--start-maximized",
                 "--remote-debugging-port=9222", "--user-data-dir=C:\\chrome-cdp-test",
                 "--no-first-run", "--no-default-browser-check"]
        if proxy:
            flags.append(f"--proxy-server={proxy}")
        subprocess.Popen([chrome, *flags])
        time.sleep(8)

    # The decision backend must already be running (run_demo.ps1 / decider.serve).
    # Default to the production wire so an ad-hoc run "just works" against a bare
    # local decider on :8000 -- run_task.py raised "Missing DECIDER_2B_BASE_URL"
    # otherwise, because DECIDER_MODE unset falls back to the openai provider.
    os.environ.setdefault("DECIDER_MODE", "typesafe")
    os.environ.setdefault("TYPESAFE_BASE_URL", "http://127.0.0.1:8000/v1/systemone")
    os.environ.setdefault("TYPESAFE_API_KEY", "local")

    from jev_ultrafast.agent import Agent

    spec = {"task_id": "adhoc", "domain": "", "category": "browse",
            "goal": args.goal, "budget": {"steps": args.steps},
            "success_assertion": {"type": "any_of", "clauses": [
                {"type": "url_matches", "pattern": e.replace(".", r"\.")}
                for e in args.expect] +
                [{"type": "text_contains", "value": e} for e in args.expect]}}

    print(f"goal : {args.goal}")
    print(f"start: {args.url}")
    a = Agent(url=args.url, goals=args.goal, task_spec=spec)
    steps = 0
    try:
        for state in a.run():
            steps = len(state.get("history") or [])
            d = state.get("decision") or {}
            if d:
                print(f"  [{steps:>2}] {d.get('operation', '?'):<9} "
                      f"{str(d.get('choice')):<10}"
                      f"{('skill=' + d['skill']) if d.get('skill') else ''}")
            if state.get("status") in {"done", "blocked", "budget_exceeded"}:
                break
    finally:
        page = state.get("page") or {}
        hist = state.get("history") or []
        print()
        print(f"status : {state.get('status')}   steps: {len(hist)}")
        print(f"final  : {page.get('url')}")
        txt = (page.get("text") or "")[:300].replace("\n", " ")
        print(f"text   : {txt}")
        ok = True
        if args.expect:
            hay = f"{page.get('url') or ''}\n{page.get('text') or ''}".lower()
            missing = [e for e in args.expect if e.lower() not in hay]
            ok = not missing
            print(f"expect : {'PASS' if ok else 'MISSING ' + str(missing)}")
        else:
            print("expect : (none given -- status only, not a success claim)")
        a.close()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())