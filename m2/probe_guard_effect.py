r"""#60 的第六轮：两版防御到底**生效了没有**——先验 JS 本身，再验它在那个页面上有没有真的拦住 alert。

到目前为止的读数互相矛盾，原因是我把"没排到对话框事件"当成了"没有对话框"：
`browser.py` 里 `Page.enable` 是在 `_settle_patch()` 里发的，而那一步在 readyState 轮询**之后**。
所以 `probe_dialog_which` / `probe_dialog_culprit` 里"0 个对话框事件"是**仪器没开机**，不是证据。
另一头，`probe_dialog_routes3` 的两次"装上防御后 0.03s 就答 complete"也可能只是**测早了**——
alert 是 `<img src=x>` 加载失败才跑的，代理慢的时候它在我 3 秒那次采样之后才来。

本轮两条，各自只回答一个问题：
  E1 JS 本身：`Object.defineProperty(window,'alert',…)` 在 Chrome 154 里到底能不能盖住原生
     alert？（先查 alert 是 window 自有属性还是原型上的，再定义，再调用看返回值/描述符）
  E2 现场：`Page.enable` **在导航之前**发（这次开机），装防御，导航后等 8 秒，排空——
     如果仍然出现 `Page.javascriptDialogOpening`，说明防御没拦住，就把它 accept 掉并读
     `String(window.alert)`，看页面里 alert 现在是谁。

零模型，只在没有批次在跑时用。
"""
import io
import json
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\Administrator\openjev-ultrafast")
os.environ.setdefault("BU_CDP_URL", "http://127.0.0.1:9222")

from browser_harness.helpers import cdp, drain_events           # noqa: E402
from jev_ultrafast.browser import MODAL_GUARD_JS                # noqa: E402

URL = "https://the-internet.herokuapp.com/download"


def ev(sid, expr, cap=6):
    try:
        v = cdp("Runtime.evaluate", session_id=sid, expression=expr,
                returnByValue=True, _response_timeout=cap)
        return (v.get("result") or {}).get("value")
    except Exception as e:
        return "TIMEOUT/%s" % type(e).__name__


def sess(url="about:blank"):
    tid = cdp("Target.createTarget", url=url, background=True)["targetId"]
    sid = cdp("Target.attachToTarget", targetId=tid, flatten=True)["sessionId"]
    return tid, sid


def e1():
    print("E1 defineProperty 能不能盖住原生 alert？")
    tid, sid = sess()
    print("   alert 在 window 自有属性上吗 =",
          ev(sid, "Object.prototype.hasOwnProperty.call(window,'alert')"))
    print("   原型上呢 =",
          ev(sid, "!!Object.getOwnPropertyDescriptor(Object.getPrototypeOf(window),'alert')"))
    print("   装补丁 =", ev(sid, MODAL_GUARD_JS + " + 'ok'"))
    print("   装完 typeof =", ev(sid, "typeof window.alert"),
          "  调用返回值 =", repr(ev(sid, "String(window.alert('x'))")),
          "  可覆写吗 =", ev(sid, "(function(){try{window.alert=function(){return 7};return '写成功了:'+String(window.alert())}catch(e){return '严格模式外也没写成:'+e.name}})()"))
    print("   现在 window.alert 长什么样 =", str(ev(sid, "String(window.alert)"))[:70])
    cdp("Target.closeTarget", targetId=tid)


def e2(label, source):
    tid, sid = sess()
    cdp("Page.enable", session_id=sid, _response_timeout=8)          # 这次先开机
    if source:
        cdp("Page.addScriptToEvaluateOnNewDocument", session_id=sid, source=source,
            _response_timeout=8)
    cdp("Page.navigate", session_id=sid, url=URL, _response_timeout=8)
    time.sleep(8.0)
    dl = [e for e in drain_events()
          if e.get("method") == "Page.javascriptDialogOpening" and e.get("session_id") == sid]
    for e in dl:
        cdp("Page.handleJavaScriptDialog", session_id=sid, accept=True, _response_timeout=5)
    dt0 = time.monotonic()
    r = ev(sid, "document.readyState", cap=6)
    who = ev(sid, "String(window.alert).slice(0,50)", cap=6)
    print("  %-26s 导航后 8 秒：对话框事件=%d  readyState=%s（+%.2fs）  window.alert=%r" % (
        label, len(dl), r, time.monotonic() - dt0, who))
    for e in dl[:2]:
        pp = e.get("params") or {}
        print("       type=%s message=%r hasBrowserHandler=%s" %
              (pp.get("type"), str(pp.get("message"))[:12], pp.get("hasBrowserHandler")))
    try:
        cdp("Target.closeTarget", targetId=tid, _response_timeout=5)
    except Exception:
        pass


def main():
    e1()
    e2("不装（对照）", None)
    e2("装 MODAL_GUARD_JS", MODAL_GUARD_JS)
    e2("装普通赋值版", "(() => { window.alert = () => undefined;"
                       " window.confirm = () => true; window.prompt = () => ''; })()")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
