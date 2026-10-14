r"""#85 的真因探针：sqlite 那两行的失败到底在**页面**还是在**我们**。

为什么起这个探针：把 19 份 100 行批与 5 份 50 行批逐行对出来，同一个 host 的 sqlite 五行
失败率差得离谱 —— `r127`（点 `lang_select.html`）与 `r129`（点 `json1.html`）**每一批平均抛一次硬币**，
而 `r126 / r128 / r172 / r173` 36 批里各只失败 1 次：

| 行 | 位置 | 目标页 | 页数 | 非 PASS / 观测数 |
|---|---|---|---|---|
| r126 | 25 | `lang.html` | 34 KB | 1 / 36 |
| **r127** | 26 | `lang_select.html` | **2.03 MB** | **17 / 36** |
| r128 | 27 | `faq.html` | 37 KB | 1 / 36 |
| **r129** | 28 | `json1.html` | 71 KB | **19 / 36** |
| r174 | 72 | `pragma.html` | 140 KB | 2 / 19 |

⇒ 这些行在批里全被记成 `blocked_by_egress / system`（终页 `chrome-error://chromewebdata/`），
也就是"环境的锅"。但同一 host 的兄弟行几乎不失败 ⇒ **"批内瞬时出口失败"这个说法解释不了 17/36 与 19/36**。
要么这两行的目标页确实打不开（题集可行性问题，走 r118/r106 那两条先例），要么是我们的点击/观测路径有问题
（产品问题）。两种结论的动作完全相反，所以必须测。

两臂都跑，各 N 次，**零模型**（不调 decider、不调 Text Helper）：
- A 臂 `direct`：`Browser(目标 URL)` 直接导航，问"这页经 :2080 打得开吗"。
- B 臂 `click`：`Browser(起点页)` → 在起点页里找 label 匹配的行 → 用产品的 `Browser.act` 点它，
  复现批内那一拍（问"我们点它的时候打得开吗"）。

判读：A 臂也不通 ⇒ 站点/代理侧，走行先例；A 臂通、B 臂不通 ⇒ 我们的路径有问题，归产品。

运行："C:/Users/Administrator/miniconda3/envs/jev/python.exe" m2/probe_sqlite_reachability.py [--trials 10]
产物：stdout 的逐臂计数（页快照不落盘，避免第三方正文进仓）。
"""
from __future__ import annotations

import argparse
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

from jev_ultrafast.browser import Browser, StalePage        # noqa: E402

HOME = "https://www.sqlite.org/"
LANG = "https://www.sqlite.org/lang.html"

# (标签, 起点页, 目标 URL, 起点页里那一行的 label 关键词)
CASES = [
    ("r126 lang.html",      HOME, "https://www.sqlite.org/lang.html",       "SQL Syntax"),
    ("r127 lang_select",    LANG, "https://www.sqlite.org/lang_select.html", "SELECT"),
    ("r128 faq.html",       HOME, "https://www.sqlite.org/faq.html",         "Frequently Asked Questions"),
    ("r129 json1.html",     HOME, "https://www.sqlite.org/json1.html",       "JSON functions"),
    ("r174 pragma.html",    HOME, "https://www.sqlite.org/pragma.html",      "PRAGMA"),
]


def batch_in_flight() -> list:
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
          "Where-Object { $_.CommandLine -like '*run_tasks*' } | "
          "Select-Object -ExpandProperty ProcessId")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                         capture_output=True, text=True, timeout=30)
    return [x.strip() for x in (out.stdout or "").splitlines() if x.strip()]


def observe_settled(b, tries=8):
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


def dead(url: str) -> bool:
    return url.startswith(("chrome-error://", "about:neterror"))


def arm_direct(url: str, trials: int) -> tuple:
    ok = bad = 0
    lens = []
    for i in range(trials):
        b = None
        try:
            b = Browser(url)
            b.await_dom_settle()
            page = observe_settled(b)
            u = str((page or {}).get("url") or "")
            if page and not dead(u):
                ok += 1
                lens.append(len(str(page.get("text") or "")))
            else:
                bad += 1
                print("    direct %-20s 第 %d 次不通: url=%s" % (url.split("/")[-1], i + 1, u[:44]))
        except Exception as e:                                       # noqa: BLE001
            bad += 1
            print("    direct %-20s 第 %d 次异常: %s: %s"
                  % (url.split("/")[-1], i + 1, type(e).__name__, str(e)[:60]))
        finally:
            if b is not None:
                try:
                    b.close()
                except Exception:                                    # noqa: BLE001
                    pass
    return ok, bad, lens


def arm_click(start: str, needle: str, trials: int) -> tuple:
    ok = bad = notfound = 0
    for i in range(trials):
        b = None
        try:
            b = Browser(start)
            b.await_dom_settle()
            page = observe_settled(b)
            cand = next((a for a in ((page or {}).get("actions") or [])
                         if a.get("kind") == "click" and needle.lower() in str(a.get("label") or "").lower()),
                        None)
            if cand is None:
                notfound += 1
                print("    click  %-20s 第 %d 次没找到 label %r" % (start.split("/")[-1], i + 1, needle))
                continue
            b.act(cand, page)
            b.await_dom_settle()
            page2 = observe_settled(b)
            u = str((page2 or {}).get("url") or "")
            if page2 and not dead(u):
                ok += 1
            else:
                bad += 1
                print("    click  label=%r 第 %d 次不通: url=%s" % (needle, i + 1, u[:44]))
        except Exception as e:                                       # noqa: BLE001
            bad += 1
            print("    click  label=%r 第 %d 次异常: %s: %s"
                  % (needle, i + 1, type(e).__name__, str(e)[:60]))
        finally:
            if b is not None:
                try:
                    b.close()
                except Exception:                                    # noqa: BLE001
                    pass
    return ok, bad, notfound


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=10)
    args = ap.parse_args()
    busy = batch_in_flight()
    if busy:
        print("REFUSED: 批次占着浏览器（pid %s）" % ",".join(busy), file=sys.stderr)
        return 4

    print("每臂 %d 次，零模型，走 :2080 与自有 chrome-cdp-test\n" % args.trials)
    for label, start, url, needle in CASES:
        a_ok, a_bad, a_lens = arm_direct(url, args.trials)
        b_ok, b_bad, b_nf = arm_click(start, needle, args.trials)
        med = sorted(a_lens)[len(a_lens) // 2] if a_lens else 0
        print("%-18s A 直接导航 通 %2d / 不通 %2d (正文中位 %d 字符)   "
              "B 从起点页点 通 %2d / 不通 %2d / 找不到行 %d"
              % (label, a_ok, a_bad, med, b_ok, b_bad, b_nf))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
