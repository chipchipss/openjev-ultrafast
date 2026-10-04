"""Observed actions through Browser Harness; one CDP session, no per-step subprocess."""

import hashlib
import json
import sys
import time
from pathlib import Path

from browser_harness.admin import ensure_daemon, restart_daemon
from browser_harness.helpers import cdp

import os

# browser_harness 默认在"本地 + 未显式传 wait"时把 Chrome 授权弹窗的等待设为
# **无限**（approval_wait=None）——无人值守时没人点 "Allow"，任务会永久挂起
# （实测：M1 长跑卡在 ensure_daemon 30+ 分钟，只能人工 kill）。
DAEMON_WAIT = float(os.environ.get("JEV_DAEMON_WAIT", "30"))


def _ensure_daemon() -> None:
    """有界 ensure_daemon：显式 wait 把无限等待变成有界失败；失败则复位重试一次。"""
    try:
        ensure_daemon(wait=DAEMON_WAIT)
        return
    except Exception:
        pass
    try:
        restart_daemon()          # 清掉楔死的 daemon（含其 Chrome）
    except Exception:
        pass
    ensure_daemon(wait=DAEMON_WAIT)


# Atomically read visible content and controls, preserving actual DOM node identity.
READ_STATE = Path(__file__).with_name("snapshot.js").read_text(encoding="utf-8")
MARKER = f"(() => {{ const state={READ_STATE}; return state?.marker ?? null; }})()"

#: 新鲜度专用 marker：不含 text / 滚动位置。动态内容（时钟、广告、懒加载）会让完整
#: marker 每帧都变，用它判会把每一次点击都判成 stale → "预测→拒绝→重预测"活锁
#: （n001/f002 实况：同一 CLICK 决策连发 5 次、一次都没执行，最终被循环检测判 blocked）。
MARKER_STABLE = f"(() => {{ const state={READ_STATE}; return state?.marker_stable ?? null; }})()"

class StalePage(ValueError):
    """A decision no longer refers to the observed page."""


