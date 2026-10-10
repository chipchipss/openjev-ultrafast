r"""#60 的第四轮：防御**装上了**、前 8 次 evaluate 都答，第 9 次楔 124 秒——问"那时候开着的是什么框"。

`m2/out_dialog_routes3.txt` 证明 defineProperty 版补丁在裸路径上 3/3 挡住（0 个对话框事件、
evaluate 0.03s 回 `complete|a=201`）。真实 `Browser(url)` 的调用序列里补丁确实注册了
（`Page.addScriptToEvaluateOnNewDocument 0.01s ok`），却在 `_settle_patch`/`_await_settle`
那一步楔住 124.19 秒——和 b18–b24 里 step 1 的 124.5/124.8 是同一个数。
差别只可能在"什么时候弹"：裸路径睡 3 秒只查一次；真实路径在这 3 秒里**连续发 8 次
snapshot.js**，把 `<img src=x>` 的加载往前挤。

所以本轮把楔住那一刻的证据取回来：撞超时以后立刻 `drain_events()`，打印每个
`Page.javascriptDialogOpening` 的 `type/message/frameId`，再 accept 后重发同一条 evaluate。
零模型。
"""
import io
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\Administrator\openjev-ultrafast")
os.environ.setdefault("BU_CDP_URL", "http://127.0.0.1:9222")

from browser_harness.helpers import cdp, drain_events          # noqa: E402
import jev_ultrafast.browser as B                              # noqa: E402

URL = "https://the-internet.herokuapp.com/download"
SEEN = []


ORIG_CALL = B.Browser.call


def logged(self, method, _response_timeout=30.0, **p):
    t0 = time.monotonic()
    try:
        r = ORIG_CALL(self, method, _response_timeout, **p)
        dt = time.monotonic() - t0
        SEEN.append((method, round(dt, 2), None, str(p.get("expression") or "")[:60]))
        return r
    except Exception as e:
        dt = time.monotonic() - t0
        SEEN.append((method, round(dt, 2), type(e).__name__, str(p.get("expression") or "")[:60]))
        raise


def main():
    B.Browser.call = logged
    tid_holder = {}
    real_create = B.cdp

    def cdp_patched(method, session_id=None, _response_timeout=None, **params):
        r = real_create(method, session_id=session_id, _response_timeout=_response_timeout,
                        **params)
        if method == "Target.createTarget":
            tid_holder["tid"] = r.get("targetId")
        if method == "Target.attachToTarget":
            tid_holder["sid"] = r.get("sessionId")
        return r
    B.cdp = cdp_patched
    try:
        b = B.Browser(URL)
        print("构造成功（没楔住？）")
        b.close()
        return 0
    except Exception as e:
        print("构造失败:", type(e).__name__)
    print("最后 6 次调用：")
    for m, dt, err, ex in SEEN[-6:]:
        print("   %-18s %7.2fs %-24s %s" % (m, dt, err or "", ex))
    sid = tid_holder.get("sid")
    evs = drain_events()
    dl = [e for e in evs if e.get("method") == "Page.javascriptDialogOpening"]
    print("排空 %d 事件，其中对话框 %d 个：" % (len(evs), len(dl)))
    for e in dl:
        pp = e.get("params") or {}
        print("   type=%-12s message=%-20r session匹配=%s frameId=%s url=%s" % (
            pp.get("type"), str(pp.get("message"))[:20], e.get("session_id") == sid,
            str(pp.get("frameId"))[:8], str(pp.get("url"))[:44]))
    for e in dl:
        try:
            cdp("Page.handleJavaScriptDialog", session_id=sid, accept=True, _response_timeout=5)
        except Exception as ex:
            print("   accept 失败", type(ex).__name__)
    t0 = time.monotonic()
    try:
        v = cdp("Runtime.evaluate", session_id=sid, expression="document.readyState",
                returnByValue=True, _response_timeout=8)
        print("accept 之后 evaluate +%.2fs ->" % (time.monotonic() - t0), (v.get("result") or {}).get("value"))
    except Exception as ex:
        print("accept 之后仍超时:", type(ex).__name__)
    try:
        cdp("Target.closeTarget", targetId=tid_holder.get("tid"), _response_timeout=5)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
