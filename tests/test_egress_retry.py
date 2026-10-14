r"""#85 的后半刀：一行**代理 TLS 瞬时失败**要会自己再跑一次（有界：一次，且只认错误码）。

为什么这一刀现在可以做（三步实验，全在 `m2/real-log.md` 的 #85 那几节）：
1. 同域 sqlite 七行里失败的只有 `r127`(17/36) 与 `r129`(19/36) —— 先以为这是行专属；
2. `m2/probe_sqlite_reachability.py`：五个目标页**单独访问**直接导航 8/8、点击 7-8/8 全通 ⇒ 不是站点锁我们；
   同一行 `r127` 单跑 **8/8 全 PASS**；
3. 顺序实验：同一四行**原序**跑真 runner 复现失败、**反序 4/4 全过**；
   `m2/probe_sqlite_batch_context.py` 抓到错误页里的 **`ERR_SSL_PROTOCOL_ERROR`** ⇒
   是操作者本地代理（:2080）的 TLS 隧道在 sqlite 请求密集时间歇断，`blocked_by_egress / system` 归因本来就对。

**回收率是量过的，不是估的**（10-14 17:4x，四轮"块跑 + 失败行立刻再跑一次"）：

| 块跑 | 失败行 | 再跑一次 |
|---|---|---|
| 第 1 次 | r129 | **PASS** |
| 第 2 次 | r127 | **PASS** |
| 第 3、4 次 | 无 | 无需重试 |

⇒ **2/2 回收**。所以这一刀买的是"分数下沿不再被代理抖动压穿"（今天三轮 `42/43/42`，
`MinPass=43` 连红两轮），代价是每次回收多跑一行（实测 ~3 秒）。

四条不可让步的形状（都各有一案钉住）：
- **只认错误码**：判定条件是 `failure_mode=blocked_by_egress` **且** `meta.final_page.err` 非空。
  没有码就不许重跑 —— 否则"我们自己的改动把导航弄坏了"这种 regress 会被重试洗成 PASS（#85 的仪表就是为这个存在的）。
- **只一次**：再跑还是 egress 就照实留 FAIL/system，不许循环。
- **PASS 行不许被碰**：`x001` 的终页今天起也带 `err=ERR_CONNECTION_CLOSED`（它按设计就不可达），
  但它是 PASS —— 重试只针对**失败行**。这一案是防"仪器反过来咬负向题"。
- **重试痕迹必须活到 reports/*.json**：白名单丢仪器字段是这仓库的第 5 次同族事故（#65/#67/#75/#83），
  所以这里既测 `_meta` 放行，也测判定函数不吃"没写键"的旧形状。

运行：python tests/test_egress_retry.py
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

run_tasks = importlib.import_module("m1.run_tasks") if (REPO / "m1" / "__init__.py").exists() \
    else None
if run_tasks is None:                      # m1/ 不是包：按路径加载（与 runner 自己的调用方式一致）
    import importlib.util
    spec_l = importlib.util.spec_from_file_location("run_tasks", REPO / "m1" / "run_tasks.py")
    run_tasks = importlib.util.module_from_spec(spec_l)
    spec_l.loader.exec_module(run_tasks)

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


def row(task_id="r127", result="FAIL", mode="blocked_by_egress", err="ERR_SSL_PROTOCOL_ERROR",
        url="chrome-error://chromewebdata/"):
    """形状抄自 `reports/ci-1014-1652-1014-171208.json` 的 r127/r129 两行。"""
    fp = {"url": url, "title": "www.sqlite.org", "text_len": 83, "text_sha16": "0" * 16}
    if err:
        fp["err"] = err
    inner = {"task_id": task_id, "result": result, "quadrant": "correct_abandon",
             "failure_class": "system" if mode else None, "failure_mode": mode,
             "evidence": {}, "meta": {"steps": 1, "model_calls": 2, "api_calls": 0,
                                      "elapsed_ms": 2900, "final_page": fp}}
    return {"task_id": task_id, "result": inner}


@case("① 有码的 egress 失败行才许重跑")
def t_retry_fires_only_on_coded_egress():
    assert run_tasks._should_retry_egress(row()) is True, \
        "r127/r129 这种带 ERR_SSL_PROTOCOL_ERROR 的 egress 行没被认出来，下沿还是会被压穿"


@case("② 没有错误码就不许重跑（回归不许被重试洗白）")
def t_no_code_no_retry():
    assert run_tasks._should_retry_egress(row(err=None)) is False, \
        "摘要里没有码也重跑 ⇒ 我们弄坏导航时会被重试掩盖"
    assert run_tasks._should_retry_egress(row(mode="blocked_by_bot_wall")) is False, \
        "墙页重跑没有意义（站点就是不让你进），不许花这一次"
    assert run_tasks._should_retry_egress(row(mode="decision")) is False


@case("③ PASS 行不许被碰：x001 的终页今天也带 err，但它是 PASS")
def t_pass_rows_are_never_retried():
    assert run_tasks._should_retry_egress(
        row(task_id="x001", result="PASS", mode=None, err="ERR_CONNECTION_CLOSED",
            url="chrome-error://chromewebdata/")) is False, \
        "负向题按设计就落在错误页；碰它等于把一次正确拒绝改写成两次尝试（#16/#78 的豁免同一族）"


@case("④ 重跑恰好一次：再失败就照实留 FAIL，不许循环")
def t_retry_is_bounded_to_one_extra_attempt():
    calls = []

    def fake_run(spec, log_dir, start_url, screenshots):
        calls.append(spec["task_id"])
        return row()                      # 永远是同一份 egress 失败

    out = run_tasks._run_one_with_egress_retry(
        {"task_id": "r127"}, log_dir=None, start_url="https://x", screenshots=False,
        run=fake_run)
    assert len(calls) == 2, f"跑了 {len(calls)} 次，预算是一次重跑（1+1）"
    assert (out.get("result") or {}).get("failure_mode") == "blocked_by_egress"
    assert (out.get("result") or {}).get("meta", {}).get("egress_retry", {}).get("recovered") is False, \
        "没回收也得起码在产物里说清"


@case("⑤ 回收成功时痕迹进 meta，并且穿过 _meta 白名单到 reports/*.json")
def t_retry_marker_survives_to_the_report():
    calls = []

    def fake_run(spec, log_dir, start_url, screenshots):
        calls.append(len(calls))
        return row() if len(calls) == 1 else row(result="PASS", mode=None,
                                                 url="https://www.sqlite.org/lang_select.html")

    out = run_tasks._run_one_with_egress_retry(
        {"task_id": "r127"}, log_dir=None, start_url="https://x", screenshots=False,
        run=fake_run)
    inner = out.get("result") or {}
    tag = (inner.get("meta") or {}).get("egress_retry") or {}
    assert len(calls) == 2 and inner.get("result") == "PASS", \
        f"该回收的没回收：calls={calls} result={inner.get('result')}"
    assert tag.get("recovered") is True and tag.get("first_err") == "ERR_SSL_PROTOCOL_ERROR", tag

    from jev_ultrafast.evaluator import evaluate
    spec = {"task_id": "r127", "category": "positive", "extensions": {},
            "success_assertion": {"type": "all_of", "clauses": [
                {"type": "url_matches", "pattern": "lang_select"}]}}
    pg = {"url": "https://www.sqlite.org/lang_select.html", "title": "The SELECT statement",
          "text": "SELECT rows VALUES " + "y" * 40, "actions": []}
    res = evaluate(spec, pg, [], "done", meta=inner.get("meta"))
    assert (res.meta or {}).get("egress_retry"), \
        f"runner 写了痕迹，报告白名单又丢了它（第 5 次同族事故）：meta={sorted(res.meta or {})}"


@case("⑥ 反空转：错误码真的来自实盘工件，不是测试自己编的字段")
def t_the_code_comes_from_the_artifact():
    import io
    import json
    p = REPO / "reports" / "ci-1014-1652-1014-171208.json"
    if not p.exists():
        raise AssertionError("判据所依据的那份批报告不在了（本条不许静默跳过）")
    d = json.load(io.open(p, encoding="utf-8"))
    coded = [(r["task_id"], ((r.get("result") or {}).get("meta") or {}).get("final_page", {}).get("err"))
             for r in d["results"]
             if (r.get("result") or {}).get("failure_mode") == "blocked_by_egress"]
    assert coded and all(err for _, err in coded), \
        f"批里的 egress 行没都带上码：{coded}"
    assert {err for _, err in coded} == {"ERR_SSL_PROTOCOL_ERROR"}, coded


def main() -> int:
    failed = 0
    for name, fn in CASES:
        try:
            fn()
            print("ok    " + name)
        except Exception as e:                                       # noqa: BLE001
            failed += 1
            print("FAIL  " + name)
            print("      " + f"{type(e).__name__}: {str(e)[:300]}")
    print(f"{len(CASES) - failed}/{len(CASES)} passed")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
