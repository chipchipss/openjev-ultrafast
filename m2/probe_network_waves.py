r"""#65 的可行性判据（零模型）：Network 层的"在途=0"到底能不能把两波请求分开？

为什么要再量一次，而不是直接开写：#65 的第一刀（页内 fetch/XHR 归静）被**它自己的靶子否掉了**
（`m2/real-log.md`「#65 的第一刀被它自己的靶子否掉了」）。现场是 docs.python.org 的搜索结果页：

    +781ms  url 到位、textlen=654、不含要找的词
    +0.9s   searchindex.js（`<script>`，页内计数器看不见）结束
    +2.18s  正文波才开始发 fetch
    +4.0s   textlen=1454、含词

⇒ 在 +0.9s 到 +2.18s 之间页面**本来就归静**：没有 DOM 变更、没有在途 fetch/XHR、没有 running
transition。任何"等一段平静"的判据等的都是这段**合法的**静默。所以这一刀要成立，必须先回答一个
数值问题，而不是先写代码：

    **Q = 多长的"在途请求=0"窗口，才能在整族里都不提前放行？**

如果不存在这样的 Q（真空比正文到达还长），CDP Network 层也只是把早读从 0.8 秒推到 1.0 秒，
这一刀就该按读数判死，剩下的只有"落点页第一次读到 near-empty 时不许定案"那半件。

两个仪器坑都在这支探针上真踩过，写法里留着注释：
1. **`sessionId` 是 CDP 消息的顶层字段，不是 params**。放错位置的后果不是报错而是静默：
   命令在 browser 级执行 ⇒ `Network.enable` 回 "'Network.enable' wasn't found"、
   `Page.navigate` 没导航，探针一脸正经地打印"6 秒没等到、0 条事件"。
   ⇒ 任何"外部系统没有 X"的结论，要先证明这台仪器能读出 X（本探针的自检 = 请求数 > 0 且正文非空）。
2. 先建 future 再 `ws.send`，否则响应可能先于 future 到达而被丢掉。

做法：自己开一条 browser 级 WS（daemon 不转我们 session 的事件，见 #60 的探针），
createTarget → attachToTarget(flatten) → Network/Page/Runtime.enable → Page.navigate，
之后每 50ms 同时取 (在途请求数, 正文长度, 是否含目标词)。viewport 与产品一致（1120x780）。

零模型、不调决策线；只在没有批次在跑、且 :9222 确认是我们自有画像时用
（`cdp_ownership_guard_9222.ps1` 那条判据）。
"""
from __future__ import annotations

import asyncio
import io
import json
import sys
import time
import urllib.request
from collections import Counter

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import websockets                                             # noqa: E402

CDP_HTTP = "http://127.0.0.1:9222"
CAP_MS = 9000
POLL_MS = 50
MIN_TEXT = 300                 # 与产品见证口径一致：短于这个不算"读到正文"
QS = (200, 300, 500, 800, 1200, 1500)

# (题号, 终点页, 那一行断言真正要的文本片段) —— 与 m2/probe_navigation_timing.py 同一批
TARGETS = [
    ("r153", "https://docs.python.org/3/search.html?q=list", "list"),
    ("r154", "https://docs.python.org/3/search.html?q=enumerate", "enumerate"),
    ("r156", "https://docs.python.org/3/search.html?q=typing", "typing"),
    ("r157", "https://docs.python.org/3/search.html?q=asyncio", "asyncio"),
    ("r187", "https://arxiv.org/list/cs.CL/new", "Computation and Language"),
    ("r195", "https://stackoverflow.com/questions/tagged/python-3.x", "python"),
]

TEXT_JS = ("(() => { const s = document.body && document.body.innerText;"
           " return s ? String(s).slice(0, 200000) : ''; })()")


