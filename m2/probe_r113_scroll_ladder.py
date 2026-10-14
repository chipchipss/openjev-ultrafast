r"""#46 的那页到底是哪一页：在**同一个浏览器会话**里沿 r113 的真实路径往下滚，逐拍抓页并当场重放地板。

为什么要滚着抓：离线在语料起点页上重放 `explicit_target` 是**弃权**的（起点页没有 'Style Guide' 那行），
而批内 tick 2 明明点中了 `pep-0007`（'Style Guide for C Code'）—— 所以错点发生在**滚动之后**那一页。
不抓到那一页，任何新档位都是凭想象加词（本仓的规矩：名词只收见过的）。

零模型：不调 decider、不调 Text Helper。滚用的是页面自己给出的 `scroll_down` 候选，
走产品的 `Browser.act`（含 Fix U 的偏移结算），与批内同一条路。

产物：逐拍一行 `scroll_y / nactions / 候选里 style-guide 的行 / explicit_target 的选择`，
并把每拍的整页写到 `m2/corpus/r113-ladder-<n>.json`（`m2/corpus/` 不入库：第三方正文）。

运行："C:/Users/Administrator/miniconda3/envs/jev/python.exe" m2/probe_r113_scroll_ladder.py [--steps 8]
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

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:2080")
os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:2080")
os.environ.setdefault("BU_CDP_URL", "http://127.0.0.1:9222")

from jev_ultrafast import skills as S                       # noqa: E402
from jev_ultrafast.browser import Browser, StalePage        # noqa: E402

GOAL = "Open PEP 8, 'Style Guide for Python Code'."
START = "https://peps.python.org/"
OUT_DIR = REPO / "m2" / "corpus"


def batch_in_flight() -> list:
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
          "Where-Object { $_.CommandLine -like '*run_tasks*' } | "
          "Select-Object -ExpandProperty ProcessId")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                         capture_output=True, text=True, timeout=30)
    return [x.strip() for x in (out.stdout or "").splitlines() if x.strip()]


def observe_settled(b, tries=12):
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


def style_rows(page: dict) -> list:
    hits = []
    for a in page.get("actions") or []:
        lab = str(a.get("label") or "")
        href = str(a.get("href") or "")
        if "style guide" in lab.lower() or "pep-0007" in href or "pep-0008" in href:
            hits.append((a.get("id"), lab[:42], href[:20]))
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=8)
    args = ap.parse_args()

    busy = batch_in_flight()
    if busy:
        print("REFUSED: 批次占着浏览器（pid %s）" % ",".join(busy), file=sys.stderr)
        return 4

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    hist: list = []
    b = None
    try:
        b = Browser(START)
        b.await_dom_settle()
        page = observe_settled(b)
        for n in range(args.steps + 1):
            if not isinstance(page, dict) or not page.get("url"):
                print("tick %d: 没读到页" % n, file=sys.stderr)
                return 5
            pick = S.explicit_target(page, GOAL, hist)
            scroll = page.get("scroll") or {}
            rows = style_rows(page)
            print("tick %-2d y=%-6s nact=%-4d pick=%-28s style-rows=%s" % (
                n, scroll.get("y"), len(page.get("actions") or []),
                ("%s -> %s" % (pick.get("target"), pick.get("kind")) if isinstance(pick, dict) else "None(弃权)"),
                [(r[0], r[1][:20], r[2]) for r in rows][:6]))
            with io.open(OUT_DIR / ("r113-ladder-%d.json" % n), "w", encoding="utf-8") as fh:
                json.dump({"goal": GOAL, "tick": n, "page": page}, fh, ensure_ascii=False)
            if n == args.steps:
                break
            cand = next((a for a in (page.get("actions") or [])
                         if a.get("kind") == "scroll" and "down" in str(a.get("id") or "")), None)
            if cand is None:
                print("  后面没有 scroll_down 候选了（抓到第 %d 拍为止）" % n, file=sys.stderr)
                return 0
            b.act(cand, page)
            hist.append({"choice": cand.get("id"), "kind": "scroll",
                         "operation": "SCROLL_DOWN", "url": page.get("url")})
            page = observe_settled(b)
    finally:
        if b is not None:
            try:
                b.close()
            except Exception:                                            # noqa: BLE001
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
