r"""#65 的前置测量（零模型）：动作发起的那次导航，什么时候才"可读"。

b36 的 r187/r195 与 b35 的 r154/156/157/158 是同一族：`act` 之后的 settle
（`browser.py::_await_settle`）在**整页导航**时把自己的执行上下文炸掉，`except: pass`
静默放行，紧接的 observe 读到一份还没有正文的新 document。修法要付的代价是"多等"，
所以先量两个时刻，再决定上限，不许拍一个数字：

  t_ready = 导航发起后 `document.readyState=='complete'` 第一次成立
  t_text  = 第一次读到**够用**的正文（阈值见 MIN_TEXT，按见证页实测 text 长度的一小部分取）

做法只用产品自己的 `Browser`（navigate + evaluate + observe），不调模型、不填表单：
终点页就是那几行的见证 URL，也就是 agent 本该在下一拍读到的东西。

只在没有批次在跑时用。
"""
import io
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\Administrator\openjev-ultrafast")
os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:2080")
os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:2080")
os.environ.setdefault("BU_CDP_URL", "http://127.0.0.1:9222")

from jev_ultrafast.browser import Browser, StalePage   # noqa: E402

# 每行 = (题号, 终点页, 那一行断言真正要的文本片段)
TARGETS = [
    ("r153", "https://docs.python.org/3/search.html?q=list", "list"),
    ("r154", "https://docs.python.org/3/search.html?q=enumerate", "enumerate"),
    ("r156", "https://docs.python.org/3/search.html?q=typing", "typing"),
    ("r157", "https://docs.python.org/3/search.html?q=asyncio", "asyncio"),
    ("r158", "https://docs.python.org/3/search.html?q=memoryview", "memoryview"),
    ("r187", "https://arxiv.org/list/cs.CL/new", "Computation and Language"),
    ("r195", "https://stackoverflow.com/questions/tagged/python-3.x", "python"),
]
PROBE_CAP_MS = 6000          # 单次探测上限：超过就记"这一页 6 秒还没可读"，不当成功
POLL_MS = 50


def probe(url, needle):
    b = Browser(url)
    t0 = time.monotonic()
    t_ready = t_text = None
    maxlen = 0
    try:
        while (time.monotonic() - t0) * 1000 < PROBE_CAP_MS:
            try:
                rs = b.evaluate("document.readyState")
            except StalePage:
                rs = None
            if rs == "complete" and t_ready is None:
                t_ready = (time.monotonic() - t0) * 1000
            try:
                txt = b.evaluate(
                    "(() => { const s = document.body && document.body.innerText;"
                    " return s ? String(s).slice(0, 200000) : ''; })()"
                ) or ""
            except StalePage:
                txt = ""
            maxlen = max(maxlen, len(txt))
            if t_text is None and needle.lower() in txt.lower() and len(txt) >= 300:
                t_text = (time.monotonic() - t0) * 1000
            if t_ready is not None and t_text is not None:
                break
            time.sleep(POLL_MS / 1000)
    finally:
        b.close()
    return t_ready, t_text, maxlen


def main():
    print(f"{'row':6} {'t_ready(ms)':>12} {'t_text(ms)':>11} {'max_text_len':>13}  url")
    rows = []
    for tid, url, needle in TARGETS:
        r, t, m = probe(url, needle)
        rows.append((tid, r, t, m))
        print(f"{tid:6} {('-' if r is None else f'{r:.0f}'):>12} "
              f"{('-' if t is None else f'{t:.0f}'):>11} {m:>13}  {url[:58]}")
    ready = [x[1] for x in rows if x[1] is not None]
    text = [x[2] for x in rows if x[2] is not None]
    print(f"\n读到目标文本的行 {len(text)}/{len(rows)}；"
          f"t_ready max={max(ready):.0f}ms  t_text max={max(text):.0f}ms  "
          f"t_text 中位={sorted(text)[len(text)//2]:.0f}ms" if text else "没有一行读到")
    return 0


if __name__ == "__main__":
    sys.exit(main())


# ---------------------------------------------------------------------------
# 第二轮：走**产品自己的 act 路径**复现失败行的形状（fill 搜索框 → click 提交 → 计时）。
# 上面那组直连见证 URL 的读数不能当依据：形态不对（不是表单导航，也没有 searchindex.js
# 那一发 XHR），而且浏览器是热的。这一轮量的是"动作发起的那次导航到底什么时候可读"。
# ---------------------------------------------------------------------------

def drive_docs(term):
    """docs.python.org/3/ 上填搜索框、点提交，然后量 readyState 与结果文本的出现时刻。"""
    b = Browser("https://docs.python.org/3/")
    page = b.observe(screenshot=False)
    box = next((a for a in page["actions"] if a.get("kind") == "text"), None)
    btn = next((a for a in page["actions"] if a.get("kind") == "click"
               and "search" in str(a.get("label", "")).lower()), None)
    if not box or not btn:
        b.close()
        return None
    b.act({"kind": "fill", "id": box["id"]}, page, text=term)
    page2 = b.observe(screenshot=False)
    t0 = time.monotonic()
    t_ready = t_text = None
    maxlen = 0
    try:
        b.act({"kind": "click", "id": btn["id"]}, page2)     # 产品路径：动作后的 settle 也在里面
        while (time.monotonic() - t0) * 1000 < PROBE_CAP_MS:
            try:
                rs = b.evaluate("document.readyState")
            except StalePage:
                rs = None
            if rs == "complete" and t_ready is None:
                t_ready = (time.monotonic() - t0) * 1000
            try:
                txt = b.evaluate(
                    "(() => { const s = document.body && document.body.innerText;"
                    " return s ? String(s).slice(0, 200000) : ''; })()"
                ) or ""
            except StalePage:
                txt = ""
            maxlen = max(maxlen, len(txt))
            if t_text is None and term.lower() in txt.lower() and len(txt) >= 300:
                t_text = (time.monotonic() - t0) * 1000
            if t_ready is not None and t_text is not None:
                break
            time.sleep(POLL_MS / 1000)
    finally:
        url = b.evaluate("location.href") if True else ""
        b.close()
    return t_ready, t_text, maxlen, url
