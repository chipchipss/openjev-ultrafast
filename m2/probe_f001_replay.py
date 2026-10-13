r"""f001（httpbin 表单题）的地板回放：同一张真实首页，两个构建各跑一遍技能链。

为什么需要它：冻结第 1 轮 18/19，唯一的 FAIL 是 f001，steps 1（历史上它是 PASS/5 步）。
它的 trace 里只有 `first_action_floor` + 模型 BLOCKED，**没有 `first_result`**——
#52 的改动结构上碰不到它。但"结构上碰不到"是推理，不是读数；这一发把读数取回来：
拿 f001 的真实 goal 走一遍产品自己的技能优先级（`SKILLS` 的顺序就是 `model.choose` 的顺序），
把每一格的返回打出来。若 `goto_path`/`explicit_target` 本该开火而没开火，那是**旧账**
（#25 的地板空点击族），不是这一刀带来的。

零模型（不调 :8090），只读页面 + 调技能函数。只在没有批次在跑时使用。
用法：python m2/probe_f001_replay.py [--root <repo>]  （--root 给 HEAD 对照构建）
"""
import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
URL = "https://httpbin.org/"
GOAL = ("Go to /forms/post and fill the customer name field with 'Test User', "
        "then submit the form.")

root = "."
if "--root" in sys.argv:
    root = sys.argv[sys.argv.index("--root") + 1]
sys.path.insert(0, os.path.abspath(root))
os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:2080")
os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:2080")
os.environ.setdefault("BU_CDP_URL", "http://127.0.0.1:9222")

from jev_ultrafast.browser import Browser, StalePage       # noqa: E402
from jev_ultrafast import skills as S                       # noqa: E402

print("build root = %s" % os.path.abspath(root))
print("skills.py  = %s" % S.__file__)

b = Browser(URL)
try:
    p = None
    for k in range(8):
        try:
            p = b.observe(screenshot=False)
        except StalePage:
            import time
            time.sleep(0.5)
            continue
        if S.indexed_actions(p.get("actions") or []):
            break
    acts = S.indexed_actions((p or {}).get("actions") or [])
    print("url=%r title=%r n_indexed=%d" % (
        str((p or {}).get("url") or "")[:40], str((p or {}).get("title") or "")[:30], len(acts)))
    print("---- 页面上的 /forms/ 相关链接 ----")
    for i, a in acts:
        h = str(a.get("href") or "")
        if "forms" in h.lower() or "post" in h.lower():
            print("   %-4s %-30s %s" % (i, str(a.get("label") or "")[:30], h[:40]))
    print("---- 技能链（SKILLS 顺序 = model.choose 顺序）----")
    first_fire = None
    for fn in S.SKILLS:
        try:
            d = fn(p, GOAL, [])
        except Exception as e:
            print("   %-26s ERROR %r" % (fn.__name__, e))
            continue
        if d:
            print("   %-26s -> %s target=%s choice=%s" % (
                fn.__name__, d.get("operation"), d.get("target"), d.get("choice")))
            if first_fire is None:
                first_fire = (fn.__name__, d)
        else:
            print("   %-26s    -" % (fn.__name__,))
    print("---- floor 会发什么（模型 BLOCKED 之后才轮到它）----")
    f = S.first_action_floor(p, GOAL, [])
    print(json.dumps(f, ensure_ascii=False)[:200] if f else "None")
finally:
    b.close()