class Client:
    def __init__(self, ws):
        self.ws = ws
        self.n = 0
        self.pending: dict[int, asyncio.Future] = {}
        self.sid = None
        self.inflight: dict[str, float] = {}
        self.t0 = time.monotonic()
        self.tl = []                       # [(t_ms, method, requestId, type)]

    def now_ms(self):
        return (time.monotonic() - self.t0) * 1000.0

    async def pump(self):
        async for raw in self.ws:
            d = json.loads(raw)
            if "id" in d:
                f = self.pending.pop(d["id"], None)
                if f and not f.done():
                    f.set_result(d)
                continue
            m = d.get("method")
            if not m:
                continue
            if d.get("sessionId") != self.sid:
                continue                     # flatten 之后事件带 sessionId；只听我们自己那条
            p = d.get("params") or {}
            rid = p.get("requestId")
            ty = p.get("type") if m == "Network.requestWillBeSent" else None
            if m == "Network.requestWillBeSent":
                self.inflight[rid] = self.now_ms()
            elif m in ("Network.loadingFinished", "Network.loadingFailed"):
                self.inflight.pop(rid, None)
            self.tl.append((self.now_ms(), m, rid, ty))

    async def send(self, method, bare=False, **params):
        self.n += 1
        mid = self.n
        msg = {"id": mid, "method": method, "params": params}
        if self.sid and not bare:
            msg["sessionId"] = self.sid    # 顶层！见文件头仪器坑 1
        fut = asyncio.get_event_loop().create_future()
        self.pending[mid] = fut            # 先登记再发，见仪器坑 2
        await self.ws.send(json.dumps(msg))
        r = await asyncio.wait_for(fut, timeout=10)
        if "error" in r:
            raise RuntimeError(f"{method}: {r['error'].get('message')}")
        return r.get("result") or {}


async def measure(tid, url, needle):
    http = json.load(urllib.request.urlopen(CDP_HTTP + "/json/version", timeout=5))
    async with websockets.connect(http["webSocketDebuggerUrl"], max_size=None) as ws:
        c = Client(ws)
        pump = asyncio.create_task(c.pump())
        try:
            target = (await c.send("Target.createTarget", url="about:blank",
                                   background=True, bare=True))["targetId"]
            c.sid = (await c.send("Target.attachToTarget", targetId=target,
                                  flatten=True, bare=True))["sessionId"]
            for m in ("Runtime.enable", "Network.enable", "Page.enable"):
                await c.send(m)
            await c.send("Emulation.setDeviceMetricsOverride", width=1120, height=780,
                         deviceScaleFactor=1, mobile=False)
            await c.send("Emulation.setFocusEmulationEnabled", enabled=True)

            t_nav = c.now_ms()
            await c.send("Page.navigate", url=url)

            samples, t_text = [], None
            tail_ms = 2500         # 正文到了之后再盯一段：放行时刻的代价才是这支刀真正要付的钱
            while True:
                dt = c.now_ms() - t_nav
                if dt >= CAP_MS or (t_text is not None and dt >= t_text + tail_ms):
                    break
                try:
                    r = await c.send("Runtime.evaluate", expression=TEXT_JS, returnByValue=True)
                    txt = ((r.get("result") or {}).get("value")) or ""
                except Exception:
                    txt = ""
                t = c.now_ms() - t_nav
                has = needle.lower() in txt.lower()
                samples.append((t, len(c.inflight), len(txt), has))
                if t_text is None and has and len(txt) >= MIN_TEXT:
                    t_text = t
                await asyncio.sleep(POLL_MS / 1000)

            fin = [e[0] - t_nav for e in c.tl
                   if e[1] in ("Network.loadingFinished", "Network.loadingFailed")]
            t_last_finish = round(max(fin)) if fin else None
            marks = {}
            for name in ("Page.domContentEventFired", "Page.loadEventFired"):
                hits = [e[0] - t_nav for e in c.tl if e[1] == name]
                marks[name] = round(hits[0]) if hits else None
            types = Counter(e[3] for e in c.tl if e[1] == "Network.requestWillBeSent")
            n_req = sum(types.values())
            quiet = longest_quiet(c.tl, t_nav, c.now_ms() - t_nav)
            await c.send("Target.closeTarget", targetId=target, bare=True)
        finally:
            pump.cancel()

    # 仪器自检：读不到正事件就说明这台仪器不能回答这个问题，不许据此下结论
    ok = n_req > 0 and any(s[3] for s in samples)
    return dict(target=tid, t_text=t_text, samples=samples, marks=marks, types=dict(types),
                n_req=n_req, quiet=quiet, t_last_finish=t_last_finish, instrument_ok=ok)