class Browser:
    def __init__(self, url):
        _ensure_daemon()
        self.target = cdp("Target.createTarget", url="about:blank", background=True)["targetId"]
        self.session = cdp("Target.attachToTarget", targetId=self.target, flatten=True)["sessionId"]
        self.call("Emulation.setDeviceMetricsOverride", width=1120, height=780, deviceScaleFactor=1, mobile=False)
        # Keep rAF/menus rendering in an owned background tab, without activating the user's Chrome tab.
        self.call("Emulation.setFocusEmulationEnabled", enabled=True)
        self.call("Page.navigate", url=url)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.evaluate("document.readyState") == "complete":
                break
            time.sleep(0.02)

    def call(self, method, _response_timeout=30.0, **params):
        # browser_harness 的 cdp() 默认 _response_timeout=5.0s
        # （helpers.DEFAULT_IPC_RESPONSE_TIMEOUT_SECONDS，且是定义时求值的默认参数，
        #  改模块属性无效）。重页面（wikipedia.org 等）首次 Page.navigate 稳定超过 5s，
        #  于是被误判成 daemon 已死——4 次退避重试 + _ensure_daemon 反而让 daemon 更糟。
        # 实测：s004 / l002 / x002 三个 wikipedia 任务在四轮独立测试里反复
        #   agent_init_failed: _IPCResponseTimeout: Page.navigate timed out after 5s
        # 超时是上限而非 sleep：快请求不受影响，重页面则能等到 daemon 真正返回。
        from browser_harness.helpers import _IPCResponseTimeout
        last = None
        for attempt in range(4):
            try:
                return cdp(method, session_id=self.session,
                           _response_timeout=_response_timeout, **params)
            except _IPCResponseTimeout as e:
                last = e
                if attempt < 3:
                    time.sleep(0.5 * (attempt + 1))
                    # daemon 可能已掉，重新 ensure
                    try:
                        _ensure_daemon()
                    except Exception:
                        pass
        raise last

    def evaluate(self, expression):
        response = self.call("Runtime.evaluate", expression=expression, returnByValue=True)
        if response.get("exceptionDetails"):
            raise StalePage("Document changed during evaluation")
        return response.get("result", {}).get("value")

    def observe(self, screenshot=True):
        if getattr(self, "after_input", None):
            action, self.after_input = self.after_input, None
            # This is read-only and happens after execution was logged, even if navigation interrupts it.
            try:
                self.call(
                    "Runtime.evaluate",
                    expression="""(action => new Promise(resolve => {
                      const field=window.__jevFast?.nodes.get(action.node);
                      const autocomplete=action.kind==='fill' && field?.getAttribute('role')==='combobox';
                      let frames=0, stopped=false;
                      const finish=()=>{stopped=true;resolve()};
                      setTimeout(finish,autocomplete ? 200 : 50);
                      const ready=()=>{
                        if (stopped) return;
                        const ids=(field?.getAttribute('aria-controls')||field?.getAttribute('aria-owns')||'')
                          .split(/\\s+/).filter(Boolean);
                        const roots=ids.length ? ids.map(id=>document.getElementById(id)).filter(Boolean) : [document];
                        const options=roots.flatMap(root=>[...root.querySelectorAll('[role="option"]')]);
                        if (++frames>=2 && (!autocomplete || options.some(e=>{
                          const r=e.getBoundingClientRect();
                          return r.width && r.height && r.bottom>0 && r.top<innerHeight &&
                            e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true});
                        }))) finish();
                        else requestAnimationFrame(ready);
                      };
                      requestAnimationFrame(ready);
                    }))(""" + json.dumps(action) + ")",
                    awaitPromise=True,
                    returnByValue=True,
                )
            except RuntimeError:
                pass
        for attempt in range(10):
            try:
                return browser_operation(
                    {"operation": "observe", "session": self.session, "screenshot": screenshot}
                )
            except StalePage:
                if attempt == 9:
                    raise
                time.sleep(0.02)
        raise StalePage("Page did not settle")

    def fresh(self, page, action=None):
        # wait 不引用任何节点，页面正在变化正是要等的理由 —— 对它做 marker 校验
        # 会自相矛盾：marker 一变就判 stale，于是"等一拍"被无限重试
        # （实测：Flights 第 10 步同一 wait 决策重试 ~40 次 × 0.34s，直到
        #  MAX_STEPS*2 决策上限才收口，单轮白烧 13s+）。
        if action is not None and action["kind"] == "wait":
            return True
        if action is not None and action["kind"] in {"click", "select"}:
            node = action["node"]
            if type(node) is not int:
                return False
            current = self.evaluate(
                "(() => { const c=window.__jevFast; "
                f"return c ? [c.pageKey(),c.guard(c.nodes.get({node}))] : null; }})()"
            )
            expected = [page["page_key"], page["guards"].get(str(node))]
            if current is None:
                # 页面导航中/缓存已清（__jevFast 不存在）——与"目标消失"同义
                return False
            if current != expected:
                cur_pk = current[0] if isinstance(current, list) and len(current) > 0 else None
                cur_guard = current[1] if isinstance(current, list) and len(current) > 1 else None
                print("FRESH_MISMATCH")
                print("  node:", node)
                print("  page_key_equal:", cur_pk == expected[0])
                print("  guard_equal:", cur_guard == expected[1])
                print("  current_page_key:", cur_pk)
                print("  expected_page_key:", expected[0])
                print("  current_guard:", cur_guard)
        return self.evaluate(MARKER_STABLE) == page.get("marker_stable")

    def await_dom_settle(self, cap_s: float = 0.25, floor_ms: int = 60) -> None:
        """等"页面又渲染出了东西"：地板 floor_ms 后**首次** DOM 变化即返回，最多 cap_s。

        上限 0.25s 是实测选出来的：建议列表要 0.72s 才出现，但"首次变化即返回"已经
        主导 —— 把它加到 0.7s 后连跑三轮反而更慢（9.17/11.72/13.06 vs 8.75/9.94/11.82），
        因为页面静止（没什么可等）时白付满上限。上限只需保证"不早于真实渲染"，不需要
        一次覆盖完整延迟：wait 之后 agent 必然重新 observe，技能再判一次，没到就再发一个
        wait（_can_wait 兜底）。
        取不到 DOM（导航中/缓存被清）时退回盲等。
        """
        try:
            self.call(
                "Runtime.evaluate",
                expression=(
                    "new Promise(resolve => {"
                    " let done=false;"
                    " const finish=()=>{ if(done) return; done=true;"
                    "   try{obs.disconnect()}catch(e){} clearTimeout(cap); resolve(1); };"
                    " const obs=new MutationObserver(finish);"
                    f" setTimeout(()=>{{ try{{ obs.observe(document.documentElement,"
                    "   {childList:true,subtree:true,attributes:true,characterData:true});"
                    f" }}catch(e){{}} }},{int(floor_ms)});"
                    f" const cap=setTimeout(finish,{int(cap_s * 1000)});"
                    "})"
                ),
                awaitPromise=True,
                returnByValue=True,
            )
        except Exception:
            time.sleep(cap_s)

    def reload(self):
        """整页重载并等 readyState 落地。

        用于 SPA 路由偶发不渲染的兜底：实测失败的 final_url 重新整页加载必出结果
        （12 个 "flight" 命中、3 行 "Select flight"），而运行中 25 拍都看不到 ——
        走同一条出问题的 SPA 路由再提交一次救不回来（v110 实测）。
        """
        self.call("Page.reload", ignoreCache=False)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                if self.evaluate("document.readyState") == "complete":
                    break
            except StalePage:
                pass
            time.sleep(0.05)
        return {"status": "reloaded", "ok": True}

    def act(self, action, page, text=None):
        if action["kind"] != "reload" and not self.fresh(page, action):
            raise StalePage("Page changed since this decision. Observe again.")
        if action["kind"] == "wait":
            # 事件式等待：候选渲染出来就立刻返回，页面静止则等满 0.25s（原为盲等 0.5s）。
            self.await_dom_settle()
        if action["kind"] == "reload":
            # 重载会换掉整棵 DOM，agent 随后必然复观察 —— 这里不需要 after_input 结算。
            self.after_input = None
            return self.reload()
        result = browser_operation({"operation": "act", "session": self.session, "action": action, "text": text})
        self.after_input = action if action["kind"] != "wait" else None
        return result

    def close(self):
        if self.target:
            cdp("Target.closeTarget", targetId=self.target)
            self.target = None


