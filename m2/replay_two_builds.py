r""""这一行翻动了，是我的改动还是站点的改动？" —— 两个 build 重放**当场抓的同一页**。

为什么需要它：Tier 3 的 golden 语料是昨晚 23:0x 采的（`m2/corpus/`，不入库）。
它证明的是"对昨晚的页形状，改前改后输出一致"。若今天某个站自己改了（或干脆渲染不出东西），
那一行的翻动就落在 golden 的覆盖范围之外 —— 这时说"重构无行为变更"是超支的，
说"是站点变了"同样要证据。

做法（不动工作树、不 checkout、不联网、不调模型）：
1. 把 `jev_ultrafast/` 整包复制进临时目录（相对导入要用得到 `decision_validator`），
   再用 `git show <rev>:jev_ultrafast/skills.py` 的 blob **只替换那一个文件**；
2. 每个 build 各起一个**子进程**（同一个 `jev_ultrafast` 包名不能在一条进程里装两份），
   对同一个 `(page, goal, history)` 跑同一批确定性函数，打印 JSON；
3. 父进程逐字段比。两边一致 ⇒ 这一页上确定性层没差异，翻动只能来自模型采样或站点本身。

运行：
    # 1) 先零模型抓一页（需要自有 Chrome，且没有批在跑）
    python m2/probe_one_page.py https://arxiv.org/search/physics "…goal…" \\
        --came-from https://arxiv.org/ --via-label Search > m2/corpus/oneoff.json
    # 2) 再比两个 build
    python m2/replay_two_builds.py m2/corpus/oneoff.json --old-rev 53aa033~1
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FNS = ["route", "goal_reached", "link_followed_arrival", "explicit_target",
       "first_result", "first_action_floor"]


def build_tree(rev: str, workdir: Path) -> Path:
    """真包复制一份，只把 skills.py 换成指定 rev 的 blob。"""
    tree = workdir / ("tree_" + rev.replace("~", "_").replace("^", "_"))
    if tree.exists():
        shutil.rmtree(tree)
    tree.mkdir(parents=True)
    src = REPO / "jev_ultrafast"
    shutil.copytree(src, tree / "jev_ultrafast")
    out = subprocess.run(["git", "show", "%s:jev_ultrafast/skills.py" % rev],
                         capture_output=True, text=True, encoding="utf-8", cwd=str(REPO))
    if out.returncode != 0:
        raise SystemExit("git show %s:jev_ultrafast/skills.py 失败：%s"
                         % (rev, (out.stderr or "")[:200]))
    (tree / "jev_ultrafast" / "skills.py").write_text(out.stdout, encoding="utf-8")
    return tree


CHILD = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
from jev_ultrafast import skills as S
rec = json.load(open(sys.argv[2], encoding="utf-8"))
page, goal, hist = rec["page"], rec["goal"], rec["history"]
out = {}
for fn in sys.argv[3].split(","):
    f = getattr(S, fn, None)
    if f is None:
        out[fn] = {"absent": True}; continue
    try:
        d = f(page, goal, hist)
    except Exception as e:
        out[fn] = {"raised": type(e).__name__}; continue
    if isinstance(d, dict):
        out[fn] = {"operation": d.get("operation"), "target": d.get("target"),
                   "skill": d.get("skill"), "confidence": d.get("confidence"),
                   "kind": d.get("kind")}
    else:
        out[fn] = None
print(json.dumps(out, ensure_ascii=False, sort_keys=True))
'''


def run(tree: Path, snapshot: Path) -> dict:
    env = dict(os.environ)
    env.pop("JEV_DEBUG", None)
    p = subprocess.run([sys.executable, "-X", "utf8", "-c", CHILD,
                        str(tree), str(snapshot), ",".join(FNS)],
                       capture_output=True, text=True, encoding="utf-8", env=env)
    if p.returncode != 0:
        raise SystemExit("子进程失败：%s" % (p.stderr or "")[:400])
    return json.loads(p.stdout.strip().splitlines()[-1])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("snapshot")
    ap.add_argument("--old-rev", default="53aa033~1",
                    help="改前的 revision（默认 = Tier 3 第一步之前）")
    args = ap.parse_args()

    rec = json.load(open(args.snapshot, encoding="utf-8"))
    page = rec.get("page") or rec
    goal = rec.get("goal") or ""
    hist = rec.get("history")
    if hist is None:
        hist = [{"url": rec.get("came_from") or "https://elsewhere.invalid/",
                 "kind": "click", "action": rec.get("via_label") or "",
                 "page_changed": True, "outcome": {"url_changed": True}}]
    norm = {"page": page, "goal": goal, "history": hist}
    tmp = Path(tempfile.mkdtemp(prefix="twobuilds_"))
    snap = tmp / "case.json"
    snap.write_text(json.dumps(norm, ensure_ascii=False), encoding="utf-8")

    old = run(build_tree(args.old_rev, tmp), snap)
    new = run(build_tree("HEAD", tmp), snap)
    print("页：%s" % str(page.get("url"))[:80])
    print("goal：%s" % goal[:90])
    print("可点元素=%d  标题=%r" % (len(page.get("actions") or []),
                                     str(page.get("title") or "")[:32]))
    same = True
    for fn in FNS:
        a = json.dumps(old.get(fn), ensure_ascii=False, sort_keys=True)
        b = json.dumps(new.get(fn), ensure_ascii=False, sort_keys=True)
        if a != b:
            same = False
        print("  %-22s %s  改前=%s  改后=%s" % (fn, "同" if a == b else "**异**",
                                                a[:72], b[:72]))
    shutil.rmtree(tmp, ignore_errors=True)
    print("")
    if same:
        print("结论：这一页上两个 build 的确定性产出**逐字段一致** ⇒ 这一行的翻动不是 Tier 3 造成的。"
              "剩下的可能只有模型采样或站点本身，要各自的证据，别合并成一句猜测。")
        return 0
    print("结论：这一页上产出**不一致** ⇒ 真行为变更，按预登记判据回滚并记账。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
