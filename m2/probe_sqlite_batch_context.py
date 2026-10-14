r"""#85 的定位探针：批内顺序会决定 sqlite 那两行失败，那就把**错误码**抓出来。

现场（10-14 16:5x，同一台机器、同一代理、同一自有 Chrome）：

| 臂 | 顺序 | 结果 |
|---|---|---|
| P（题集原顺序）| home→lang / lang→lang_select / home→faq / home→json1 | `r127`、`r129` **FAIL `blocked_by_egress`**，另两行 PASS |
| R（完全反序）  | home→json1 / home→faq / lang→lang_select / home→lang | **4/4 PASS** |

⇒ 失败不随行身份（R 里同一行同一目标页过了），也不是简单奇偶（R 的第 2、4 位也过了）。
而 `m2/probe_sqlite_reachability.py` 刚量到这两页**单独访问 8/8 全通**（直接导航与点击两臂）
⇒ 站点没有锁我们，锁的是"批内那一串请求的某种形状"。

这一支探针要拿的是**从没进过工件的那 83 个字符**：批里失败行的终页是
`chrome-error://chromewebdata/`、`text_len=83`，而 Chrome 的错误页正文里写着 `ERR_...` 的名字。
今天之前它只在 `text_len` 里留下长度，正文没落盘（#75 的口径就是不带正文），所以没人看得见错误码。

做法：零模型复现 P 臂的四拍（起点页 → 点 goal 那一行 → 读页），一旦落在 `chrome-error://` 就把
`document.title` 与 `body.innerText` 原样打印（只在 stdout，不落盘、不进仓）。重复 N 轮直到抓到或到上限。

运行："C:/Users/Administrator/miniconda3/envs/jev/python.exe" m2/probe_sqlite_batch_context.py [--rounds 4]
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

# (行号, 起点页, 要点的 label) —— 与 m2/tasks_real_50.jsonl 里 r126..r129 的题面一致
P_SEQUENCE = [
    ("r126", HOME, "SQL Syntax"),
    ("r127", LANG, "SELECT"),
    ("r128", HOME, "Frequently Asked Questions"),
    ("r129", HOME, "JSON functions"),
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


def dead(u: str) -> bool:
    return u.startswith(("chrome-error://", "about:neterror"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=4)
    args = ap.parse_args()
    busy = batch_in_flight()
    if busy:
        print("REFUSED: 批次占着浏览器（pid %s）" % ",".join(busy), file=sys.stderr)
        return 4

    caught = 0
    for rnd in range(1, args.rounds + 1):
        print("=== 第 %d 轮：复现 P 臂四拍 ===" % rnd)
        for tid, start, needle in P_SEQUENCE:
            b = None
            try:
                b = Browser(start)
                b.await_dom_settle()
                page = observe_settled(b)
                cand = next((a for a in ((page or {}).get("actions") or [])
                             if a.get("kind") == "click"
                             and needle.lower() in str(a.get("label") or "").lower()), None)
                if cand is None:
                    print("   %-5s 起点页上没有 %r 这一行（跳过）" % (tid, needle))
                    continue
                b.act(cand, page)
                b.await_dom_settle()
                p2 = observe_settled(b)
                u2 = str((p2 or {}).get("url") or "")
                if dead(u2):
                    caught += 1
                    title = str((p2 or {}).get("title") or "")
                    body = str((p2 or {}).get("text") or "")
                    err = ""
                    try:
                        err = str(b.evaluate("document.body ? document.body.innerText : ''") or "")
                    except Exception as e:                            # noqa: BLE001
                        err = "<evaluate 失败 %s: %s>" % (type(e).__name__, str(e)[:40])
                    print("   %-5s 落在错误页  title=%r text_len=%d" % (tid, title, len(body)))
                    print("        错误页正文：%s" % " / ".join(
                        x.strip() for x in (err or body).splitlines() if x.strip())[:400])
                else:
                    print("   %-5s 通  -> %s (正文 %d 字符)" % (
                        tid, u2[:44], len(str((p2 or {}).get("text") or ""))))
            finally:
                if b is not None:
                    try:
                        b.close()
                    except Exception:                                 # noqa: BLE001
                        pass
        if caught:
            break
    if not caught:
        print("结论：本轮没复现（P 臂四拍全通）⇒ 现象不是顺序的确定函数，"
              "还要往「这一串请求的时间密度」上找。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
