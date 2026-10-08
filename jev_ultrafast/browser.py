"""Observed actions through Browser Harness; one CDP session, no per-step subprocess."""

import hashlib
import json
import re
import subprocess
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

#: 浏览器归属（P0 · 2026-10-08）。browser_harness 的 get_ws_url() 找浏览器的顺序是：
#: BU_CDP_WS → BU_CDP_URL → **扫 Chrome 默认画像的 DevToolsActivePort** → 最后才探 9222。
#: 我们自己的 Chrome 是用 `--user-data-dir`（不在扫描名单里）起的，所以只要用户本人的
#: Chrome 允许过远程调试（Local State 里 remote_debugging.user-enabled=true），守护进程
#: 就会连到**他的**浏览器：任务在他的真实窗口里跑（撞"绝不动用户自己的 Chrome"这条硬线），
#: 而弹窗不在时又变成 403 permission-blocked（实测：冻结 round 1 两个 pilot 全废在这）。
#: 所以连接之前把端点钉死，并且验一次"这个端口上的进程确实是我们起的画像"。
CDP_PORT = int(os.environ.get("JEV_CDP_PORT", "9222"))
OWNED_PROFILE_MARKERS = ("chrome-cdp-test", "chrome-jev-profile")


def _pin_cdp_endpoint() -> None:
    """没显式指定就把守护进程锁到我们的 CDP 端口；显式指定的尊重它，但仍要过归属校验。"""
    if not (os.environ.get("BU_CDP_WS") or os.environ.get("BU_CDP_URL")):
        os.environ["BU_CDP_URL"] = f"http://127.0.0.1:{CDP_PORT}"


def _endpoint_port() -> int:
    for var in ("BU_CDP_WS", "BU_CDP_URL"):
        m = re.search(r"://[^/:]+:(\d+)", os.environ.get(var) or "")
        if m:
            return int(m.group(1))
    return CDP_PORT


def _run_text(cmd: list[str], timeout: int) -> str:
    """Console tools here answer in the OEM codepage; decode leniently instead of
    letting a UnicodeDecodeError look like "no browser on that port"."""
    r = subprocess.run(cmd, capture_output=True, timeout=timeout)
    return r.stdout.decode("utf-8", "replace") + "\n" + r.stderr.decode("utf-8", "replace")


def _listener_cmdline(port: int):
    """命令行里带 --user-data-dir 的那个进程；查不到返回 None（fail closed 由调用方决定）。"""
    try:
        out = _run_text(["netstat", "-ano", "-p", "TCP"], 5)
    except Exception:
        return None
    pids = {l.split()[-1] for l in out.splitlines()
            if f":{port}" in l and "LISTENING" in l and l.split()[-1].isdigit()}
    if not pids:
        return None
    probes = ";".join(
        f"(Get-CimInstance Win32_Process -Filter 'ProcessId={p}').CommandLine" for p in pids)
    try:
        out = _run_text(["powershell", "-NoProfile", "-Command", probes], 10)
    except Exception:
        return None
    lines = [x for x in out.splitlines() if x.strip() and "Get-CimInstance" not in x]
    return "\n".join(lines) or None


def _assert_owned_browser() -> None:
    port = _endpoint_port()
    cmd = _listener_cmdline(port)
    if cmd is None:
        raise RuntimeError(
            f"no-browser: nothing listens on :{port} -- the owned CDP Chrome was started "
            f"by the runner (--user-data-dir=chrome-cdp-test); refusing to let the harness "
            f"fall back to whatever browser it can find")
    if not any(marker in cmd for marker in OWNED_PROFILE_MARKERS):
        raise RuntimeError(
            f"foreign-browser: :{port} is served by a Chrome we did not start "
            f"({cmd[:160]}) -- refusing to drive it")


_pin_cdp_endpoint()


def _ensure_daemon() -> None:
    """有界 ensure_daemon：显式 wait 把无限等待变成有界失败；失败则复位重试一次。"""
    _assert_owned_browser()
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

