"""E2 类病灶的确定性探针（零模型）：inline <a> 的**并集矩形中心**落在没绘制的空隙里。

doc.rust-lang.org/stable/ 实况（2026-10-08，b7 的 r116）：'Rust API documentation'
这条链接 `getClientRects()` 有 2 段（文字绕着浮动块断行），而
`getBoundingClientRect()` 是它们的**并集** [177,294,665x52] —— 中心 (510,320) 根本
不属于这个链接，`document.elementFromPoint` 返回别的元素 → act 侧判"被覆盖"→
`StalePage` 连抛 5 次 → `steps=0` 收口。同一元素的**每个行片段的中心**都能命中。

所以点击点该取自行片段，不是并集盒。这个脚本把"修前必红、修后必绿"钉成一条命令：

    python scripts/probe_click_point.py

它不碰模型、不碰技能层，只验执行层能不能把一条真实存在的链接点下去。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:2080")
os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:2080")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jev_ultrafast.browser import Browser, StalePage  # noqa: E402

URL = "https://doc.rust-lang.org/stable/"
# 两条已知是"多行 inline <a>"的链接（并集中心打不中）
TARGETS = ("Rust API documentation", "Rust By Example")

PROBE_JS = """(node => { const e=window.__jevFast?.nodes.get(node);
  if (!e) return null;
  const r=e.getBoundingClientRect(), cx=r.x+r.width/2, cy=r.y+r.height/2;
  const t=document.elementFromPoint(cx,cy);
  const frags=[...e.getClientRects()].map(q=>{const x=q.x+q.width/2,y=q.y+q.height/2;
      const h=document.elementFromPoint(x,y); return [Math.round(x),Math.round(y),
      !!h && (h===e||e.contains(h))];});
  return {union:[Math.round(r.x),Math.round(r.y),Math.round(r.width),Math.round(r.height)],
          centreHits: !!t && (t===e||e.contains(t)), fragments:frags};
})"""


def check_one(label: str) -> tuple[str, str]:
    """返回 (id, 'ok' | 'stale:<msg>' | 'skip')；每次都新开一个浏览器会话，
    因为成功的那一发会真的导航走，页面形状就没了。"""
    b = Browser(URL)
    try:
        page = b.observe(screenshot=False)
        target = next((a for a in page["actions"]
                       if a["kind"] == "click" and label in (a.get("label") or "")), None)
        if target is None:
            return ("?", "skip")
        geo = b.evaluate(f"{PROBE_JS}({target['node']})")
        print(f"\n{target['id']} {target['label']!r}")
        print(f"   并集盒 {geo['union']}，中心命中={geo['centreHits']}")
        print(f"   行片段 {geo['fragments']}")
        if geo["centreHits"]:
            return (target["id"], "skip")           # 这条已经不是病灶形状
        try:
            b.act(target, page)
        except StalePage as e:
            return (target["id"], f"stale:{e}")
        return (target["id"], "ok")
    finally:
        b.close()


def main() -> int:
    failed, hits, skipped = [], [], []
    for label in TARGETS:
        tid, outcome = check_one(label)
        if outcome == "ok":
            hits.append(tid)
        elif outcome.startswith("stale:"):
            failed.append((tid, outcome[6:]))
            print(f"   act -> StalePage：{outcome[6:]}")
        else:
            skipped.append(tid)
    print("\n" + "=" * 58)
    if not hits and not failed:
        print(f"没验到病灶形状（靶子页面变了）：skip={skipped}")
        return 2
    if failed:
        print(f"RED  点击点取并集中心 -> {len(failed)} 条被拒：{failed}")
        return 1
    print(f"GREEN {len(hits)} 条多行链接全部点得下去：{hits}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
