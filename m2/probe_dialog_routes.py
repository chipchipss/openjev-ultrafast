r"""#60 的路线对照：对话框有两条堵法，哪条**实测**能用？

现场事实（m2/out_download_wedge2.txt / 本轮探针）：/download 页面一加载就 `alert(1)`
（第三方上传的文件名里带的 `<img src=x onerror=alert(1)>`），modal 把 renderer 主线程钉住，
该 session 之后每一次 CDP 调用永久超时。两条候选堵法：

  A 反应式：`Page.enable` + `drain_events()` 看到 `Page.javascriptDialogOpening` 就 accept。
    —— 这条**已经量过并否掉**：经 daemon 排空 97 条事件里对话框 0 条
    （daemon 只把它自己 attach 的 session 的事件记进缓冲；我们的 session 它不转）。
  B 预防式：`Page.addScriptToEvaluateOnNewDocument` 在页面自己的脚本之前把
    `window.alert/confirm/prompt` 换成空函数，对话框根本不开。

本探针跑 B 的现场有效性：装补丁 → navigate → 观测 readyState/动作数，并对照不装补丁的 A 路。
零模型，只在没有批次在跑时用。
"""
import io
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\Administrator\openjev-ultrafast")
os.environ.setdefault("BU_CDP_URL", "http://127.0.0.1:9222")

from browser_harness.helpers import cdp, drain_events          # noqa: E402

URL = "https://the-internet.herokuapp.com/download"
NEUTRALIZE = ("(() => { for (const k of ['alert', 'confirm', 'prompt']) {"
              " try { window[k] = k === 'confirm' ? (() => true) : (() => undefined);"
              " } catch (e) {} } return 1; })()")


def route_b(label, which):
    tid = cdp("Target.createTarget", url="about:blank", background=True)["targetId"]
    sid = cdp("Target.attachToTarget", targetId=tid, flatten=True)["sessionId"]
    t0 = time.monotonic()
    try:
        cdp("Page.addScriptToEvaluateOnNewDocument", session_id=sid, source=NEUTRALIZE,
            _response_timeout=8)
        reg = "注册 ok"
    except Exception as e:
        reg = "注册失败 %s" % type(e).__name__
    try:
        cdp("Page.navigate", session_id=sid, url=URL, _response_timeout=8)
        nav = "navigate ok"
    except Exception as e:
        nav = "navigate %s" % type(e).__name__
    t1 = time.monotonic()
    try:
        v = cdp("Runtime.evaluate", session_id=sid,
                expression="document.readyState + '|a=' + document.querySelectorAll('a').length",
                returnByValue=True, _response_timeout=8)
        ev = "%s（+%.2fs）" % ((v.get("result") or {}).get("value"), time.monotonic() - t1)
    except Exception as e:
        ev = "evaluate %s（+%.2fs）" % (type(e).__name__, time.monotonic() - t1)
    print("  B %-10s %-8s %-10s %-16s %s" % (label, which, reg, nav, ev))
    n = len([e for e in drain_events() if e.get("method") == "Page.javascriptDialogOpening"])
    print("    排空到的对话框事件=%d" % n)
    cdp("Target.closeTarget", targetId=tid)


def route_a(label, which):
    tid = cdp("Target.createTarget", url="about:blank", background=True)["targetId"]
    sid = cdp("Target.attachToTarget", targetId=tid, flatten=True)["sessionId"]
    cdp("Page.enable", session_id=sid, _response_timeout=8)
    try:
        cdp("Page.navigate", session_id=sid, url=URL, _response_timeout=8)
        nav = "ok"
    except Exception as e:
        nav = type(e).__name__
    time.sleep(2.0)
    evs = drain_events()
    dl = [e for e in evs if e.get("method") == "Page.javascriptDialogOpening"]
    mine = [e for e in dl if e.get("session_id") == sid]
    print("  A %-10s %-8s navigate=%-22s 事件 %d / 对话框 %d / 本 session %d" %
          (label, which, nav, len(evs), len(dl), len(mine)))
    if dl:
        for e in dl:
            cdp("Page.handleJavaScriptDialog", session_id=sid, accept=True, _response_timeout=5)
        t = time.monotonic()
        try:
            cdp("Runtime.evaluate", session_id=sid, expression="document.readyState",
                returnByValue=True, _response_timeout=6)
            print("    accept 后 evaluate 恢复（+%.2fs）" % (time.monotonic() - t))
        except Exception as e:
            print("    accept 后仍超时：%s" % type(e).__name__)
    try:
        cdp("Target.closeTarget", targetId=tid)
    except Exception:
        pass


def main():
    for i in (1, 2):
        route_a("事件轮询" if i == 1 else "事件轮询", "第%d次" % i)
    for i in (1, 2):
        route_b("新文档补丁", "第%d次" % i)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