#: 在途请求计数器。同一份脚本既装进当前 document，也注册成 new-document 脚本
#: （见 Browser._settle_patch）——它必须在页面自己的脚本之前跑起来，才可能看见
#: 页面一加载就发出的那个异步请求。
SETTLE_INIT_JS = (
    "(() => { if (window.__jevSettle) return 1;"
    " const st = { inflight: 0, lastEnd: 0 };"
    " const dec = () => { st.inflight--; st.lastEnd = performance.now(); };"
    " const of = window.fetch;"
    " if (of) window.fetch = function (...a) {"
    "   st.inflight++; let p;"
    "   try { p = of.apply(this, a); }"
    "   catch (e) { dec(); throw e; };"
    "   p.then(dec, dec); return p; };"
    " const os = XMLHttpRequest.prototype.send;"
    " XMLHttpRequest.prototype.send = function (...a) {"
    "   st.inflight++;"
    "   try { this.addEventListener('loadend', dec); }"
    "   catch (e) { dec(); };"
    "   try { return os.apply(this, a); }"
    "   catch (e) { dec(); throw e; }; };"
    " window.__jevSettle = st; return 1; })()"
)


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
        # readyState=complete 不等于渲染完成：冷启动（空 profile）的 rfc-editor.org
        # 首页在 complete 时头部的 6 个导航+搜索控件还没挂上（实测 n_actions 23，
        # 晚几百毫秒拍是 30；缺的正是 "Find an RFC" 搜索框）。首拍拿残缺页 → 模型
        # BLOCKED 0.77 → floor 链走向 Subscribe 死路，n004 三个冻结轮全死在这。
        # 与动作后 settle 同一判据。初始拍三个专门参数：
        # floor 1200ms —— readyState 与异步 bundle 挂载（实测 1.0-3.2s）之间 DOM
        # 本来就静止，"归静"判据会被这段假静止骗过（1540 轮 2.5s 上限仍读空即此因）；
        # quiet 250ms —— 挂载后常伴随轮询/时钟类小变更，放宽归静窗口；
        # cap 5000ms —— 冷 profile + 0.7MB/s 代理的渲染尾巴。已静止的页面只付 ~1.45s。
        self._settle_patch()
        self._await_settle(cap_ms=5000, floor_ms=1200, quiet_ms=250)

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
            # Fix O（n004 三轮冻结 + 单任务复跑）：act() 之后那次 settle 会在**整页导航**时
            # 撞上"执行上下文被销毁"，而那条路是 `except Exception: pass`（注释写明交给
            # observe 的 StalePage 重试）。可 StalePage 只会重试"读"，不会等"渲染" ——
            # 于是提交搜索后的第一拍观测仍可能没有结果行（实测第 3 拍弃权、第 4 拍才点上）。
            # 这里在**要读的那个 document 上**再等一次：在途计数现在由 new-document 脚本带着，
            # 导航后照样有效，所以等的是"这一页自己的请求跑完了没"。
            cap_ms = self.SETTLE_CAPS_MS.get(action["kind"])
            if cap_ms:
                self._await_settle(cap_ms)
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

    # 动作后 settle detection（n004 靶子）：SPA 的结果在动作后数秒才渲染，复观察太早
    # 读到过渡态（实测"0 results"空页 → agent 放弃）。与 wait 用的"首次变化即返回"
    # 相反，这里要等页面**归静**：DOM 连续 quiet_ms 无变化、且该动作发起的请求结束、
    # 且无进行中的元素 transition，才返回；否则最多等 cap。已静止的页面只付一个
    # quiet_ms 窗口，不吃上限。
    SETTLE_CAPS_MS = {"click": 1500, "select": 800, "fill": 800}
    SETTLE_QUIET_MS = 120

    def _settle_patch(self) -> None:
        """装 fetch/XHR 在途计数（幂等）。

        除了装进当前 document，还要用 `Page.addScriptToEvaluateOnNewDocument` 注册一份：
        提交搜索是**整页导航**，只装在当前 document 的补丁会随旧文档一起消失，新 document
        里 `window.__jevSettle` 是 undefined → `_await_settle` 的 `reqBusy` 恒假 → 只剩
        "DOM 静默 120ms" 一条判据，于是在结果行还没异步渲染出来时就放行观测。
        n004 三轮冻结里 round 1331/1336 就是这么丢的（零模型探针：提交后 t=0 页面 27 个动作、
        命中 0 行；+1.0s 才 32 个动作、1 行）。注册一次即可，之后每个新 document 都自带计数器。
        """
        try:
            self.call("Runtime.evaluate", expression=SETTLE_INIT_JS, returnByValue=True)
        except Exception:
            pass
        if not getattr(self, "_settle_registered", False):
            try:
                self.call("Page.enable")
                self.call("Page.addScriptToEvaluateOnNewDocument", source=SETTLE_INIT_JS)
                self._settle_registered = True
            except Exception:
                # 不支持就该照旧工作：少一份跨导航计数器，等价于改前行为，不能让动作失败。
                pass

    def await_action_settle(self, kind: str) -> None:
        cap_ms = self.SETTLE_CAPS_MS.get(kind)
        if cap_ms:
            self._await_settle(cap_ms)

    def _await_settle(self, cap_ms: int, floor_ms: int = 0, quiet_ms: int | None = None) -> None:
        quiet = self.SETTLE_QUIET_MS if quiet_ms is None else quiet_ms
        try:
            self.call(
                "Runtime.evaluate",
                expression=(
                    "((capMs, quietMs, floorMs) => new Promise(resolve => {"
                    " const t0 = performance.now(); let lastMut = t0, done = false;"
                    " const finish = () => { if (done) return; done = true;"
                    "   try { obs.disconnect(); } catch (e) {} resolve(1); };"
                    " let obs;"
                    " try {"
                    "   obs = new MutationObserver(() => { lastMut = performance.now(); });"
                    "   obs.observe(document.documentElement,"
                    "     { childList: true, subtree: true, attributes: true, characterData: true });"
                    " } catch (e) {}"
                    " const check = () => {"
                    "   const now = performance.now();"
                    "   if (now - t0 >= capMs) return finish();"
                    "   if (now - t0 < floorMs) { setTimeout(check, 40); return; };"
                    "   const s = window.__jevSettle;"
                    "   const reqBusy = !!s && (s.inflight > 0 || now - s.lastEnd < quietMs);"
                    "   const domBusy = now - lastMut < quietMs;"
                    "   let transBusy = false;"
                    "   try {"
                    "     transBusy = document.getAnimations().some(a =>"
                    "       a.playState === 'running' && a instanceof CSSTransition);"
                    "   } catch (e) {}"
                    "   if (!domBusy && !reqBusy && !transBusy) return finish();"
                    "   setTimeout(check, 40);"
                    " };"
                    " setTimeout(check, 20);"
                    f" }}))({int(cap_ms)},{int(quiet)},{int(floor_ms)})"
                ),
                awaitPromise=True,
                returnByValue=True,
            )
        except Exception:
            # 导航会销毁执行上下文 —— 后续 observe 的 StalePage 重试负责接住过渡态。
            pass

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
        if action["kind"] in self.SETTLE_CAPS_MS:
            self._settle_patch()
        result = browser_operation({"operation": "act", "session": self.session, "action": action, "text": text})
        self.after_input = action if action["kind"] != "wait" else None
        if action["kind"] in self.SETTLE_CAPS_MS:
            self.await_action_settle(action["kind"])
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
              // 点击点取自**行片段**（getClientRects），不是并集盒（getBoundingClientRect）。
              // inline <a> 的文字绕浮动块断行时，并集盒把两段之间的空白也算进来：
              // doc.rust-lang.org/stable/ 实况（b7 的 r116），'Rust API documentation'
              // 行片段 [[805,307],[245,333]] 都能命中，并集盒 [177,294,665x52] 的中心
              // (510,320) 却打在别的元素上 → 这里判"被覆盖" → StalePage 连抛 5 次 →
              // agent 以 steps=0 收口，看起来像竞态，其实是每条多行链接都点不动。
              // 块级元素只有一段，与该段等于其 border box —— 常见路径行为不变。
              let pt=null;
              for (const q of e.getClientRects()) {
                const x=q.x+q.width/2, y=q.y+q.height/2;
                if (!q.width || !q.height || x<0 || y<0 || x>=innerWidth || y>=innerHeight) continue;
                const top=document.elementFromPoint(x,y);
                if (top && e.contains(top)) { pt={x,y}; break; }
              }
              if (!pt) return null;
              if (action.kind==='select') {
                if (e.tagName!=='SELECT' || ![...e.options].some(o=>o.value===action.value &&
                    !o.disabled && !o.closest('optgroup[disabled]'))) return null;
                e.value=action.value;
                e.dispatchEvent(new Event('input',{bubbles:true}));
                e.dispatchEvent(new Event('change',{bubbles:true}));
              }
              return pt;
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
