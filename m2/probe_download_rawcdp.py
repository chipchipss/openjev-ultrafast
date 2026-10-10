r"""#58 的仪器检查：wedge 到底在 daemon 里还是页面主线程上？——绕开 daemon 直连该 target 的裸 CDP。

上一轮（probe_download_wedge2）量到：/download 页 navigate 0.95s 返回、标题已渲染，但该 session
的 `Runtime.evaluate` 永久超时（120s 轮询 24 次全失败），同站根路径和外站同时都 0.02s 正常。
剩下的两种解释必须分开，否则 #58 的修法会打在错误的一层：
  A 页面主线程被卡（Chrome 端）→ 裸 WS 也超时候选
  B daemon 为该 session 等一个永不到来的事件 → **裸 WS 能答**
本脚本用 /json/list 里该 target 自己的 webSocketDebuggerUrl 直连，发 1+1，不经过 daemon。

只在没有批次在跑时使用。
"""
import asyncio
import io
import json
import sys
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import websockets                                     # noqa: E402

URL = "https://the-internet.herokuapp.com/download"


def pages():
    with urllib.request.urlopen("http://127.0.0.1:9222/json/list", timeout=10) as r:
        return [t for t in json.load(r) if t.get("type") == "page"]


async def probe(ws_url, label):
    try:
        async with websockets.connect(ws_url, max_size=None, open_timeout=8) as ws:
            await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                                      "params": {"expression": "1+1", "returnByValue": True}}))
            msg = await asyncio.wait_for(ws.recv(), timeout=8)
            got = json.loads(msg)
            print("  %-22s 裸 WS -> %s" % (label, json.dumps(got.get("result", got))[:90]))
            await ws.send(json.dumps({"id": 2, "method": "Page.getNavigationHistory"}))
            async def drain(target_id):
                while True:
                    m = json.loads(await ws.recv())
                    if m.get("id") == target_id:
                        return m
            hist = await asyncio.wait_for(drain(2), timeout=8)
            entries = (hist.get("result") or {}).get("entries") or []
            print("  %-22s 导航历史 %d 条：%s" % (
                label, len(entries),
                ["%s:%s" % (e.get("type"), str(e.get("url"))[:40]) for e in entries[-3:]]))
    except Exception as e:
        print("  %-22s 裸 WS -> %s: %s" % (label, type(e).__name__, str(e)[:60]))


async def amain():
    ps = pages()
    dl = [p for p in ps if p.get("url") == URL]
    other = [p for p in ps if p.get("url") == "https://the-internet.herokuapp.com/"]
    print("pages=%d  /download=%d  根路径=%d" % (len(ps), len(dl), len(other)))
    for i, p in enumerate(dl[:3], 1):
        await probe(p["webSocketDebuggerUrl"], "download #%d" % i)
    for p in (other[:1] or ps[:1]):
        await probe(p["webSocketDebuggerUrl"], "对照 %s" % p.get("url", "")[:20])


if __name__ == "__main__":
    asyncio.run(amain())
