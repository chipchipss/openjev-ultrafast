r"""#60 的第三轮：上一轮 n=1 的结果互相矛盾，把它拆开量。

`m2/out_dialog_routes2.txt` 的读数：defineProperty 版注册 ok、排空到 0 个对话框事件、
但 evaluate 6.01s 超时；普通赋值版同样 0 个事件、evaluate 2.47s 就答了。
"0 个事件"和"会话楔死"不能同时为真——除非**我的那一次排空赶在 alert 之前**
（`<img src=x>` 的 onerror 是图片加载失败才跑的，时刻取决于代理，不在脚本之前）。

所以本轮每条：navigate → 睡 3s → 排空并 accept → evaluate（6s）→ **超时后再排空一次**
并 accept → 再 evaluate。这样"事件在不在"由第二次排空回答，不再靠运气。三种各跑 3 次。

零模型，只在没有批次在跑时用。
"""
import io
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\Administrator\openjev-ultrafast")
os.environ.setdefault("BU_CDP_URL", "http://127.0.0.1:9222")

from browser_harness.helpers import cdp, drain_events           # noqa: E402
from jev_ultrafast.browser import MODAL_GUARD_JS                # noqa: E402

URL = "https://the-internet.herokuapp.com/download"
ASSIGN_JS = ("(() => { for (const k of ['alert', 'confirm', 'prompt']) {"
             " try { window[k] = k === 'confirm' ? (() => true) : (() => undefined);"
             " } catch (e) {} } return 1; })()")
VARIANTS = [
    ("无防御（对照）", None),
    ("defineProperty 不可覆写", MODAL_GUARD_JS),
    ("普通赋值 window[k]", ASSIGN_JS),
]
REPEATS = 3
EXPR = "document.readyState + '|a=' + document.querySelectorAll('a').length"


def dialogs(sid):
    return [e for e in drain_events()
            if e.get("method") == "Page.javascriptDialogOpening" and e.get("session_id") == sid]


def accept_all(sid, dl):
    for e in dl:
        try:
            cdp("Page.handleJavaScriptDialog", session_id=sid, accept=True, _response_timeout=5)
        except Exception:
            pass


def evaluate(sid, cap=6):
    t0 = time.monotonic()
    try:
        v = cdp("Runtime.evaluate", session_id=sid, expression=EXPR,
                returnByValue=True, _response_timeout=cap)
        return time.monotonic() - t0, str((v.get("result") or {}).get("value"))
    except Exception as e:
        return time.monotonic() - t0, "TIMEOUT"


def run(label, source):
    tid = cdp("Target.createTarget", url="about:blank", background=True)["targetId"]
    sid = cdp("Target.attachToTarget", targetId=tid, flatten=True)["sessionId"]
    cdp("Page.enable", session_id=sid, _response_timeout=8)
    if source:
        cdp("Page.addScriptToEvaluateOnNewDocument", session_id=sid, source=source,
            _response_timeout=8)
    try:
        cdp("Page.navigate", session_id=sid, url=URL, _response_timeout=8)
    except Exception:
        pass
    time.sleep(3.0)
    d1 = dialogs(sid)
    accept_all(sid, d1)
    dt1, r1 = evaluate(sid)
    d2 = []
    dt2 = r2 = None
    if r1 == "TIMEOUT":
        d2 = dialogs(sid)                 # 超时之后再排空：事件到底来过没有
        accept_all(sid, d2)
        dt2, r2 = evaluate(sid)
    try:
        cdp("Target.closeTarget", targetId=tid, _response_timeout=5)
    except Exception:
        pass
    print("  %-24s 首排=%d 首eval %.2fs %-22s 二排=%d 二eval %s" % (
        label, len(d1), dt1, r1[:22], len(d2),
        ("-（没超时，不必二排）" if r2 is None else "%.2fs %s" % (dt2, r2[:22]))))


def main():
    for label, source in VARIANTS:
        for i in range(REPEATS):
            run("%s #%d" % (label, i + 1), source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
