r"""#58 的零模型复现：the-internet/download 页让 daemon 对**已有** target 的 evaluate 也不回答。

为什么要单独量：b22/b23 的 r142 崩在这一跳上，当时只能用"冷 dyno 125 秒"解释。现在
curl 取同一 URL 1.0 秒 200，自有 Chrome 里页面标题已经渲染（'The Internet'），但
`Runtime.evaluate("1+1")` 30 秒超时——所以卡点不在网站，在 harness/CDP 这一侧。
本探针不对任何读数负责，只回答一个问题：**attach 到已经加载好的 target，evaluate 还回不回**。

只在没有批次在跑时使用。
"""
import io
import json
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\Administrator\openjev-ultrafast")
os.environ.setdefault("BU_CDP_URL", "http://127.0.0.1:9222")

from browser_harness.helpers import cdp                          # noqa: E402
from jev_ultrafast.browser import READ_STATE, _ensure_daemon     # noqa: E402

URL = "https://the-internet.herokuapp.com/download"


def targets():
    import urllib.request
    with urllib.request.urlopen("http://127.0.0.1:9222/json/list", timeout=10) as r:
        return json.load(r)


def main():
    _ensure_daemon()
    tg = [t for t in targets() if t.get("type") == "page"]
    same = [t for t in tg if t.get("url") == URL]
    print("pages=%d  其中 %s = %d" % (len(tg), URL, len(same)))
    for t in tg:
        print("  %-8s %-10s %r" % (t["id"][:8], "download" if t in same else "other",
                                   str(t.get("title"))[:40]))

    # 现场造一个：自己 createTarget + attach + Page.navigate，逐步计时看 30 秒花在哪一步
    print("\n--- 现场导航（每一步 8 秒上限）---")
    own = cdp("Target.createTarget", url="about:blank", background=True)["targetId"]
    sid = cdp("Target.attachToTarget", targetId=own, flatten=True)["sessionId"]
    for step, params in (("Page.navigate", dict(url=URL)),
                         ("readyState#1", dict(expression="document.readyState")),
                         ("1+1", dict(expression="1+1")),
                         ("readyState#2", dict(expression="document.readyState"))):
        t0 = time.monotonic()
        try:
            v = cdp("Runtime.evaluate" if step != "Page.navigate" else step,
                    session_id=sid, _response_timeout=8, returnByValue=True, **params)
            print("  %-14s %6.2fs -> %s" % (step, time.monotonic() - t0,
                                            json.dumps(v.get("result", v))[:60]))
        except Exception as e:
            print("  %-14s %6.2fs -> %s" % (step, time.monotonic() - t0, type(e).__name__))
        time.sleep(1.0)
    same += [own]

    for i, t in enumerate(same, 1):
        sid = None
        try:
            sid = cdp("Target.attachToTarget", targetId=t["id"], flatten=True)["sessionId"]
        except Exception as e:
            print("  [%d] attach 失败：%s" % (i, type(e).__name__))
            continue
        t0 = time.monotonic()
        try:
            v = cdp("Runtime.evaluate", session_id=sid, expression="1+1",
                    returnByValue=True, _response_timeout=8)
            ok = "1+1=%r" % (v.get("result") or {})
        except Exception as e:
            ok = "超时/失败：%s" % type(e).__name__
        print("  [%d] 已有 target 的 evaluate（8s 上限）%.2fs -> %s" %
              (i, time.monotonic() - t0, ok))
        t1 = time.monotonic()
        try:
            v = cdp("Runtime.evaluate", session_id=sid,
                    expression="(() => { const s=%s; return String(s?.marker_stable ?? 'null').slice(0,24); })()" % READ_STATE,
                    returnByValue=True, _response_timeout=8)
            print("      snapshot.js -> %s（%.2fs）" % (
                json.dumps(v.get("result"))[:60], time.monotonic() - t1))
        except Exception as e:
            print("      snapshot.js -> %s（%.2fs）" % (type(e).__name__, time.monotonic() - t1))

    # 对照组：about:blank 的新 target 能不能 evaluate（同一 daemon，同一时刻）
    tid = cdp("Target.createTarget", url="about:blank", background=True)["targetId"]
    sid = cdp("Target.attachToTarget", targetId=tid, flatten=True)["sessionId"]
    t0 = time.monotonic()
    try:
        cdp("Runtime.evaluate", session_id=sid, expression="1+1",
            returnByValue=True, _response_timeout=8)
        ctrl = "正常"
    except Exception as e:
        ctrl = type(e).__name__
    print("对照组 about:blank 新 target evaluate：%.2fs -> %s" % (time.monotonic() - t0, ctrl))
    cdp("Target.closeTarget", targetId=tid)

    # 清理我自己泄漏的标签页（只关自有 Chrome :9222 里的 download 页）
    closed = 0
    for t in same:
        try:
            cdp("Target.closeTarget", targetId=t["id"])
            closed += 1
        except Exception:
            pass
    time.sleep(1.0)
    left = [t for t in targets() if t.get("url") == URL]
    print("关闭泄漏标签：%d，剩余：%d" % (closed, len(left)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
