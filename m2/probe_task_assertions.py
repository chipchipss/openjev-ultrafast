r"""L3-B：任务有效性核实 = **让产品自己的评测器去核一个真页面**（零模型）。

前两版核实器都不够用，且各自的错都记在 `m2/real-log.md`：
  ① 只看"起点页有没有那条链/那个控件"——搜索族、表单族结构性地看不见（查询词不是链）；
  ② 驱动式（自己填自己点）——这些站的搜索框要按回车、/login 的输入框没有可匹配 label，
     驱动半数是假的"通过"（我那条 `echoed` 判据把"首页正文里本来就有 list"也算成回显）。

所以这一版只问一个**不打折**的问题：
  "我为这行写的断言，是不是被一个真实页面满足？"
做法：navigate 到该行的**见证 URL**（这行题面要求的终点页），observe 之后把页面喂给
`jev_ultrafast.evaluator`——就是跑批时判 PASS/FAIL 的同一份代码。评测器说满足，这行才进
任务集；说不满足，这行直接丢。这不循环：我断言的是终点页的性质，agent 的活是**走到那里**；
见证 URL 是我对站点的假设，CDP + 评测器是证明（"curl 只筛，CDP 才算数"的同一条例）。

只在没有批次在跑时用。**默认演练**：不写结论文件，要 `--write` 才合并写（#74）。
预检发现自有 Chrome 不在 `:9222` 上时直接拒跑（返回 3），因为那种轮次写出来的不是结论，
是冒充分数的 `false` —— 10-12 那次 82 行被刷掉就是这条路径（`m2/real-log.md`）。
"""
import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\Administrator\openjev-ultrafast")
os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:2080")
os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:2080")
os.environ.setdefault("BU_CDP_URL", "http://127.0.0.1:9222")

from jev_ultrafast import evaluator as E                     # noqa: E402
from jev_ultrafast.browser import Browser, StalePage         # noqa: E402
from jev_ultrafast.browser import _assert_owned_browser      # noqa: E402

CANDS = r"C:\Users\Administrator\openjev-ultrafast\m2\tasks_l3_candidates.jsonl"
OUT = r"C:\Users\Administrator\openjev-ultrafast\m2\tasks_l3_verified.jsonl"
LOG = r"C:\Users\Administrator\openjev-ultrafast\m2\out_task_assertions.txt"

#: 出现这些字样的失败是**环境**没到位（浏览器不在、连不上、超时），不是"评测器说这条断言不成立"。
#: 分类错一次的代价是整份题集结论被冒充分数刷掉（见 m2/real-log.md 的 #74 那一节）。
_ENV_MARKS = ("no-browser", "foreign-browser", "connection", "refused",
              "timed out", "timeout", "target attach", "unable to connect",
              "getaddrinfo", "tunnel")


def observe_settled(b, tries=8):
    p = None
    for _ in range(tries):
        try:
            p = b.observe(screenshot=False)
            if str((p or {}).get("title") or "").strip():
                return p
        except StalePage:
            pass
        time_sleep()
    return p


def time_sleep():
    import time
    time.sleep(0.5)


def check(row):
    """navigate 见证 URL → 用**产品评测器本人**判这行的断言。

    `evaluate(spec, final_page, history, status)` 的 status 必须是终态之一
    （`evaluator.py:86`：done/blocked/budget_exceeded/error）；这里报 `done`，
    因为我们主张的是"这个真页面满足这条断言"。
    """
    spec = {"task_id": row["slug"], "success_assertion": row["success_assertion"],
            "category": "positive", "extensions": row.get("extensions") or {}}
    b = Browser(row["witness_url"])
    try:
        page = observe_settled(b)
        v = E.evaluate(spec, page, [], "done")
        return str(getattr(v, "result", "")) == "PASS", page
    finally:
        b.close()


def _is_env_failure(exc) -> bool:
    """"这行没证成"与"这行根本没机会被证"是两件事（#74）。后者不许冒充 False。"""
    s = ("%s:%s" % (type(exc).__name__, str(exc))).lower()
    return any(m in s for m in _ENV_MARKS)


def _preflight():
    """自有 Chrome 在不在端口上。不在就返回原因串（探针拒跑），在则返回 None。

    用的就是 runner 一直在用的那条"端口归谁"判据：`no-browser:` 与 `foreign-browser:` 都算不在。
    """
    try:
        _assert_owned_browser()
    except Exception as e:                                          # noqa: BLE001
        return "%s:%s" % (type(e).__name__, str(e)[:120])
    return None


