r"""L3-C 的前置量测：`--parallel 4` 的 :8090 在并发下到底能吞多少决策（先测后设计）。

#34 记过一笔：50 行的批 91% 的墙钟在**任务之间**，不在 agent 里；#56 门控落地后
（b27–b29 三批 8.2–9.5 分钟/50 行）100 题已经在 30 分钟判据内，**300 题**才需要并行。
并行 runner 的前提只有一个还没量过：决策 wire 能不能同时服务多个 worker。
`scripts/startlux_serve.ps1` 起的是 `llama-server --parallel 4`，所以理论上限是 4，
但"槽位数"不等于"吞吐"——4 路并发可能只是把一条决策的耗时拉长 4 倍。

量法：同一个真实页面（`m2/fixtures/r126_arrival.json`，产品观测格式）+ 同一个 goal，
用**产品自己的** `model.choose_typesafe` 发请求（候选过滤、题型、温度全走原路），
并发 1/2/4/6 各若干次，记每次往返与总吞吐；同时采样 llama-server 的 RSS。
若 6 路比 1 路吞吐不涨反跌，就把 worker 数定在拐点。

需要 :8090 在线；不碰浏览器，所以代理挂了也能跑。
"""
import concurrent.futures as cf
import json
import os
import statistics
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\Administrator\openjev-ultrafast")
os.environ.setdefault("TYPESAFE_BASE_URL", "http://127.0.0.1:8090")
os.environ.setdefault("TYPESAFE_API_KEY", "local")
os.environ.setdefault("DECIDER_MODE", "typesafe")

from jev_ultrafast import model as M                        # noqa: E402

PAGE = json.load(open(r"C:\Users\Administrator\openjev-ultrafast\m2\fixtures"
                      r"\r126_arrival.json", encoding="utf-8"))
GOAL = "From the SQLite home page, open the 'SQL Syntax' page."
REPS = {1: 4, 2: 6, 4: 8, 6: 6}


def llama_rss_mb():
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-Process llama-server -EA SilentlyContinue | "
             "Measure-Object WorkingSet64 -Sum).Sum"],
            capture_output=True, timeout=20).stdout.decode("utf-8", "replace").strip()
        return round(float(out) / 1e6, 0) if out else 0.0
    except Exception:
        return -1.0


def one(i):
    # `choose_typesafe(state, …)` 的 state 就是**页面本身**（它读 state["actions"]，
    # model.py:167），不是 {"page": …}。第一版我传了 {"page": …}，于是每一发都在
    # KeyError 上瞬间返回——量出来的"266 决策/秒"是异常吞吐，不是模型吞吐。
    t0 = time.monotonic()
    try:
        d = M.choose_typesafe(PAGE, GOAL, [])
        return time.monotonic() - t0, (isinstance(d, dict) and bool(d.get("choice")))
    except Exception as e:
        return time.monotonic() - t0, "ERR:%s" % type(e).__name__


def main():
    print("wire =", os.environ["TYPESAFE_BASE_URL"], " 页面动作数 =", len(PAGE.get("actions") or []))
    base_t, ok0 = one(0)
    print("预热一发：%.2fs ok=%s" % (base_t, ok0))
    if ok0 is not True:
        raise SystemExit("预热就没打通，量出来的吞吐无意义（%s）" % ok0)
    rows = []
    for width, reps in REPS.items():
        t0 = time.monotonic()
        with cf.ThreadPoolExecutor(max_workers=width) as ex:
            res = list(ex.map(one, range(reps)))
        span = max(time.monotonic() - t0, 1e-6)
        lat = [r[0] for r in res]
        bad = [r[1] for r in res if r[1] is not True]
        rows.append((width, reps, span, statistics.median(lat), max(lat),
                     reps / span, llama_rss_mb(), len(bad)))
        print("  并发 %d：n=%d 总 %.2fs  中位延迟 %.2fs 最长 %.2fs  吞吐 %.2f 决策/秒"
              "  RSS %.0fMB  失败 %d" % rows[-1])
    best = max(rows, key=lambda r: r[5])
    print("\n吞吐最高在并发 %d（%.2f 决策/秒）；单路吞吐 %.2f → 加速比 %.2fx" % (
        best[0], best[5], rows[0][5], best[5] / rows[0][5]))
    print("判据：worker 数取吞吐不再上升的那一档；RSS 决定还能不能再开一个 Chrome 画像。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
