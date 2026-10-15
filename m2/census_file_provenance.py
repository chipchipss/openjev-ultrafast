r"""#6：逐文件出处的**两层**普查。

**第一层（只读我们自己的历史）**：每个源码文件是哪一次提交带进来的。
一次带进几百个文件的提交（批量导入的形状）与"一次一个文件、带测试、带判据"的形状，在事后是可分辨的。
 bulk 阈值不是拍的：本仓历史里批量提交的实际数是 406/112/64/55/47/33，作者提交通常 ≤10。

**第二层（真字节对照）**：上游是公开仓 `browser-use/jev-ultrafast`。抓它的 git 树（含每个 blob 的 sha），
与本仓 `git ls-files -s` 的**索引 blob sha** 逐路径对 —— 两边都是 git blob sha，所以**不必下载文件内容**
就能判"这个文件与上游那一份逐字节相同 / 我们改过 / 上游没有这个文件"。
抓取命令（经操作者的出口代理，与 `docs/12-upstream-license.md` 同一条路）：

```
curl -s -x http://127.0.0.1:2080 -H "Accept: application/vnd.github+json" \
     https://api.github.com/repos/browser-use/jev-ultrafast/git/trees/HEAD?recursive=1 \
     -o logs/upstream_tree.json
```

**这一层的边界必须先说**：比的是**上游今天**的树（`truncated` 与 tree sha 会打印出来）。
我们没动过、而上游后来改了的文件，会读成"改过"——所以第二层的产出是**分诊的证据强度**，
不是"抄袭/未抄袭"的判决。要判"我们改过的那批里，改动是不是我们写的"，需要上游历史
（`/repos/.../commits?path=`），那一步要联网取更多东西，不在这层里冒充结论。
头部标记只数不印值（#79 与 `feedback-mask-third-party-values-in-docs`：邮箱只报数量）。

跑法（PATH 上的 python 没有 browser_harness，但这里只读 git 与一个 JSON）：
    C:/Users/Administrator/miniconda3/envs/jev/python.exe -X utf8 m2/census_file_provenance.py
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# 普查范围：能"被抄"的东西。题集/夹具/文档不在这一层（它们的内容由我们的判据生成规则决定）。
SOURCE_SUFFIXES = (".py", ".ps1", ".js", ".toml", ".cfg", ".ini")
EXCLUDE_TOP = ("reports/",)            # 工件不是代码

BULK_THRESHOLD = 40                     # 一次提交带进 ≥40 个文件 = 批量形状
EMAIL_RE = re.compile(rb"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
COPYRIGHT_RE = re.compile(rb"Copyright|\(c\)\s*\d{4}", re.I)
SPDX_RE = re.compile(rb"SPDX-License-Identifier", re.I)
LICENSE_RE = re.compile(rb"\b(MIT|Apache-2\.0|GPL|BSD)\b")
UPSTREAM_NAME_RE = re.compile(r"\b(JEv[-Uu]ltraFast|jev[-_]?ultrafast|JEv)\b")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True,
                          text=True, encoding="utf-8", errors="replace").stdout


def tracked_source_files() -> list[str]:
    out = []
    for f in git("ls-files").splitlines():
        f = f.strip().replace("\\", "/")
        if not f or f.startswith(EXCLUDE_TOP):
            continue
        if f.endswith(SOURCE_SUFFIXES) or "/" not in f and "." in f:
            out.append(f)
    return out


def commit_add_counts() -> dict[str, int]:
    """每个提交带进来多少个文件（用来认批量形状）。"""
    out = git("log", "--diff-filter=A", "--name-only", "--format=C\x01%h")
    counts: dict[str, int] = {}
    cur = None
    for line in out.splitlines():
        if line.startswith("C\x01"):
            cur = line.split("\x01", 1)[1]
            counts.setdefault(cur, 0)
        elif line.strip() and cur is not None:
            counts[cur] += 1
    return counts


def first_add(path: str) -> tuple[str, str]:
    """该文件最早被加入的那次提交（sha, subject）。"""
    shas = [s for s in git("log", "--reverse", "--diff-filter=A", "--format=%h", "--", path)
            .splitlines() if s.strip()]
    if not shas:
        return ("", "")
    sha = shas[0]
    subj = git("log", "-1", "--format=%s", sha).strip()
    return (sha, subj)


def header_markers(path: str) -> dict[str, int]:
    raw = (REPO / path).read_bytes()
    text = raw.decode("utf-8", errors="replace")
    return {
        "copyright": len(COPYRIGHT_RE.findall(raw)),
        "spdx": len(SPDX_RE.findall(raw)),
        "license_token": len(LICENSE_RE.findall(raw)),
        "emails": len(EMAIL_RE.findall(raw)),          # 只数，不打印
        "upstream_name": len(UPSTREAM_NAME_RE.findall(text)),
    }


def index_blobs() -> dict[str, str]:
    """本仓索引里每个跟踪文件的 git blob sha（与上游树里的 sha 同一算法，可直接对）。"""
    out: dict[str, str] = {}
    for line in git("ls-files", "-s").splitlines():
        parts = line.split()
        if len(parts) >= 4:
            out["/".join(parts[3:])] = parts[1]
    return out


def layer_two(rows: list[dict]) -> None:
    tree_path = REPO / "logs" / "upstream_tree.json"
    print("\n=== 第二层：与上游树的 blob sha 逐路径对照 ===")
    if not tree_path.exists():
        print("  没抓到上游树（logs/upstream_tree.json 不存在）⇒ 这一层不写任何结论，"
              "先跑文件头注释里那条 curl。")
        return
    tree = json.loads(tree_path.read_text(encoding="utf-8"))
    entries = [t for t in tree.get("tree", []) if t.get("type") == "blob"]
    up_by_path = {t["path"]: t["sha"] for t in entries}
    up_shas = {t["sha"]: t["path"] for t in entries}
    print(f"  上游 tree sha={tree.get('sha')}  blob 条目={len(entries)}  truncated={tree.get('truncated')}")
    ours = index_blobs()

    same, modified, renamed, only_ours = [], [], [], []
    for r in rows:
        p = r["path"]
        sha = ours.get(p)
        if sha is None:
            continue
        if p in up_by_path:
            (same if up_by_path[p] == sha else modified).append((p, sha))
        elif sha in up_shas:
            renamed.append((p, sha, up_shas[sha]))
        else:
            only_ours.append((p, sha))

    print(f"  与上游逐字节相同 = {len(same)}")
    print(f"  同路径但内容不同（我们改过，或上游后来改过）= {len(modified)}")
    print(f"  内容相同、路径不同（改名/挪目录）= {len(renamed)}")
    print(f"  上游树里没有这个路径，且内容不等于任何上游 blob = {len(only_ours)} —— 这一族是我们写的")
    print("  逐字节相同的那些（按目录）：")
    for d, n in Counter(p.split('/')[0] if '/' in p else '<root>' for p, _ in same).most_common():
        print(f"    {d:<16} {n:>3}")
    print("  内容相同但路径不同的那些：")
    for p, _, up in renamed:
        print(f"    {p}  <- 上游路径 {up}")
    print("  我们独有（sha 在上游树里找不到）的源码文件，最多列 30 个：")
    for p, _ in sorted(only_ours)[:30]:
        print(f"    {p}")
    print("  **边界**：这比的是上游**今天**的树。'同路径不同内容'里混着两种事实——我们改过它，"
          "以及我们没改而上游改过它。分开它们要上游历史（commits?path=），不在这一层里冒充结论。")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                                   # noqa: BLE001
            pass

    files = tracked_source_files()
    counts = commit_add_counts()
    rows = []
    for f in files:
        sha, subj = first_add(f)
        m = header_markers(f)
        rows.append({"path": f, "first_add": sha, "added_files_in_that_commit": counts.get(sha, 0),
                     "subject": subj, **m})

    bulk = [r for r in rows if r["added_files_in_that_commit"] >= BULK_THRESHOLD]
    authored = [r for r in rows if 0 < r["added_files_in_that_commit"] < BULK_THRESHOLD]
    untracked = [r for r in rows if not r["first_add"]]

    print(f"源码类跟踪文件（排除 reports/）= {len(rows)}")
    print(f"  由批量提交带进来（一次 ≥{BULK_THRESHOLD} 文件）= {len(bulk)}")
    print(f"  由作者提交带进来                               = {len(authored)}")
    print(f"  查不到首次加入提交（改名/重命名史）           = {len(untracked)}")

    per_dir = Counter(r["path"].split("/")[0] if "/" in r["path"] else "<root>" for r in rows)
    print("\n按目录：文件数 / 其中批量带入")
    bulk_dir = Counter(r["path"].split("/")[0] if "/" in r["path"] else "<root>" for r in bulk)
    for d, n in per_dir.most_common():
        print(f"  {d:<16} {n:>4} / {bulk_dir.get(d, 0):>4}")

    tot = {k: sum(r[k] for r in rows) for k in ("copyright", "spdx", "license_token", "emails", "upstream_name")}
    print(f"\n头部标记总量（只数不印值）：{tot}")
    flagged = [r for r in rows if r["upstream_name"]]
    print(f"源码里出现上游产品名的文件 = {len(flagged)}")
    for r in sorted(flagged, key=lambda x: -x["upstream_name"])[:10]:
        print(f"  {r['path']}  提及 {r['upstream_name']} 次  首次加入 {r['first_add']}"
              f"（那次带进 {r['added_files_in_that_commit']} 个文件）")

    triage = [r for r in bulk if not (r["copyright"] or r["spdx"] or r["license_token"])]
    print(f"\n**分诊清单**（批量带入 + 无任何出处标记）= {len(triage)} 个，人拿上游树来时要先看这批：")
    for r in sorted(triage, key=lambda x: x["path"])[:25]:
        print(f"  {r['path']}  first_add={r['first_add']} 该提交带入 {r['added_files_in_that_commit']} 文件")
    if len(triage) > 25:
        print(f"  …其余 {len(triage) - 25} 个（同一判据，全表可由本脚本重跑得到）")

    layer_two(rows)
    layer_two(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
