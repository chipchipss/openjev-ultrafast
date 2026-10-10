"""#60 回归：页面自己弹的模态框不许把会话楔死（the-internet /download 的实测形状）。

现场（m2/probe_dialog_routes.py + m2/out_dialog_routes.txt，2026-10-11 早晨，零模型）：
`https://the-internet.herokuapp.com/download` 的**初始导航**就让 renderer 主线程停在
`Page.javascriptDialogOpening {type:'alert', message:'1'}` 上——那页把任何人上传的文件名
原样拼进 HTML，列表里躺着 `<img src=x onerror=alert(1)>`。此后该 session 的每一次
`Runtime.evaluate` 都**永不返回**（120 秒轮询 24 次全超时），同时新开 about:blank 0.02s 正常，
同站根路径与 example.com 也正常。b22/b23 的 r142 崩、b18–b24 里 step 1 的 124.5/124.8 秒
`executed_ms`（= `Browser.call` 的 4 次 × 30 秒）都是这一条。

修法选"预防"而不是"事后应答"，两条都在现场量过：
  A `Page.enable` + `drain_events()` + `Page.handleJavaScriptDialog`：能解，但要撞一次
    30 秒超时才发现，且页面连弹 4 个时必须循环排干（实测第 1 次 accept 后仍超时、
    第 2 次才恢复）。
  B `Page.addScriptToEvaluateOnNewDocument` 在页面自己的脚本之前把
    `window.alert/confirm/prompt` 换成空函数：对话框根本不开，navigate 后 evaluate
    +0.02s 就答（实测 2/2）。且它随每个新 document 重装，点击之后的导航也覆盖。

没覆盖的已知形状（记账，不虚构修法）：`beforeunload` 这类**浏览器生成**的对话框不走
window.*  API，B 拦不住——50 题里没有这种页面，等真见到再打这一刀。

运行：python tests/test_browser_modal_guard.py
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


def fresh_browser(env: dict):
    saved = {k: os.environ.get(k) for k in ("BU_CDP_URL", "BU_CDP_WS", "JEV_CDP_PORT")}
    for k in ("BU_CDP_URL", "BU_CDP_WS", "JEV_CDP_PORT"):
        os.environ.pop(k, None)
    os.environ.update(env)
    import jev_ultrafast.browser as b
    importlib.reload(b)
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    return b


URL = "https://the-internet.herokuapp.com/download"


class Fake:
    """假 CDP 层：记录调用顺序，并对"对话框页"模拟主线程楔死。

    wedge=True 时，任何**未装防御补丁**的 Runtime.evaluate 都不回答（模拟 modal 钉住
    主线程）；装了 `addScriptToEvaluateOnNewDocument`（在 navigate 之前）就不再有对话框。
    """

    def __init__(self, wedge=True):
        self.calls = []                  # [(method, params)]
        self.wedge = wedge
        self.guarded = False             # 补丁是否在 navigate 之前注册
        self.script_before_nav = False
        from browser_harness.helpers import _IPCResponseTimeout
        self.Timeout = _IPCResponseTimeout

    def cdp(self, method, session_id=None, _response_timeout=None, **params):
        self.calls.append((method, params))
        if method == "Target.createTarget":
            return {"targetId": "T1"}
        if method == "Target.attachToTarget":
            return {"sessionId": "S1"}
        if method == "Page.addScriptToEvaluateOnNewDocument":
            src = params.get("source") or ""
            if "alert" in src and "confirm" in src and "prompt" in src:
                self.guarded = True
                if not any(m == "Page.navigate" for m, _ in self.calls):
                    self.script_before_nav = True
            return {}
        if method == "Page.enable":
            return {}
        if self.wedge and self.guarded:
            return {"result": {"value": "complete"}}
        if self.wedge and method in ("Runtime.evaluate",) and any(
                m == "Page.navigate" for m, _ in self.calls):
            raise self.Timeout("Runtime.evaluate timed out waiting for the daemon")
        if method == "Runtime.evaluate":
            return {"result": {"value": "complete"}}
        return {}

    def names(self):
        return [m for m, _ in self.calls]

    def first(self, m):
        return self.names().index(m) if m in self.names() else None


def build(b, fake):
    """用假 CDP 走一遍 Browser(url)，返回 (实例, 异常或 None)。"""
    b.cdp = fake.cdp
    b._ensure_daemon = lambda: None
    b._assert_owned_browser = lambda: None
    try:
        return b.Browser(URL), None
    except Exception as e:                                # noqa: BLE001
        return None, e


@case("初始导航前就装好模态框防御（对话框页不许楔死会话）")
def _guard_installed_before_first_navigate():
    b = fresh_browser({})
    fake = Fake(wedge=True)
    inst, err = build(b, fake)
    assert err is None, f"对话框页把会话楔死了：{type(err).__name__}: {err}"
    assert fake.script_before_nav, \
        "防御补丁没在 Page.navigate 之前注册，第一跳的 alert 照样能把主线程钉住"


@case("拦对话框要覆盖 alert/confirm/prompt 三个入口")
def _all_three_modal_apis():
    b = fresh_browser({})
    fake = Fake(wedge=True)
    inst, err = build(b, fake)
    assert err is None, f"{type(err).__name__}: {err}"
    i = fake.first("Page.addScriptToEvaluateOnNewDocument")
    assert i is not None, "根本没注册 new-document 脚本"
    src = fake.calls[i][1].get("source") or ""
    for api in ("alert", "confirm", "prompt"):
        assert api in src, f"补丁没管 {api}()"


@case("没对话框的页面行为不变（补丁只是装上，不多做动作）")
def _clean_page_unchanged():
    b = fresh_browser({})
    fake = Fake(wedge=False)
    inst, err = build(b, fake)
    assert err is None, f"{type(err).__name__}: {err}"
    assert fake.first("Page.navigate") is not None, "没导航就不叫起会话"
    assert fake.first("Page.addScriptToEvaluateOnNewDocument") is not None


@case("注册失败不能让会话起不来（等价改前行为，不能新增死法）")
def _registration_failure_is_not_fatal():
    b = fresh_browser({})
    fake = Fake(wedge=False)
    real = fake.cdp

    def cdp(method, session_id=None, _response_timeout=None, **params):
        if method == "Page.addScriptToEvaluateOnNewDocument":
            raise RuntimeError("daemon 不支持")
        return real(method, session_id, _response_timeout, **params)
    try:
        build(b, type("F", (), {"cdp": cdp, "calls": [], "wedge": False,
                                "guarded": False, "script_before_nav": False,
                                "Timeout": fake.Timeout,
                                "names": lambda self: [],
                                "first": lambda self, m: None})())
    except RuntimeError as e:
        raise AssertionError(f"补丁注册失败把会话起不来了：{e}")


@case("`Page.enable` 必须在第一次导航之前（实测：不开 Page 域，防御等于没装）")
def _page_enabled_before_first_navigate():
    b = fresh_browser({})
    fake = Fake(wedge=True)
    inst, err = build(b, fake)
    assert err is None, f"{type(err).__name__}: {err}"
    i_en = fake.first("Page.enable")
    i_nav = fake.first("Page.navigate")
    assert i_en is not None, "会话里根本没发过 Page.enable"
    assert i_en < i_nav, \
        f"Page.enable 排在第 {i_en} 个、Page.navigate 在第 {i_nav} 个：导航之后才开机就没用了"


@case("负例：改前的 browser.py 在 navigate 之前不装任何防御（第一条失败因此归因到点上）")
def _pre_fix_code_fails():
    """改动落进 HEAD 之后对照对象消失，按 Skip 处理（同 test_cdp_ownership 的规矩）。"""
    import subprocess
    out = subprocess.run(["git", "show", "HEAD:jev_ultrafast/browser.py"],
                         cwd=str(REPO), capture_output=True)
    if out.returncode != 0:
        raise AssertionError("git show 失败，无从对照")
    old = out.stdout.decode("utf-8", "replace")
    i = old.index("def __init__(self, url")
    body = old[i:old.index("def call(", i)]
    nav = body.find('"Page.navigate"')
    if nav < 0 or "MODAL_GUARD_JS" in body:
        raise AssertionError("改前不该已含防御（提交已落则本条应改为 Skip）")
    assert "addScriptToEvaluateOnNewDocument" not in body[:nav], \
        "改前的 __init__ 在第一跳之前就注册了脚本，那第一条失败就不是楔死造成的"


def main() -> int:
    failed = 0
    for name, fn in CASES:
        try:
            fn()
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {name}\n      {e}")
        except Exception as e:                              # noqa: BLE001
            failed += 1
            print(f"ERROR {name}\n      {type(e).__name__}: {e}")
        else:
            print(f"ok    {name}")
    print(f"\n{len(CASES) - failed}/{len(CASES)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
