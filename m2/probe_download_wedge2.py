r"""#58 的零模型复现（第二次量）：wedge 是**这个 URL 特有**还是**每个 session 都会**？会自己恢复吗？

为什么还要再量一轮：上一轮只证明了"navigate 0.97s 返回后，该 session 的 evaluate 一直超时，
同时新开的 about:blank 0.02s 正常"。这不区分三种解释：
  A 该 URL 的页面把 renderer 主线程卡住（curl 取子资源全 200/1s，弱支持）
  B daemon 为该 session 等一个永不到来的事件（load/首帧），别的 session 不受影响
  C heroku 站点级（换同站别的页也 wedge）
本轮把 A/B/C 分开：同站根路径 + 外站对照 + 对 wedge 的 session 持续轮询到恢复或 120s。

只在没有批次在跑时使用（驱动自有 headless Chrome `:9222`，零模型）。
"""
import io
import json
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\Administrator\openjev-ultrafast")
os.environ.setdefault("BU_CDP_URL", "http://127.0.0.1:9222")

from browser_harness.helpers import cdp                        # noqa: E402
from jev_ultrafast.browser import _ensure_daemon               # noqa: E402

CASES = [
    ("heroku /download", "https://the-internet.herokuapp.com/download"),
    ("heroku /", "https://the-internet.herokuapp.com/"),
    ("example.com", "https://example.com/"),
    ("heroku /download 第二次", "https://the-internet.herokuapp.com/download"),
]
POLL_BUDGET = 120


def mk(url):
    tid = cdp("Target.createTarget", url="about:blank", background=True)["targetId"]
    sid = cdp("Target.attachToTarget", targetId=tid, flatten=True)["sessionId"]
    cdp("Page.navigate", session_id=sid, url=url, _response_timeout=10)
    return tid, sid


def ev(sid, expr="1+1", cap=6):
    t0 = time.monotonic()
    try:
        cdp("Runtime.evaluate", session_id=sid, expression=expr,
            returnByValue=True, _response_timeout=cap)
        return time.monotonic() - t0, None
    except Exception as e:
        return time.monotonic() - t0, type(e).__name__


def main():
    _ensure_daemon()
    opened = []
    handles = {}
    for name, url in CASES:
        try:
            tid, sid = mk(url)
            handles[name] = (tid, sid)
        except Exception as e:
            print("%-26s 导航就失败：%s" % (name, type(e).__name__))
    time.sleep(2.0)
    print("导航后 2 秒，每个 session 各试一次 evaluate（6 秒上限）：")
    wedged = []
    for name, (tid, sid) in handles.items():
        dt, err = ev(sid)
        print("  %-26s %5.2fs %s" % (name, dt, err or "正常"))
        if err:
            wedged.append(name)

    for name in wedged:
        sid = handles[name][1]
        t0 = time.monotonic()
        marks = []
        while time.monotonic() - t0 < POLL_BUDGET:
            time.sleep(5)
            dt, err = ev(sid, cap=5)
            if not err:
                marks.append("恢复于 +%.0fs" % (time.monotonic() - t0))
                break
        else:
            marks.append("%ds 内始终超时（累计 %d 次）" % (POLL_BUDGET, (time.monotonic() - t0) // 5))
        print("  %-26s -> %s" % (name, marks[-1]))

    # readyState / url 到底停在哪个状态？能回答的 session 都问一遍
    for name, (tid, sid) in handles.items():
        dt, err = ev(sid, "document.readyState + '|' + location.href", cap=4)
        if err:
            print("  %-26s 状态不可读（%s）" % (name, err))
        else:
            v = cdp("Runtime.evaluate", session_id=sid,
                    expression="document.readyState + '|' + location.href + '|anchors=' + document.querySelectorAll('a').length",
                    returnByValue=True, _response_timeout=4)
            print("  %-26s %s" % (name, (v.get("result") or {}).get("value")))
        opened.append(tid)

    for tid in opened:
        try:
            cdp("Target.closeTarget", targetId=tid)
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
