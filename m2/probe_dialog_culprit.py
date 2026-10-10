r"""#60 的第五轮：装上防御之后仍然楔住，而且**没有对话框事件**——那主线程上堵着的是什么？

`m2/probe_dialog_which.py` 的读数：真实 `Browser(url)` 在 `Page.addScriptToEvaluateOnNewDocument
 (0.01s ok)` 之后导航，`document.readyState` 连答 5 次（0.02/0.03/0.02/0.02/0.00s），第 6 次
楔 124.42 秒；撞超时后排空 12 条事件、**对话框 0 个**，accept 无效。也就是说：
防御确实把 alert 挡住了（对照路线 3/3 有对话框事件、这里 0 个），但这条页面上还有**第二个
主线程阻塞源**。这页在 the-internet 的公共模板里挂了一个厂商统计脚本
`/js/vendor/298279967.js`（mPulse/comScore 一类，132 KB），它常在加载时发**同步 XHR**。

本轮按"每次只动一个开关"分开：
  1 只装防御（复现：应当仍然楔）
  2 防御 + 关掉页面 JS（`Emulation.setScriptExecutionDisabled`，导航前设）→ 若是页面脚本干的，这条一定通
  3 防御 + 屏蔽 mPulse 脚本（`Network.setBlockedURLs`）→ 若是**它**干的，这条通、且快照仍然可用
每条都在导航前设置，然后每 0.5 秒轮 `document.readyState`，轮 30 秒，打印每次往返耗时。

零模型，只在没有批次在跑时用。
"""
import io
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\Administrator\openjev-ultrafast")
os.environ.setdefault("BU_CDP_URL", "http://127.0.0.1:9222")

from browser_harness.helpers import cdp                        # noqa: E402
from jev_ultrafast.browser import MODAL_GUARD_JS               # noqa: E402

URL = "https://the-internet.herokuapp.com/download"
MPULSE = "*/js/vendor/298279967.js"


def poll(sid, seconds=30.0):
    """每 0.5s 问一次 readyState，返回 (成功次数, 第一次超时发生在第几次, 时刻)"""
    t0 = time.monotonic()
    ok, first_bad = 0, None
    while time.monotonic() - t0 < seconds:
        tp = time.monotonic()
        try:
            v = cdp("Runtime.evaluate", session_id=sid,
                    expression="document.readyState", returnByValue=True, _response_timeout=5)
            val = (v.get("result") or {}).get("value")
            ok += 1
            last = val
        except Exception as e:
            if first_bad is None:
                first_bad = (ok, round(time.monotonic() - t0, 1), type(e).__name__)
            print("      第 %d 次 +%4.1fs 超时（前面通了 %d 次）" % (ok + 1, time.monotonic() - t0, ok))
            # 试探：还能恢复吗？
            try:
                cdp("Runtime.evaluate", session_id=sid, expression="1",
                    returnByValue=True, _response_timeout=8)
                print("      下一次试探恢复")
            except Exception:
                print("      8 秒上限仍不答 -> 主线程确实堵着；停止本条")
                return ok, first_bad, None
            continue
        time.sleep(0.5)
    return ok, first_bad, locals().get("last")


def case(label, guard=True, kill_js=False, block_mpulse=False, budget=30):
    tid = cdp("Target.createTarget", url="about:blank", background=True)["targetId"]
    sid = cdp("Target.attachToTarget", targetId=tid, flatten=True)["sessionId"]
    setup = []
    if guard:
        cdp("Page.addScriptToEvaluateOnNewDocument", session_id=sid, source=MODAL_GUARD_JS,
            _response_timeout=8)
        setup.append("guard")
    if kill_js:
        cdp("Emulation.setScriptExecutionDisabled", session_id=sid, value=True,
            _response_timeout=8)
        setup.append("noJS")
    if block_mpulse:
        try:
            cdp("Network.enable", session_id=sid, _response_timeout=8)
            cdp("Network.setBlockedURLs", session_id=sid, urls=[MPULSE], _response_timeout=8)
            setup.append("blockMPulse")
        except Exception as e:
            setup.append("block失败%s" % type(e).__name__)
    try:
        cdp("Page.navigate", session_id=sid, url=URL, _response_timeout=8)
    except Exception as e:
        print("   navigate 就超时：%s" % type(e).__name__)
    ok, bad, last = poll(sid, budget)
    print("  %-22s 装配=%-26s 通了 %2d 次  首次超时=%s  末值=%s" % (
        label, ",".join(setup) or "-", ok, bad, last))
    try:
        cdp("Target.closeTarget", targetId=tid, _response_timeout=5)
    except Exception:
        pass


def main():
    case("1 只装防御", guard=True)
    case("2 防御+关页面JS", guard=True, kill_js=True)
    case("3 防御+屏蔽mPulse", guard=True, block_mpulse=True)
    case("4 什么都不装", guard=False, budget=20)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
