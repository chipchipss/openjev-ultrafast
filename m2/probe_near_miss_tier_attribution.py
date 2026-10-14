r"""#46 的射程测量：`explicit_target` 在**全部语料页**上的每一次非弃权命中，是**哪一档**给的。

为什么先量这一条：r113 的错点已由 `m2/probe_r113_scroll_ladder.py` 量清 ——
滚动一格之后页面上只有 `Style Guide for C Code`（pep-0007），短语是 `Style Guide for Python Code`，
两个都不是精确/前缀/包含/片段关系，能开火的只剩**词重叠档**（4 个实义词命中 3 个 = 0.75 ⇒ 约 0.825）；
再滚一格，Python 那行进来，精确档 2.0 压住 0.825，自动纠正 ⇒ 代价是**一个空拍**，r113 每批都 PASS。

所以"要不要给近似行加一道守卫"不能凭 r113 一行决定：**得先知道有多少别的行正靠这一档活着**。
这份探针就是把 186 份真实页（100 起点 + 86 一跳，`m2/corpus/pages*.jsonl`，零模型抓的）逐页跑一遍
产品的 `explicit_target`，再把产品选中的那一行**按产品的档位顺序**归到某一档上。

一句话说明这不是产品代码：**判据仍是产品算的**（非弃权/选中哪一行都来自 `skills.explicit_target`），
这里只复刻"标签 vs 短语属于哪一档"这一段分类，用来数档位分布。
复刻的档位顺序与 `skills.py` 里那段 if/elif 一字对齐，改了产品档位必须同步改这里。

运行："C:/Users/Administrator/miniconda3/envs/jev/python.exe" m2/probe_near_miss_tier_attribution.py
"""
from __future__ import annotations

import io
import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from jev_ultrafast import skills as S                       # noqa: E402

CORPUS = [REPO / "m2" / "corpus" / "pages.jsonl",
          REPO / "m2" / "corpus" / "pages-hop.jsonl"]


def fold_s(t: str) -> str:
    # 与 skills.explicit_target 里那个**局部**函数逐字对齐（它不是模块级，探针只能复制）。
    return t[:-1] if len(t) > 5 and t.endswith("s") else t


def tier_of(label: str, phrase: str) -> str:
    """按产品那段 if/elif 的**顺序**判断 (label, phrase) 落在哪一档。"""
    lab_n = " ".join(S._tokens(label))
    pn = " ".join(S._tokens(phrase))
    lt, pt = S._tokens(label), S._tokens(phrase)
    if not pn:
        return "no-phrase"
    if lab_n == pn:
        return "1 精确(2.0)"
    if lab_n.startswith(pn + " "):
        return "2 前缀(1.5)"
    if pn in lab_n:
        return "3 包含(1.0)"
    if phrase.startswith("/"):
        return "4 路径短语(0.0，不发)"
    if len(lab_n) >= 4 and pn.startswith(lab_n + " "):
        return "5 从头对齐片段(0.9)"
    if (pt and pt[0] not in S.STOPWORDS and len(lt) <= len(pt)
            and all(fold_s(x) == fold_s(y) for x, y in zip(lt, pt))
            and any(x != y for x, y in zip(lt, pt))):
        return "6 单复数折叠(0.95)"
    pc = S._content(phrase)
    if pc:
        ratio = sum(1 for t in pc if t in S._tokens(label)) / len(pc)
        if ratio >= 0.75:
            return "7 词重叠(<=0.85) ← r113 的那一档"
    return "8 其它(href 档/域名档/0)"


def main() -> int:
    pages = []
    for path in CORPUS:
        if not path.exists():
            print("缺语料：%s（先跑 m2/probe_tier3_corpus.py 重采并**重记基线**）" % path, file=sys.stderr)
            return 3
        for line in io.open(path, encoding="utf-8"):
            if line.strip():
                pages.append(json.loads(line))

    tiers = Counter()
    overlap_rows = []
    fired = 0
    for rec in pages:
        pg, goal = rec["page"], rec["goal"]
        pick = S.explicit_target(pg, goal, [])
        if not isinstance(pick, dict):
            continue
        fired += 1
        idx = str(pick.get("target"))
        act = dict(S.indexed_actions(pg.get("actions") or [])).get(idx) or {}
        label = str(act.get("label") or "")
        # 取该 pick 在短语集合里能拿到的**最高档**（按产品顺序，序号小者优先）
        best = None
        for ph in S.goal_phrases(goal):
            t = tier_of(label, ph)
            if best is None or t < best:
                best = t
        tiers[best or "?"] += 1
        if best and best.startswith("7"):
            overlap_rows.append((rec.get("task_id"), goal[:58], label[:42], str(act.get("href") or "")[:30]))

    print("语料页：%d 份；explicit_target 非弃权：%d 次" % (len(pages), fired))
    for k in sorted(tiers):
        print("  %-34s %d" % (k, tiers[k]))
    print("\n第 7 档（词重叠）到底是哪些行：")
    for r in overlap_rows[:40]:
        print("   %-6s goal=%-58s label=%-42r href=%s" % r)
    if len(overlap_rows) > 40:
        print("   …共 %d 行，只列前 40" % len(overlap_rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
