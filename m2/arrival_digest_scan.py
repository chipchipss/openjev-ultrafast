"""#84 的阈值来自哪：把仓里所有带 `final_page` 摘要的 task_result 事件扫一遍。

只读，零模型，零浏览器。摘要字段由 logger.page_digest 写入（10-13 起进 trace，10-14 起进 report meta），
所以样本 = "真正跑完并落了摘要的行"，不是快照、也不是编出来的形状。

用法：python m2/arrival_digest_scan.py [logs 根目录，默认 logs/]
"""
from __future__ import annotations

import collections
import glob
import json
import os
import sys

# 空壳候选：摘要里有 url/title/text_len/sha16 四个键才算测过（缺键 = 摘要之前的老行，不计）。
NEED = ("text_len", "text_sha16")


def load_rows(root: str) -> list[dict]:
    rows: list[dict] = []
    for path in glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True):
        batch = path.replace("\\", "/").split("/")
        batch_name = batch[-2] if len(batch) >= 2 else "?"
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if ev.get("event") != "task_result":
                    continue
                fp = ev.get("final_page")
                if not isinstance(fp, dict) or not all(k in fp for k in NEED):
                    continue
                # task_result 行里 `result` 是整个评测 dict（字符串字段在它内部），拆开
                inner = ev.get("result")
                if isinstance(inner, dict):
                    res = inner.get("result")
                    quad = inner.get("quadrant")
                    fcls = inner.get("failure_class")
                    fmode = inner.get("failure_mode")
                    steps = (inner.get("meta") or {}).get("steps")
                else:
                    res = inner
                    quad = ev.get("quadrant")
                    fcls = ev.get("failure_class")
                    fmode = ev.get("failure_mode")
                    steps = (ev.get("meta") or {}).get("steps")
                rows.append({
                    "batch": batch_name,
                    "task_id": ev.get("task_id"),
                    "result": res,
                    "quadrant": quad,
                    "failure_class": fcls,
                    "failure_mode": fmode,
                    "steps": steps,
                    "url": fp.get("url") or "",
                    "title": fp.get("title") or "",
                    "text_len": fp.get("text_len"),
                    "sha16": fp.get("text_sha16"),
                })
    return rows


def main() -> int:
    root = sys.argv[1] if len(sys.argv) > 1 else "logs"
    rows = load_rows(root)
    print(f"带摘要的 task_result 行：{len(rows)}（目录 {root}/）")

    empty = [r for r in rows if not r["title"].strip()]
    print(f"标题为空的行：{len(empty)}")

    groups: dict = collections.defaultdict(list)
    for r in empty:
        groups[(r["text_len"], r["sha16"], r["url"])].append(r)
    print("\n[空标题按 (text_len, sha16, url) 分组]")
    for k in sorted(groups, key=lambda x: (x[0] if x[0] is not None else -1)):
        v = groups[k]
        tasks = sorted({str(x["task_id"]) for x in v})
        res = sorted({str(x["result"]) for x in v})
        mode = sorted({str(x["failure_mode"]) for x in v})
        print(f"  len={k[0]!s:<6} sha={k[1]!s:<17} url={k[2][:52]:<52} n={len(v):<3} "
              f"tasks={tasks[:8]} res={res} mode={mode}")

    lens = sorted(int(r["text_len"] or 0) for r in rows)
    thin = [x for x in lens if x <= 200]
    print(f"\n[text_len 分布] <=200 的行：{len(thin)}  计数={sorted(collections.Counter(thin).items())}")
    print(f"  非零最小 15 个：{[x for x in lens if x > 0][:15]}")
    print(f"  中位数：{lens[len(lens) // 2]}")

    short_title = [r for r in rows if 0 < len(r["title"].strip()) <= 6]
    print(f"\n[标题 ≤6 字符的行：{len(short_title)}]")
    for k, n in collections.Counter(
        (r["title"].strip(), r["text_len"], r["result"]) for r in short_title
    ).most_common(10):
        print(f"  title={k[0]!r:<10} len={k[1]!s:<6} res={k[2]!s:<5} n={n}")

    # 判据三条在**这份样本**上的命中情况（命中 = 被记成空壳）
    def is_shell(r: dict) -> bool:
        return (not r["title"].strip()) and int(r["text_len"] or 0) <= 100

    hits = [r for r in rows if is_shell(r)]
    print(f"\n[判据 title 空 ∧ text_len ≤ 100 在这 {len(rows)} 行上命中 {len(hits)} 行]")
    for r in hits[:20]:
        print(f"  {r['batch']} {r['task_id']} res={r['result']} class={r['failure_class']} "
              f"mode={r['failure_mode']} url={r['url'][:60]} len={r['text_len']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
