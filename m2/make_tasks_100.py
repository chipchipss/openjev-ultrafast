r"""L3-B：把核实通过的候选合成 100 行回归集 `m2/tasks_real_100.jsonl`。

只收 `m2/tasks_l3_verified.jsonl` 里 `witness_ok=True` 的行——也就是"这行的断言被一个
真实页面满足"已由产品自己的评测器证过（`m2/probe_task_assertions.py`）。没证过的 22 行
（books.toscrape 我猜错分类 URL、the-internet 几条正文里没有我写的字样、SO 搜索撞人机验证、
openstreetmap/git 书）全部丢掉，不改断言去凑数。

`task_id` 从 r152 起接现有 50 行；`budget.steps` 给 20（与现有真实站题一致）；
`domain` 用起点站（runner 的 `_resolve_start_url` 读它）。
"""
import collections
import glob
import json
import re

VERIFIED = "m2/tasks_l3_verified.jsonl"
BASE = "m2/tasks_real.jsonl"
OUT = "m2/tasks_real_100.jsonl"
NEED = 50


def host(u):
    m = re.search(r"(?://|^)([^/?#]+)", u or "")
    return m.group(1) if m else str(u)


allbase = {json.loads(l)["task_id"]: json.loads(l)
           for l in open(BASE, encoding="utf-8") if l.strip()}
# 基线只取**批里实跑的那 50 个 id**（`m2/tasks_real.jsonl` 有 52 行：r118 判为站点作废、
# r151 是预备题，都不在实跑集里）。以最近一个已提交批次报告的顺序为准。
rep_path = sorted(glob.glob("reports/real-1011-b26-anchor-*.json"))[-1]
order = [x["task_id"] for x in json.load(open(rep_path, encoding="utf-8"))["results"]]
base = [allbase[t] for t in order if t in allbase]
rows = [json.loads(l) for l in open(VERIFIED, encoding="utf-8") if l.strip()]
ok = [r for r in rows if r.get("witness_ok")]
print("基线 = %d 行（取自 %s 的实跑顺序）；核实通过 = %d 行（丢掉 %d）"
      % (len(base), rep_path.split("/")[-1][:34], len(ok), len(rows) - len(ok)))
if len(base) != 50 or len(ok) < NEED:
    raise SystemExit("基线不是 50 行，或核实通过的行数不足 %d —— 先补候选再合成" % NEED)

picked = ok[:NEED]


def honest_goal(r):
    r"""题面不能比断言更硬。

    语料里已有的搜索题（r101/r104）把断言钉在**最终结果 URL**（`pypi.org/project/Flask`、
    `pubmed…/\d{7,8}`），题面写 "open the first result" 是对的。我这批新题的断言只到
    "搜索结果页"（见证 URL 就是那一页），所以题面必须改成"到结果页"——
    不能拿弱断言配强题面，那样 PASS 数会虚高（`docs/00-project-plan.md` 的支柱三）。
    """
    g = r["goal"]
    if r["family"] != "search":
        return g
    g = re.sub(r"\s+and open the first (result|question|repository result|model page)"
               r"\s*\.", "", g, flags=re.I) + " and reach its search results page."
    return g


out = list(base)
for i, r in enumerate(picked, 1):
    out.append({"task_id": "r%d" % (151 + i), "domain": r["start_url"],
                "category": "navigate" if r["family"] in ("navigate", "pagination") else r["family"],
                "goal": honest_goal(r), "budget": {"steps": 20},
                "success_assertion": r["success_assertion"]})
with open(OUT, "w", encoding="utf-8") as fh:
    for t in out:
        fh.write(json.dumps(t, ensure_ascii=False) + "\n")
print("写出 %s = %d 行" % (OUT, len(out)))
print("类别分布:", dict(collections.Counter(t["category"] for t in out)))
print("新 50 行族配比:", dict(collections.Counter(r["family"] for r in picked)))
print("站点数 =", len({host(t["domain"]) for t in out}))
