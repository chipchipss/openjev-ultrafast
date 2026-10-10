r"""#57 的形状探针：任务**起点**的"快照为空 / 文档在导航"会持续多久（零模型）。

为什么要这个数：b21 的三行丢分（r139/r140/r141）死在 `Agent.__init__` 的第一次 `observe`，
上限是 `agent.py:142-155` 的 6 次退避 = **6.0 s**，越过就抛穿构造函数、整行连 trace 都没有。
"要不要把 6 秒加到 10 秒"这种问题不能靠拍数字回答——`Browser.__init__` 已经等了
`readyState=complete`（上限 15 s）+ `_await_settle(5000,1200,250)`，所以起点慢的**第二段**
（complete 之后又起了一次导航、快照脚本返回 null 多久）才是这一刀的形状。

这一发按真实 runner 的调用顺序做：同一个进程里一题接一题地 `Browser(url)` → `observe` → `close()`
（**不**重启浏览器，就是 b21 的那个条件），每题打：
  - `Browser.__init__` 耗时、readyState 是否 complete
  - 第一次 observe 的结果 / 重试轮数 / 空快照持续了多久
只在没有批次在跑时使用。
"""
import io
import json
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\Administrator\openjev-ultrafast")
os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:2080")
os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:2080")
os.environ.setdefault("BU_CDP_URL", "http://127.0.0.1:9222")

from jev_ultrafast.browser import Browser, StalePage, READ_STATE   # noqa: E402

# b21 里连挂三行的那一族，按题序取 8 个页面（含挂掉的 r139/r140/r141 与之后恢复正常的 r142）
URLS = [
    "https://the-internet.herokuapp.com/dropdown",
    "https://the-internet.herokuapp.com/add_remove_elements/",
    "https://the-internet.herokuapp.com/disappearing_elements",
    "https://the-internet.herokuapp.com/download",
    "https://the-internet.herokuapp.com/checkboxes",
    "https://the-internet.herokuapp.com/multiple_buttons",
    "https://the-internet.herokuapp.com/status_codes",
    "https://the-internet.herokuapp.com/wysiwyg",
]


def main():
    rows = []
    for k, url in enumerate(URLS, 1):
        t0 = time.perf_counter()
        b = Browser(url)                       # 内部已等 readyState(≤15s) + settle(≤5s)
        t_init = time.perf_counter() - t0
        ready = None
        null_ms = 0.0
        tries = 0
        outcome = "ok"
        try:
            ready = b.evaluate("document.readyState")
            t1 = time.perf_counter()
            try:
                p = b.observe(screenshot=False)
                null_ms = time.perf_counter() - t1
            except StalePage as e:
                outcome = "StalePage: %s" % e
                null_ms = time.perf_counter() - t1
            # 快照脚本自己返回 null 的持续时间：这是 observe 里那 10×20ms 在赌的东西
            tn = time.perf_counter()
            while time.perf_counter() - tn < 12 and b.evaluate(READ_STATE) is None:
                tries += 1
                time.sleep(0.05)
            null_again = time.perf_counter() - tn
        except Exception as e:
            outcome = "ERROR %s: %s" % (type(e).__name__, str(e)[:60])
            null_again = -1
        finally:
            b.close()
        rows.append({"url": url.split("/")[-1] or url, "init_s": round(t_init, 2),
                     "ready": ready, "observe_s": round(null_ms, 2), "outcome": outcome,
                     "null_snapshot_s": round(null_again, 2)})
        print("  [%d] %-22s init=%5.2fs readyState=%-10s observe=%5.2fs null=%5.2fs %s" % (
            k, url.split("/")[-1][:22], t_init, str(ready)[:10], null_ms, null_again,
            "" if outcome == "ok" else outcome))
        time.sleep(1.0)
    worst_init = max(r["init_s"] for r in rows)
    worst_null = max(r["null_snapshot_s"] for r in rows if r["null_snapshot_s"] >= 0)
    print("\n最慢 init=%.1fs  最长空快照=%.1fs  （Agent init 的退避预算=6.0s）" % (
        worst_init, worst_null))
    print(json.dumps(rows, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
