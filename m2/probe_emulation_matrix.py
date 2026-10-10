r"""#60 的第七轮：真实 `Browser(url)` 在干净 Chrome 上仍然楔，而裸探针同样顺序却不楔——差的只有那两次 `Emulation`。

读数对照（同一 URL、同一台机器、同一个 daemon）：
  `m2/probe_guard_effect.txt`/E2：createTarget → attach → `Page.enable` →
    `addScriptToEvaluateOnNewDocument(MODAL_GUARD_JS)` → navigate → 睡 8 秒 →
    对话框 0 个、`document.readyState` = complete（0.01s）。
  真实 `Browser(url)`：createTarget → attach → **setDeviceMetricsOverride** →
    **setFocusEmulationEnabled(true)** → addScript(同一个常量) → navigate →
    每 0.02 秒轮 readyState → 第 6 次楔 124 秒。

本轮把这两个变量单独加回去，2×2：{装不装防御} × {要不要那两次 Emulation}，
并且**照真实路径那样高频轮**（0.2 秒一次，15 秒上限），不再"睡 8 秒只问一次"。
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
from jev_ultrafast.browser import MODAL_GUARD_JS               # noqa: E402

URL = "https://the-internet.herokuapp.com/download"


def run(label, guard, emulation, budget=15.0):
    tid = cdp("Target.createTarget", url="about:blank", background=True)["targetId"]
    sid = cdp("Target.attachToTarget", targetId=tid, flatten=True)["sessionId"]
    if emulation:
        cdp("Emulation.setDeviceMetricsOverride", session_id=sid, width=1120, height=780,
            deviceScaleFactor=1, mobile=False, _response_timeout=8)
        cdp("Emulation.setFocusEmulationEnabled", session_id=sid, enabled=True,
            _response_timeout=8)
    cdp("Page.enable", session_id=sid, _response_timeout=8)
    if guard:
        cdp("Page.addScriptToEvaluateOnNewDocument", session_id=sid, source=MODAL_GUARD_JS,
            _response_timeout=8)
    try:
        cdp("Page.navigate", session_id=sid, url=URL, _response_timeout=8)
    except Exception as e:
        print("   navigate 超时", type(e).__name__)
    t0 = time.monotonic()
    polls = 0
    wedged_at = None
    complete_at = None
    while time.monotonic() - t0 < budget:
        tp = time.monotonic()
        try:
            v = cdp("Runtime.evaluate", session_id=sid, expression="document.readyState",
                    returnByValue=True, _response_timeout=4)
            polls += 1
            if (v.get("result") or {}).get("value") == "complete" and complete_at is None:
                complete_at = round(time.monotonic() - t0, 2)
        except Exception:
            wedged_at = round(time.monotonic() - t0, 2)
            break
        time.sleep(0.2)
    dl = [e for e in drain_events()
          if e.get("method") == "Page.javascriptDialogOpening" and e.get("session_id") == sid]
    for e in dl:
        cdp("Page.handleJavaScriptDialog", session_id=sid, accept=True, _response_timeout=5)
    after = None
    if dl:
        tp = time.monotonic()
        try:
            cdp("Runtime.evaluate", session_id=sid, expression="1", returnByValue=True,
                _response_timeout=5)
            after = round(time.monotonic() - tp, 2)
        except Exception:
            after = "仍不答"
    print("  %-34s 轮=%-3d complete@%-8s 楔@%-8s 对话框=%-2d accept后恢复=%s" % (
        label, polls, complete_at, wedged_at, len(dl), after))
    try:
        cdp("Target.closeTarget", targetId=tid, _response_timeout=4)
    except Exception:
        pass


def main():
    for emu in (False, True):
        for gd in (False, True):
            run("Emulation=%s 防御=%s" % ("开" if emu else "关", "开" if gd else "关"), gd, emu)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