def fingerprint(state):
    content = {k: state[k] for k in ("url", "text", "actions", "scroll")}
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


def browser_operation(request):
    operation = request["operation"]
    session = request["session"]

    def call(method, **params):
        return cdp(method, session_id=session, **params)

    def evaluate(expression):
        result = call("Runtime.evaluate", expression=expression, returnByValue=True)
        if result.get("exceptionDetails"):
            if operation == "act" and request["action"]["kind"] == "select":
                raise RuntimeError("Dropdown execution was interrupted; inspect before retrying.")
            raise StalePage("Document changed during evaluation")
        return result.get("result", {}).get("value")

    if operation == "act":
        action = request["action"]
        kind = action["kind"]
        if kind == "scroll":
            call("Input.dispatchMouseEvent", type="mouseWheel", x=550, y=650, deltaX=0, deltaY=action["delta"])
        elif kind != "wait":
            if type(action["node"]) is not int:
                raise ValueError("Invalid observed node")
            # Code-owned node IDs refer to actual observed elements, never model-generated selectors.
            target = evaluate("""(action => {
              const e=window.__jevFast?.nodes.get(action.node);
              if (!e?.isConnected || e.matches(':disabled') || e.closest('[aria-disabled="true"],[inert]') ||
                  !e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true})) return null;
              if (action.kind==='fill' && (e.readOnly || e.getAttribute('aria-readonly')==='true')) return null;
              const r=e.getBoundingClientRect(), x=r.x+r.width/2, y=r.y+r.height/2;
              if (!r.width || !r.height || x<0 || y<0 || x>=innerWidth || y>=innerHeight) return null;
              if (!e.contains(document.elementFromPoint(x,y))) return null;
              if (action.kind==='select') {
                if (e.tagName!=='SELECT' || ![...e.options].some(o=>o.value===action.value &&
                    !o.disabled && !o.closest('optgroup[disabled]'))) return null;
                e.value=action.value;
                e.dispatchEvent(new Event('input',{bubbles:true}));
                e.dispatchEvent(new Event('change',{bubbles:true}));
              }
              return {x,y};
            })(""" + json.dumps(action) + ")")
            if target is None:
                if kind == "select":
                    raise RuntimeError("Dropdown execution was not confirmed; inspect before retrying.")
                raise StalePage("Target changed or is covered. Observe again.")
            if kind != "select":
                x, y = target["x"], target["y"]
                for event in ("mousePressed", "mouseReleased"):
                    call("Input.dispatchMouseEvent", type=event, x=x, y=y, button="left", clickCount=1)
                if kind == "fill":
                    call(
                        "Input.dispatchKeyEvent",
                        type="keyDown",
                        key="a",
                        code="KeyA",
                        modifiers=4 if sys.platform == "darwin" else 2,
                        commands=["selectAll"],
                    )
                    call(
                        "Input.dispatchKeyEvent",
                        type="keyUp",
                        key="a",
                        code="KeyA",
                        modifiers=4 if sys.platform == "darwin" else 2,
                    )
                    call("Input.insertText", text=request["text"])
        return {"executed": action["id"]}

    info = evaluate(READ_STATE)
    if info is None:
        raise StalePage("Document is navigating")
    info["fingerprint"] = fingerprint(info)
    if request.get("screenshot", True):
        info["screenshot"] = call("Page.captureScreenshot", format="jpeg", quality=72)["data"]
    return info
