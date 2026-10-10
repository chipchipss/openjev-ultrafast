r"""#60 的第二轮对照（把上一轮的测量缺陷补上）：等页面真的加载完，再看哪条路能挡住对话框。

上一轮（`m2/probe_dialog_routes.py`）的 B 组是 **navigate 后 +0.02 秒**就 evaluate 的——那时
`<img src=x>` 还没加载失败，`onerror` 根本没跑，所以"没楔住"证明不了防御生效。真实
`Browser(url)` 带着新补丁照样在 r142 的到达页上撞 30 秒超时，就是这个道理。

本轮每条都：attach → （按路线装防御/开事件） → navigate → **睡 3 秒**（onerror 一定跑过）
→ 排空事件数对话框 → evaluate 试探。A 组还要循环 accept，因为实测页面**连弹 4 个**。

零模型，只在没有批次在跑时用（驱动自有 headless Chrome `:9222`）。
"""
import io
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\Administrator\openjev-ultrafast")
os.environ.setdefault("BU_CDP_URL", "http://127.0.0.1:9222")

from browser_harness.helpers import cdp, drain_events          # noqa: E402
from jev_ultrafast.browser import MODAL_GUARD_JS               # noqa: E402

URL = "https://the-internet.herokuapp.com/download"
ASSIGN_JS = ("(() => { for (const k of ['alert', 'confirm', 'prompt']) {"
             " try { window[k] = k === 'confirm' ? (() => true) : (() => undefined);"
             " } catch (e) {} } return 1; })()")


def open_session():
    tid = cdp("Target.createTarget", url="about:blank", background=True)["targetId"]
    sid = cdp("Target.attachToTarget", targetId=tid, flatten=True)["sessionId"]
    return tid, sid


def dialogs(sid):
    return [e for e in drain_events()
            if e.get("method") == "Page.javascriptDialogOpening" and e.get("session_id") == sid]


def probe_eval(sid, cap):
    t0 = time.monotonic()
    try:
        v = cdp("Runtime.evaluate", session_id=sid,
                expression="document.readyState + '|a=' + document.querySelectorAll('a').length",
                returnByValue=True, _response_timeout=cap)
        return time.monotonic() - t0, str((v.get("result") or {}).get("value"))
    except Exception as e:
        return time.monotonic() - t0, type(e).__name__


def guarded(label, source):
    tid, sid = open_session()
    cdp("Page.enable", session_id=sid, _response_timeout=8)
    try:
        r = cdp("Page.addScriptToEvaluateOnNewDocument", session_id=sid, source=source,
                _response_timeout=8)
        reg = "ok %s" % json_keys(r)
    except Exception as e:
        reg = "失败 %s" % type(e).__name__
    try:
        cdp("Page.navigate", session_id=sid, url=URL, _response_timeout=8)
    except Exception as e:
        pass
    time.sleep(3.0)
    dl = dialogs(sid)
    dt, res = probe_eval(sid, 6)
    print("  %-28s 注册=%-26s 对话框事件=%d  evaluate %.2fs -> %s" %
          (label, reg, len(dl), dt, res))
    return tid, sid, dl


def json_keys(r):
    ks = list((r or {}).keys())
    return ",".join(ks) if ks else "-"


def reactive():
    tid, sid = open_session()
    cdp("Page.enable", session_id=sid, _response_timeout=8)
    cdp("Page.navigate", session_id=sid, url=URL, _response_timeout=8)
    time.sleep(3.0)
    rounds = []
    for i in range(10):
        dl = dialogs(sid)
        if not dl:
            break
        for e in dl:
            try:
                cdp("Page.handleJavaScriptDialog", session_id=sid, accept=True,
                    _response_timeout=5)
            except Exception as ex:
                rounds.append("accept 失败 %s" % type(ex).__name__)
        rounds.append("第%d轮 accept %d 个" % (i + 1, len(dl)))
    dt, res = probe_eval(sid, 6)
    print("  反应式 A：accept 轮次 %s -> evaluate %.2fs %s" % (rounds or "无", dt, res))
    return tid, sid


def cleanup(ids):
    for tid in ids:
        try:
            cdp("Target.closeTarget", targetId=tid, _response_timeout=5)
        except Exception:
            pass


def main():
    ids = []
    ids.append(guarded("B defineProperty 不可覆写", MODAL_GUARD_JS)[0])
    ids.append(guarded("B 普通赋值 window[k]", ASSIGN_JS)[0])
    ids.append(reactive()[0])
    # 再确认一次：加了防御的会话，页面加载完后能不能正常观测
    cleanup(ids)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
