r"""PubMed 的 403 到底是"硬墙"还是"冷画像方差"——量，不猜（#16 的缺口）。

为什么要单测这个形状：`reports/one-r104-1009-233239.json` 里 r104 单任务首拍观测
`title="403"`、steps 0，被判成 agent 决策失败；而 b18 同一题两次都进了真结果页
（`logs/real-1009-b18-expand-1009-215419/r104.jsonl` 第 2 拍就在 `?term=…` 上）。
同一台机器同一 URL，一边 403 一边正常 → 先分清是**站方拒了**还是**我们这侧的画像/代理
冷启方差**，再决定 #16 要不要把 403 收进墙词表（收错了就是 false_positive，红线）。

两路各测 N 次：
  1) 带外 `curl -x 127.0.0.1:2080`（不经浏览器，看 NCBI 自己怎么答）；
  2) 自有 headless Chrome 的真实观测（title / len(text) / n_actions / `is_bot_wall`）
     ——墙判据的三条阈值就在 evaluator 里，读数必须打在它自己的判据上。
对照页是**不能被判成墙**的：真结果页、单篇引文页，以及 pypi 首页（已知墙）。
只在没有批次在跑时使用（它驱动自有 headless Chrome `:9222`）。
"""
import io
import json
import os
import re
import subprocess
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\Administrator\openjev-ultrafast")
PROXY = "http://127.0.0.1:2080"
os.environ.setdefault("HTTP_PROXY", PROXY)
os.environ.setdefault("HTTPS_PROXY", PROXY)
os.environ.setdefault("HTTPX_PROXY", PROXY)
os.environ.setdefault("BU_CDP_URL", "http://127.0.0.1:9222")

from jev_ultrafast.browser import Browser, StalePage       # noqa: E402
from jev_ultrafast.evaluator import (is_bot_wall, _WALL_MAX_TEXT,   # noqa: E402
                                     _WALL_MAX_ACTIONS)
from jev_ultrafast import skills as S                       # noqa: E402

N = int(os.environ.get("PROBE_N", "6"))
URLS = [
    ("pubmed-root", "https://pubmed.ncbi.nlm.nih.gov/"),
    ("pubmed-results(r104 起点)", "https://pubmed.ncbi.nlm.nih.gov/?term=CRISPR+off-target"),
    ("pubmed-article(对照:不该是墙)", "https://pubmed.ncbi.nlm.nih.gov/36970624/"),
    ("pypi(对照:已知墙)", "https://pypi.org/"),
]


def curl_once(url):
    """带外 HTTP：只取状态码 + 响应体形状，不落盘。"""
    r = subprocess.run(["curl.exe", "-s", "-S", "-m", "25", "-x", PROXY,
                        "-o", os.devnull, "-w", "%{http_code} %{size_download}", url],
                       capture_output=True, timeout=40)
    out = r.stdout.decode("utf-8", "replace").strip()
    return out or ("ERR " + r.stderr.decode("utf-8", "replace").strip()[:60])


def observe_settled(b, want, tries=10):
    """轮询到 want(page) 成立或超时——`observe` 一非空就返回会读到 JS 未填的壳。"""
    p = None
    for k in range(tries):
        try:
            p = b.observe(screenshot=False)
        except StalePage:
            time.sleep(0.5)
            continue
        if want(p):
            return p, True
        time.sleep(0.6)
    return p, False


def main():
    print("== 带外 curl（每 URL %d 次）==" % N)
    for name, url in URLS:
        codes = [curl_once(url) for _ in range(N)]
        print("   %-28s %s" % (name, "  ".join(codes)))

    print("\n== 自有 Chrome 真实观测（每 URL %d 次；判据阈值 text<=%d actions<=%d）==" % (
        N, _WALL_MAX_TEXT, _WALL_MAX_ACTIONS))
    rows = []
    for name, url in URLS:
        for k in range(N):
            b = None
            try:
                b = Browser(url)
                p, settled = observe_settled(
                    b, lambda q: bool(S._indexed((q or {}).get("actions") or []))
                    and not re.match(r"^\s*403\s*$", str((q or {}).get("title") or "")))
                acts = S._indexed((p or {}).get("actions") or [])
                text = str((p or {}).get("text") or "")
                title = str((p or {}).get("title") or "")
                rows.append({"name": name, "try": k + 1, "title": title[:60],
                             "text_len": len(text), "n_indexed": len(acts),
                             "wall": is_bot_wall(p),
                             "url": str((p or {}).get("url") or "")[:70]})
                print("   %-28s try%d title=%-46r text=%-5d acts=%-3d wall=%-5s %s" % (
                    name, k + 1, title[:46], len(text), len(acts),
                    is_bot_wall(p), "settled" if settled else "TIMEOUT"))
            except Exception as e:
                print("   %-28s try%d NAV ERROR %r" % (name, k + 1, e))
                rows.append({"name": name, "try": k + 1, "error": repr(e)[:120]})
            finally:
                if b:
                    b.close()
            time.sleep(1.0)                 # 别把连打本身变成 403 的原因
    out = os.path.join(os.environ.get("TEMP", "."), "pubmed_403_probe.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=1)
    print("\nrows -> %s" % out)
    print("\n== 汇总：每个 URL 的 title 分布 / wall 命中 ==")
    for name, _ in URLS:
        sub = [r for r in rows if r["name"] == name]
        titles = {}
        for r in sub:
            t = r.get("title") or r.get("error") or "?"
            titles[t] = titles.get(t, 0) + 1
        print("   %-28s n=%d wall=%d titles=%s" % (
            name, len(sub), sum(1 for r in sub if r.get("wall")), titles))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
