r"""零模型抓**一页**的快照，交给 `m2/replay_two_builds.py` 做"是我还是站点"的判定。

只 navigate + observe（不调模型），输出一条 JSON 到 stdout：
`{"page":…, "goal":…, "came_from":…, "via_label":…, "history":null}`。

规矩同 `m2/probe_tier3_corpus.py`：`BU_CDP_URL` 钉死自有 Chrome、有批在跑就拒绝、
产物落在不入库的 `m2/corpus/`（页快照里是第三方正文）。

运行：python m2/probe_one_page.py --url https://arxiv.org/search/physics \\
        --goal "…" --came-from https://arxiv.org/ --via-label Search > m2/corpus/oneoff.json
"""
from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:2080")
os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:2080")
os.environ.setdefault("BU_CDP_URL", "http://127.0.0.1:9222")

from jev_ultrafast.browser import Browser, StalePage                    # noqa: E402


def batch_in_flight() -> list:
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
          "Where-Object { $_.CommandLine -like '*m1\\run_tasks*' -or $_.CommandLine -like '*run_tasks.py*' } | "
          "Select-Object -ExpandProperty ProcessId")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                             capture_output=True, text=True, timeout=30)
    except Exception:                                                    # noqa: BLE001
        return ["<check failed>"]
    return [x.strip() for x in (out.stdout or "").splitlines() if x.strip()]


def observe_settled(b, tries=10):
    p = None
    for _ in range(tries):
        try:
            p = b.observe(screenshot=False)
        except StalePage:
            p = None
        if str((p or {}).get("title") or "").strip():
            return p
        time.sleep(0.5)
    return p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--goal", required=True)
    ap.add_argument("--came-from", default="")
    ap.add_argument("--via-label", default="")
    ap.add_argument("--scroll", type=int, default=0,
                    help="在首次观测之后按产品自己的 scroll 路径滚 N 次（每次都重新观测）。"
                         "#46 要的正是**滚动后**那一页：r113 的错点在 tick 2，起点页上根本复现不出来。")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    busy = batch_in_flight()
    if busy and not args.force:
        print("REFUSED: 批次占着浏览器（pid %s）" % ",".join(busy), file=sys.stderr)
        return 4

    b = None
    try:
        b = Browser(args.url)
        b.await_dom_settle()
        page = observe_settled(b)
        for i in range(args.scroll):
            # 用页面自己给出的 scroll_down 候选，不造 delta：这条路径与批内一致（含 Fix U 的偏移等待）。
            cand = next((a for a in (page.get("actions") or [])
                         if a.get("kind") == "scroll" and "down" in str(a.get("id") or "")), None)
            if cand is None:
                print("STOP: 第 %d 次滚动没有 scroll_down 候选，抓到的是滚之前那页" % (i + 1),
                      file=sys.stderr)
                break
            b.act(cand, page)
            page = observe_settled(b)
    finally:
        if b is not None:
            try:
                b.close()
            except Exception:                                            # noqa: BLE001
                pass
    if not isinstance(page, dict) or not page.get("url"):
        print("REFUSED: 没读到页", file=sys.stderr)
        return 5
    rec = {"page": page, "goal": args.goal, "came_from": args.came_from,
           "via_label": args.via_label, "history": None,
           "scrolls": args.scroll,
           "snapshot_note": ("零模型当场抓的页；scrolls=%d title=%r actions=%d text_len=%d"
                             % (args.scroll,
                                str(page.get("title") or "")[:40],
                                len(page.get("actions") or []),
                                len(str(page.get("text") or ""))))}
    json.dump(rec, io.open(sys.stdout.fileno(), "w", closefd=False, encoding="utf-8"),
              ensure_ascii=False)
    print("", file=sys.stderr)
    print(rec["snapshot_note"], file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
