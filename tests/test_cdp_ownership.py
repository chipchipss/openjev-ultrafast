"""P0 回归：守护进程只许连**我们起的** Chrome。

发现的形状（2026-10-08，冻结 round 1 两个 pilot 全废）：`browser_harness.daemon.get_ws_url()`
的顺序是 `BU_CDP_WS` → `BU_CDP_URL` → **扫 Chrome 默认画像的 DevToolsActivePort** → 最后才探
9222。我们的 Chrome 用 `--user-data-dir` 起（不在扫描名单里），所以只要用户本人的 Chrome
允许过远程调试（实测 `Local State` 里 `remote_debugging.user-enabled=true`，默认画像目录下
13:51:22 出现 `DevToolsActivePort`，端口 55806 上的进程 PID 13124 命令行是裸
`chrome.exe` = 用户从桌面起的浏览器），守护进程就连到**他的**浏览器上跑任务。
日志逐字：`bu-default.log` = `connecting to ws://127.0.0.1:55806` + `handshake-wait`。

两件事同时坏：硬线"绝不动用户自己的 Chrome"被越过，而且弹窗不在时 `ensure_daemon`
变成 403 `permission-blocked` —— 测量与边界都不可信。

运行：python tests/test_cdp_ownership.py
"""
from __future__ import annotations

import os
import re
import subprocess
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


class Skip(Exception):
    """无从对照（历史被改写）——跳过，不算失败。"""


def head_text(rel: str, ref: str = "HEAD") -> str:
    out = subprocess.run(["git", "show", f"{ref}:{rel}"], cwd=str(REPO), capture_output=True)
    if out.returncode != 0:
        raise AssertionError(f"git show {ref}:{rel} failed: "
                             f"{out.stderr.decode('utf-8', 'replace').strip()[:120]}")
    return out.stdout.decode("utf-8", "replace")


def fresh_browser(env: dict):
    """把 browser.py 在一个可控环境里重新 import 一遍（模块级会钉端点）。

    返回 (module, import 之后的 env 快照, _endpoint_port 的读数)：端口必须在还原环境
    **之前**读，否则测的是还原后的状态。
    """
    saved = {k: os.environ.get(k) for k in ("BU_CDP_URL", "BU_CDP_WS", "JEV_CDP_PORT")}
    for k in ("BU_CDP_URL", "BU_CDP_WS", "JEV_CDP_PORT"):
        os.environ.pop(k, None)
    os.environ.update(env)
    import importlib
    import jev_ultrafast.browser as b
    importlib.reload(b)
    snapshot = dict(os.environ)
    port = b._endpoint_port()
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    return b, snapshot, port


CDP_OURS = ("\"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe\" --headless=new "
            "--remote-debugging-port=9222 --user-data-dir=C:\\chrome-cdp-test")
CDP_HEADED = ("\"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe\" "
              "--remote-debugging-port=9222 --user-data-dir=C:\\Users\\me\\chrome-jev-profile")
CDP_FOREIGN = ("\"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe\" "
               "--user-data-dir=C:\\Users\\me\\AppData\\Local\\Google\\Chrome\\User Data")


@case("没显式端点时，import 就把守护进程锁到 :9222（改前根本不设 BU_CDP_URL）")
def _import_pins_endpoint():
    b, env, port = fresh_browser({})
    assert env.get("BU_CDP_URL") == "http://127.0.0.1:9222", env.get("BU_CDP_URL")
    assert (b.CDP_PORT, port) == (9222, 9222), (b.CDP_PORT, port)


@case("显式 BU_CDP_WS / BU_CDP_URL 不被覆盖，端口从它里面解析")
def _explicit_endpoint_survives():
    b, env, port = fresh_browser({"BU_CDP_WS": "ws://127.0.0.1:9333/devtools/browser/abc"})
    assert env.get("BU_CDP_WS") == "ws://127.0.0.1:9333/devtools/browser/abc"
    assert env.get("BU_CDP_URL") is None, "explicit WS must not be second-guessed by a URL"
    assert port == 9333, port
    b2, env2, port2 = fresh_browser({"BU_CDP_URL": "http://127.0.0.1:9333"})
    assert env2["BU_CDP_URL"] == "http://127.0.0.1:9333"
    assert port2 == 9333, port2


@case("我们起的两个画像（headless cdp-test / headed jev-profile）都算自有")
def _owned_markers_accepted():
    b, _, _ = fresh_browser({})
    for cmd in (CDP_OURS, CDP_HEADED):
        b._listener_cmdline = lambda port, _c=cmd: _c
        b._assert_owned_browser()          # 不抛就是过


@case("端口上是别人的 Chrome 就抛 foreign-browser，绝不连")
def _foreign_browser_raises():
    b, _, _ = fresh_browser({})
    b._listener_cmdline = lambda port: CDP_FOREIGN
    try:
        b._assert_owned_browser()
    except RuntimeError as e:
        assert str(e).startswith("foreign-browser"), e
        return
    raise AssertionError("a foreign Chrome was accepted")


@case("端口上没人监听就抛 no-browser（fail closed，不去找别的浏览器）")
def _no_listener_raises():
    b, _, _ = fresh_browser({})
    b._listener_cmdline = lambda port: None
    try:
        b._assert_owned_browser()
    except RuntimeError as e:
        assert str(e).startswith("no-browser"), e
        return
    raise AssertionError("missing browser was accepted")


@case("归属判据读的是监听进程的命令行，不是「端口通不通」")
def _ownership_reads_command_line():
    src = (REPO / "jev_ultrafast" / "browser.py").read_text(encoding="utf-8")
    i = src.index("def _assert_owned_browser")
    body = src[i:i + 900]
    assert "OWNED_PROFILE_MARKERS" in body, "ownership does not gate on the owned profiles"
    assert "_listener_cmdline" in body, "ownership does not read the listener's command line"


@case("_ensure_daemon 先验归属再连（连接路径上唯一入口）")
def _guard_is_on_the_connect_path():
    src = (REPO / "jev_ultrafast" / "browser.py").read_text(encoding="utf-8")
    i = src.index("def _ensure_daemon")
    body = src[i:src.index("ensure_daemon(wait=", i)]
    assert "_assert_owned_browser()" in body, \
        "ownership is not checked before the daemon is reached"


@case("四个入口脚本都把 BU_CDP_URL 交给守护进程")
def _runners_pin_the_browser():
    for rel in ("run_baseline_19.ps1", "run_demo.ps1", "scripts/run_one.ps1", "m1/run_suite.ps1"):
        text = (REPO / rel).read_text(encoding="utf-8")
        line = [l for l in text.splitlines()
                if "BU_CDP_URL" in l and "http://127.0.0.1:9222" in l]
        assert line, f"{rel} does not pin BU_CDP_URL to the owned Chrome"


@case("负例：HEAD 的 browser.py 与 runner 会被上面抓住")
def _pre_fix_code_fails():
    try:
        old = head_text("jev_ultrafast/browser.py")
        old_base = head_text("run_baseline_19.ps1")
    except AssertionError as e:
        raise Skip(str(e))
    caught = []
    if "_assert_owned_browser" not in old:
        caught.append("no ownership guard")
    if "BU_CDP_URL" not in old:
        caught.append("no pinned endpoint")
    if "BU_CDP_URL" not in old_base:
        caught.append("runner does not pin")
    assert len(caught) == 3, f"pre-fix code slipped through: {caught}"


def main() -> int:
    failed = 0
    for name, fn in CASES:
        try:
            fn()
        except Skip as e:
            print(f"skip  {name}\n      {e}")
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