def _read_existing():
    if not os.path.exists(OUT):
        return []
    with io.open(OUT, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def _merge_write(recs):
    """落盘是**合并**：这一轮没证成的行，不许把上一轮已证 `true` 的行降级。

    10-12 那次实况：`main()` 直接 `open(OUT, "w")` 全量重写，82 行的 `witness_ok` 被刷成
    `false`、见证字段清空，题面却一个字没动——被污染的正好是 `make_tasks_100.py` 吃的这份结论。
    """
    old = _read_existing()
    by_cid = {r.get("cid"): r for r in old}
    held = 0
    for rec in recs:
        prev = by_cid.get(rec["cid"])
        if prev is not None and prev.get("witness_ok") is True and rec.get("witness_ok") is not True:
            by_cid[rec["cid"]] = {**prev, "witness_held": "上一轮已证 true，这一轮不降级（#74）"}
            held += 1
        else:
            by_cid[rec["cid"]] = rec
    order = [r.get("cid") for r in old] + [r["cid"] for r in recs if r["cid"] not in
                                           {o.get("cid") for o in old}]
    with io.open(OUT, "w", encoding="utf-8") as f:
        for cid in order:
            if cid in by_cid:
                f.write(json.dumps(by_cid[cid], ensure_ascii=False) + "\n")
    return held


def main(argv=None):
    import argparse
    import time

    ap = argparse.ArgumentParser(
        description="让产品评测器核实候选行的断言（零模型）。默认演练：只打印，不碰结论文件。")
    ap.add_argument("--write", action="store_true",
                    help="把这一轮读数合并进 %s（已证 true 的行不降级）" % OUT)
    ap.add_argument("--only", default="", help="只跑这些 cid，逗号分隔")
    # 没有这个 parser 时 `--help` 会被当成"照跑不误"——10-12 那次 82 行被刷就是这么进来的。
    args = ap.parse_args(list(argv) if argv is not None else sys.argv[1:])

    why = _preflight()
    if why:
        print("探针拒跑：%s" % why)
        print("  自有 Chrome 得先由 scripts/start_owned_chrome.ps1 起回来。"
              "这一轮一个字节都不写：环境不可用时写出来的不是结论，是冒充分数的 false。")
        return 3

    rows = [json.loads(l) for l in io.open(CANDS, encoding="utf-8") if l.strip()]
    rows = [r for r in rows if r.get("witness_url") and r.get("success_assertion")]
    if args.only:
        want = {c.strip() for c in args.only.split(",") if c.strip()}
        rows = [r for r in rows if r.get("cid") in want]

    recs = []
    n_true = n_false = n_unknown = 0
    for r in rows:
        page = {}
        try:
            ok, page = check(r)
            if not page:
                # 整页没读到（observe 退避八次仍空）⇒ 没机会被证，不是"断言不成立"。
                ok, r["err"] = None, "no-page: observe 回空"
        except Exception as e:
            ok = None if _is_env_failure(e) else False
            r["err"] = "%s:%s" % (type(e).__name__, str(e)[:70])
        rec = {k: r.get(k) for k in ("cid", "slug", "start_url", "goal", "family",
                                     "success_assertion", "witness_url")}
        rec["witness_ok"] = ok
        rec["witness_title"] = str((page or {}).get("title") or "")[:70]
        rec["witness_url_real"] = str((page or {}).get("url") or "")[:110]
        if r.get("err"):
            rec["witness_err"] = r["err"]
        recs.append(rec)
        if ok is True:
            n_true += 1
        elif ok is False:
            n_false += 1
        else:
            n_unknown += 1
        print("  %-4s %-10s %s  %-58s %s" % (
            r["cid"], r["family"],
            {True: "✓断言成立", False: "✗丢", None: "?未证(环境)"}[ok],
            r["witness_url"][:58], rec["witness_title"][:34]))
        time.sleep(0.6)

    print("\n断言成立 %d / 不成立 %d / **未证(环境) %d**" % (n_true, n_false, n_unknown))
    if not args.write:
        print("演练模式：结论文件没动。核过读数再加 `--write`（合并写，已证 true 不降级）。")
        return 0
    held = _merge_write(recs)
    print("已写 %s（%d 行；%d 行因上一轮已证 true 而保持原样）" % (OUT, len(recs), held))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
