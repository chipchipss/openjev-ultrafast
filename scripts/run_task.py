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
    # 断言拆分（计划书 2.3）：三类证据各自独立、彼此是 all_of（都要成立）。
    # 原来只有一个 --expect，同时塞进 url_matches 与 text_contains 再套 any_of —— 任一条
    # 命中就算过，这正是第一个真实任务翻车的地方（HN 那题：agent 点进外链，
    # --expect 写的是站内 item 链接 → MISSING）。判据也不再自己实现，见下面的 evaluator 调用。
    ap.add_argument("--expect-url", action="append", default=[], metavar="RE",
                    help="regex the FINAL url must match. Repeatable (all must hold).")
    ap.add_argument("--expect-title", action="append", default=[], metavar="STR",
                    help="substring the final page <title> must contain. Repeatable.")
    ap.add_argument("--expect-text", action="append", default=[], metavar="STR",
                    help="substring the final page text must contain. Repeatable.")
    ap.add_argument("--start-chrome", action="store_true",
                    help="kill+start a headless Chrome with CDP and the egress proxy")
    ap.add_argument("--headed", action="store_true", help="watch the browser work")
    args = ap.parse_args()

    proxy = os.environ.get("HTTPX_PROXY", "")
    if args.start_chrome:
        import shutil

        chrome = shutil.which("chrome") or r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        # Kill only OUR headless instance (identified by the CDP profile in its
        # command line) -- the user's own browser must never be collateral.
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
            "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" |"
            " Where-Object { $_.CommandLine -like '*chrome-cdp-test*' } |"
            " ForEach-Object { Stop-Process -Id $_.ProcessId -Force -EA SilentlyContinue }"],
            capture_output=True)
        time.sleep(2)
        flags = ["--headless=new" if not args.headed else "--start-maximized",
                 "--remote-debugging-port=9222", "--user-data-dir=C:\\chrome-cdp-test",
                 "--no-first-run", "--no-default-browser-check"]
        if proxy:
            flags.append(f"--proxy-server={proxy}")
        subprocess.Popen([chrome, *flags])
        time.sleep(8)

    # The decision backend must already be running (startlux_serve.ps1 / startlux_serve)
    # or is auto-started by the MCP server. Default to the StartLux wire (:8090);
    # the old decider on :8000 also matches if that is what is up.
    import urllib.request

    os.environ.setdefault("DECIDER_MODE", "typesafe")
    if not os.environ.get("TYPESAFE_BASE_URL"):
        if os.environ.get("OPENJEV_WIRE_PORT"):
            base = f"http://127.0.0.1:{os.environ['OPENJEV_WIRE_PORT']}/v1/systemone"
        else:
            def _alive(port: int) -> bool:
                try:
                    return urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/health", timeout=2).status == 200
                except Exception:
                    return False
            base = ("http://127.0.0.1:8090/v1/systemone" if _alive(8090)
                    else "http://127.0.0.1:8000/v1/systemone")
        os.environ["TYPESAFE_BASE_URL"] = base
    os.environ.setdefault("TYPESAFE_API_KEY", "local")

    from jev_ultrafast.agent import Agent

    clauses = ([{"type": "url_matches", "pattern": p} for p in args.expect_url]
               + [{"type": "title_contains", "value": v} for v in args.expect_title]
               + [{"type": "text_contains", "value": v} for v in args.expect_text])
    spec = {"task_id": "adhoc", "domain": "", "category": "browse",
            "goal": args.goal, "budget": {"steps": args.steps},
            # 没有任何证据时就给一个"永真但明说不是成功声明"的形状：any_of([]) 判 False，
            # 由下面的打印明确写"这只报状态，不声明成功"。
            "success_assertion": ({"type": "all_of", "clauses": clauses} if clauses
                                  else {"type": "any_of", "clauses": []})}

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
        if clauses:
            # 判据交给 `jev_ultrafast.evaluator`——与跑批判 PASS 的是同一份代码。
            # 这里原来自己实现"子串命中"，两套语义会漂移（本项目为文档与代码漂移付过代价）。
            from jev_ultrafast import evaluator as E
            r = E.evaluate(spec, page, hist, state.get("status") or "done")
            ok = str(r.result) == "PASS"
            print(f"verdict: {r.result}   quadrant={r.quadrant}")
            for t in (r.evidence or {}).get("assertion_trace") or []:
                c = t.get("clause") or {}
                key = "pattern" if c.get("type") == "url_matches" else "value"
                print("   %-4s %s %s=%r%s" % ("ok" if t.get("ok") else "MISS",
                                              c.get("type"), key, c.get(key),
                                              ("  (" + t["note"] + ")") if t.get("note") else ""))
        else:
            print("expect : (none given -- status only, not a success claim)")
        a.close()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())