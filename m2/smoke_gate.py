r"""smoke 闸门（tier 2）的判据读者：只读 reports/*.json，不重复实现评测。

为什么不解析控制台文本：项目硬线是"每个数字都能对到工件"，而 `scripts/smoke.ps1` 与真实批
必须用**同一条**读数路径，否则闸门可以绿而批里红——那种分歧在本项目有过先例（文档数字与
reports 漂移）。评测语义的唯一作者是 `jev_ultrafast.evaluator`，它的结果已经写进报告，
这里只做"全 PASS 且 fp=0"的收口判定，并如实报出 error/blocked。

退出码：0 全绿；1 任何一行不是 PASS、或出现 false_positive、或报告缺行（blocked）。
"""
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

EXPECT = ["s005", "n004", "x001", "x002", "r142"]


def main(path):
    rep = json.load(open(path, encoding="utf-8"))
    results = rep.get("results") or []
    by_id = {x.get("task_id"): x for x in results}
    bad = []

    missing = [t for t in EXPECT if t not in by_id]
    if missing:
        bad.append("报告里没有这些行（blocked，不算通过）：%s" % ",".join(missing))

    fp = 0
    for t in EXPECT:
        x = by_id.get(t)
        if x is None:
            continue
        r = x.get("result") or {}
        quad = str(r.get("quadrant"))
        if quad == "false_positive":
            fp += 1
            bad.append("%s 是 false_positive（硬线 fp=0）" % t)
        if x.get("error") or r.get("error"):
            bad.append("%s 有 error：%s" % (t, (x.get("error") or r.get("error"))[:70]))
        if r.get("result") != "PASS":
            bad.append("%s 不是 PASS：%s/%s mode=%s steps=%s" % (
                t, r.get("result"), quad, r.get("failure_mode"), r.get("steps")))
        else:
            print("  ok   %-6s %s steps=%s" % (t, quad, r.get("steps")))

    acc = rep.get("acceptance") or {}
    if acc and acc.get("passed") is False:
        bad.append("评测侧 acceptance.passed=False：%s" % json.dumps(acc, ensure_ascii=False)[:160])

    print("  fp = %d；行数 = %d/%d" % (fp, len(by_id), len(EXPECT)))
    if bad:
        for b in bad:
            print("  FAIL %s" % b)
        return 1
    print("  smoke tier 2 PASS")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
