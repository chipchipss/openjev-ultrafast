r"""#70 Tier 3 的**行为不变性**判据：在固定语料上重放确定性技能层，逐字节比摘要。

为什么不是"再跑一批看分数"：同 build 的 100 行批本来就抖 6 行（`m2/real-log.md` 的 10-13 夜间档那节），
一次静默的行为漂移完全可能落在噪声里。重构要的是**逐字节**的对照，所以判据必须离线、确定性、可重跑。

三条硬规矩：
1. **只吃语料，不联网、不调模型** —— 输入是 `m2/corpus/pages.jsonl`（`m2/probe_tier3_corpus.py` 落的，
   那个目录不入库：里面是第三方站点正文）。语料不变 ⇒ 摘要可复现。
2. **入库件里不许有第三方文字** —— `reports/tier3-golden-*.json` 只记
   `operation / target 序号 / skill 名 / 置信度 / 布尔`，元素 label 与 href 一律不进；
   带 label 的完整输出留在不入库的 `m2/corpus/golden-full.json`，出问题时人工看。
3. **摘要动了就是行为变更** —— 当场回滚那一步，不许解释成"应该等价"。

形状对齐（不是猜的）：`agent.py:740` 调的是 `choose(state["page"], …)`，
所以 `model.py` 里那个形参名叫 `state` 的东西**就是页字典** ⇒ 语料用 `observe()` 的原样页字典是对的。

运行：
    python m2/golden_tier3.py                        # 出报告 + 打印摘要
    python m2/golden_tier3.py --compare <上一份报告>  # 摘要一致才算零行为
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:2080")
os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:2080")

from jev_ultrafast import skills as S                                # noqa: E402

CORPUS = REPO / "m2" / "corpus" / "pages.jsonl"
CORPUS_HOP = REPO / "m2" / "corpus" / "pages-hop.jsonl"
FULL_OUT = REPO / "m2" / "corpus" / "golden-full.json"
FULL_OUT = REPO / "m2" / "corpus" / "golden-full.json"

#: 到站页必须单独喂。起点页快照里 `page.url == start_url`，而 `goal_reached.hit()`
#: 第一条就是 `pn in start → False`（防"起点就到达"自锁），所以**只用语料测它永远是 None**
#: —— 那等于给判据空转。`m2/fixtures/*_arrival.json` 是历次探针留下的**真实到站页**快照，
#: 配上题集里的 goal 与起点域，正好补上这一族形状。
FIXTURE_GLOB = ("m2/fixtures/*_arrival.json", "m2/fixtures/*_results.json")
TASK_FILES = ("m2/tasks_real_100.jsonl", "m2/tasks_real.jsonl", "m1/tasks.jsonl")


def norm_decision(d):
    """决策/弃权 → 可比对的安全字段（没有 label、没有 href、没有正文）。"""
    if d is None:
        return None
    if not isinstance(d, dict):
        return {"non_dict": str(type(d).__name__)}
    return {
        "operation": d.get("operation"),
        "target": d.get("target"),
        "skill": d.get("skill"),
        "kind": d.get("kind"),
        "confidence": (None if d.get("confidence") is None
                       else round(float(d["confidence"]), 6)),
    }


#: 被测函数：(名字, 调用, 归一化)。goal_reached / link_followed_arrival 返回的是决策或 None，
#: 不是布尔（读代码得出的，不是记忆），所以统一走 norm_decision。
FN_SET = [
    ("route", lambda p, g, h: S.route(p, g, h), norm_decision),
    ("goal_reached", lambda p, g, h: S.goal_reached(p, g, h), norm_decision),
    ("link_followed_arrival",
     lambda p, g, h: S.link_followed_arrival(p, g, h), norm_decision),
    ("explicit_target", lambda p, g, h: S.explicit_target(p, g, h), norm_decision),
    ("first_result", lambda p, g, h: S.first_result(p, g, h), norm_decision),
    ("first_action_floor",
     lambda p, g, h: S.first_action_floor(p, g, h), norm_decision),
]


def histories(rec):
    """同一页构造 4 个 history 变体：空 / 一跳 / 两跳 / "上一页是别处"。

    `goal_reached` 与 `link_followed_arrival` 读的就是 history 里的 url 事实，
    只测 `[]` 会让它们永远弃权 —— 那等于给判据空转。
    """
    start = rec.get("start_url") or ""
    page = rec["page"]
    here = str(page.get("url") or "")
    #: 到站页（pass2 落的）带着**真实的来路** `came_from`，优先用它 ——
    #: "从这一页点到这一页"是 `link_followed_arrival` 唯一会说话的形状。
    came = str(rec.get("came_from") or "")
    first_href = ""
    for a in (page.get("actions") or []):
        href = str(a.get("href") or "")
        if href and not href.startswith(("javascript:", "#")):
            first_href = href
            break
    hop_start = {"url": start, "kind": "click", "page_changed": True,
                 "outcome": {"url_changed": True}}
    hop_here = {"url": here, "kind": "click", "page_changed": True,
                "outcome": {"url_changed": True}}
    prev = came or first_href or "https://elsewhere.invalid/"
    hop_else = {"url": prev, "kind": "click", "page_changed": True,
                "outcome": {"url_changed": True}}
    out = {
        "h0_empty": [],
        "h1_from_start": [hop_start],
        "h2_two_hops": [hop_start, hop_here],
        "h3_elsewhere": [hop_start, hop_else],
    }
    #: 到站页再加一个**忠实形状**：最后一条历史就是"从 came_from 点了 via_label 到到这里"。
    #: 这是 `link_followed_arrival` 唯一会说话的形状（它读 `action` 标签、`outcome.url_changed`
    #: 与 `url_from`），没有它 golden 对那一族永远是 0 例非弃权 —— 摘要一样绿，但抓不到回归。
    if came and rec.get("via_label"):
        out["h4_followed"] = [{"url": here, "url_from": came, "kind": "click",
                               "action": rec["via_label"], "page_changed": True,
                               "outcome": {"url_changed": True}}]
    return out


def jsonable(x):
    try:
        return json.loads(json.dumps(x, ensure_ascii=False))
    except Exception:                                              # noqa: BLE001
        return repr(x)[:300]


def fixture_records():
    """把历次探针留下的真实到站页变成语料：goal 与起点域从题集里取。"""
    tasks = {}
    for rel in TASK_FILES:
        p = REPO / rel
        if not p.exists():
            continue
        for line in io.open(p, encoding="utf-8"):
            if not line.strip():
                continue
            try:
                spec = json.loads(line)
            except Exception:                                      # noqa: BLE001
                continue
            tasks.setdefault(spec.get("task_id"), spec)
    recs = []
    for pat in FIXTURE_GLOB:
        for path in sorted(REPO.glob(pat)):
            page = json.load(io.open(path, encoding="utf-8"))
            tid = path.name.split("_")[0]
            spec = tasks.get(tid) or {}
            goal = spec.get("goal") or ""
            dom = str(spec.get("domain") or "")
            if not goal:
                continue
            if dom.startswith(("http://", "https://")):
                start = dom
            else:
                start = "https://" + dom if dom else str(page.get("url") or "")
            recs.append({"task_id": "fx-" + tid, "goal": goal,
                         "start_url": start, "page": page})
    return recs


def load_pages():
    recs = []
    for path in (CORPUS, CORPUS_HOP):
        if path.exists():
            recs += [json.loads(l) for l in io.open(path, encoding="utf-8") if l.strip()]
    return recs


def run_all():
    if not CORPUS.exists():
        print("没有语料 %s —— 先跑 m2/probe_tier3_corpus.py" % CORPUS)
        return None
    recs = load_pages()
    fx = fixture_records()
    print("语料：起点页/到站页 %d 页 + 夹具到站页 %d 页（hop 文件%s）"
          % (len(recs), len(fx), "在" if CORPUS_HOP.exists() else "缺"))
    safe = []
    full = []
    n_pages = 0
    for rec in recs + fx:
        page = rec["page"]
        goal = rec["goal"]
        n_pages += 1
        for hname, hist in histories(rec).items():
            case = {"task_id": rec["task_id"], "history": hname}
            for fname, call, norm in FN_SET:
                try:
                    raw = call(page, goal, hist)
                    case[fname] = norm(raw)
                    full.append({"task_id": rec["task_id"], "history": hname,
                                 "fn": fname, "raw": jsonable(raw)})
                except Exception as e:                             # noqa: BLE001
                    case[fname] = {"raised": type(e).__name__}
                    full.append({"task_id": rec["task_id"], "history": hname,
                                 "fn": fname, "raised": str(e)[:200]})
            safe.append(case)
    return safe, full, n_pages


def digest(safe):
    blob = json.dumps(safe, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--compare", default=None, help="上一份 tier3-golden 报告；摘要一致才算零行为")
    args = ap.parse_args()

    res = run_all()
    if res is None:
        return 2
    safe, full, n_pages = res
    d = digest(safe)

    fired = {}
    for c in safe:
        r = c.get("route")
        if isinstance(r, dict) and r.get("skill"):
            fired[r["skill"]] = fired.get(r["skill"], 0) + 1
    hits = {fn: sum(1 for c in safe if isinstance(c.get(fn), dict) and c[fn].get("operation"))
            for fn, _call, _norm in FN_SET}

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "corpus": str(CORPUS.relative_to(REPO)),
        "pages": n_pages,
        "cases": len(safe),
        "digest": d,
        "route_fired_by_skill": dict(sorted(fired.items())),
        "non弃权_例数": hits,
        "fns": [n for n, _c, _n2 in FN_SET],
        "note": ("只含 operation/target 序号/skill 名/置信度；元素 label 与 href 不进这份文件，"
                 "完整输出在不入库的 m2/corpus/golden-full.json"),
    }
    stamp = datetime.now().strftime("%m%d-%H%M%S")
    out = REPO / "reports" / ("tier3-golden-%s.json" % stamp)
    io.open(out, "w", encoding="utf-8", newline="\n").write(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    io.open(FULL_OUT, "w", encoding="utf-8", newline="\n").write(
        json.dumps(full, ensure_ascii=False) + "\n")
    print("报告：%s" % out.name)
    print("pages=%d cases=%d digest=%s" % (report["pages"], report["cases"], d))
    print("route 触发面：%s" % report["route_fired_by_skill"])
    print("各函数非弃权例数：%s" % hits)

    if args.compare:
        prev = json.load(io.open(args.compare, encoding="utf-8"))
        if prev["digest"] == d:
            print("COMPARE: 摘要一字不动 ⇒ 行为未变。")
            return 0
        print("COMPARE: 摘要变了 ⇒ 行为变更，按预登记判据应当**回滚**那一步。")
        print("   上一份 %s（%s）digest=%s" % (prev.get("corpus"), prev.get("generated_at"),
                                                    prev.get("digest")))
        print("   上一份触发面：%s" % prev.get("route_fired_by_skill"))
        print("   上一份非弃权：%s" % prev.get("non弃权_例数"))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