def longest_quiet(tl, t_nav, end_ms):
    """导航之后"在途=0"的最长连续区间（起点相对导航，长度 ms，结束时是被新请求打断还是仍然静默）。"""
    inflight = 0
    zero_from = None
    best = (None, 0.0, None)
    for t, m, rid, ty in tl:
        t = t - t_nav
        if t < 0:
            continue
        if m == "Network.requestWillBeSent":
            if inflight == 0 and zero_from is not None:
                if t - zero_from > best[1]:
                    best = (zero_from, t - zero_from, "closed-by-request")
                zero_from = None
            inflight += 1
        elif m in ("Network.loadingFinished", "Network.loadingFailed"):
            if inflight > 0:
                inflight -= 1
            if inflight == 0:
                zero_from = t
    if zero_from is not None and end_ms - zero_from > best[1]:
        best = (zero_from, end_ms - zero_from, "still-quiet")
    return best


def simulate(samples, t_text):
    """对每个 Q，模拟"在途=0 连续满 Q ms 就放行"，看放行时刻相对 t_text 是早还是晚。"""
    out = []
    for q in QS:
        quiet_start = None
        release = None
        for t, n, tl, has in samples:
            if n == 0:
                if quiet_start is None:
                    quiet_start = t
                if t - quiet_start >= q:
                    release = t
                    break
            else:
                quiet_start = None
        if release is None:
            out.append(f"Q={q}:从不放行")
        elif t_text is None:
            out.append(f"Q={q}:放行@{release:.0f}(没等到正文)")
        else:
            out.append(f"Q={q}:@{release:.0f}{'早读' if release < t_text else 'OK'}")
    return "  ".join(out)


def main():
    print(f"{'row':5} {'n_req':>5} {'t_text':>7} {'t_lastfin':>9} "
          f"{'最长归静':>10}  按 Q 模拟：放行时刻(相对 t_text)")
    summary = []
    for tid, url, needle in TARGETS:
        r = asyncio.run(measure(tid, url, needle))
        q = r["quiet"]
        qs = f"{round(q[1])}ms"
        flag = "" if r["instrument_ok"] else "  **仪器没读到正事件，这条不作数**"
        print(f"{tid:5} {r['n_req']:>5} "
              f"{(str(round(r['t_text'])) if r['t_text'] is not None else '-'):>7} "
              f"{str(r['t_last_finish']):>9} {qs:>10}  "
              f"{simulate(r['samples'], r['t_text'])}{flag}")
        summary.append(r | {"tid": tid})
    good = [s for s in summary if s["instrument_ok"]]
    print("\n自检：", f"{len(good)}/{len(summary)} 条拿到正事件（在途请求>0 且读到目标词）")
    if not good:
        print("⇒ 这台仪器不能回答这个问题；结论必须写『无法判定』，不许写成『Network 层没用』。")
        return
    waits = [s["quiet"][1] for s in good if s["t_text"] is not None]
    if waits:
        print(f"⇒ 在等到正文的行里，导航后最长的一段『在途=0』= {max(waits):.0f} ms"
              f"（逐行 {[round(w) for w in waits]}）")
        costs = [s["t_last_finish"] - s["t_text"] for s in good
                 if s["t_text"] is not None and s["t_last_finish"] is not None]
        print("   Q 必须 > 这个值才可能不提前放行；代价看 t_last_finish - t_text：",
              [round(c) for c in costs], "ms")
    else:
        print("⇒ 没有一行在 9 秒内等到正文——这条读数本身就不成立，先查站点。")


if __name__ == "__main__":
    main()
