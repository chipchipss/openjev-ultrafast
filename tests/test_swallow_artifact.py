r"""t9：静默降级的诊断必须落在**批工件**里，而不是只在 JEV_DEBUG 后面的 stderr 里。

病灶（`m2/census_silent_swallow_2026-10-17.md` 的 Observability baseline）：
`dbg()` 是 #68 给宽 `except Exception` 留的痕，但它**只在 `JEV_DEBUG` 设置时**写一行
stderr；仓库里没有任何 runner 设它（`scripts/ci_local.ps1` / `scripts/run_one.ps1` /
`m1/run_tasks.py` / `scripts/smoke.ps1` 全数过 = 0 处）。于是：

  - `browser.py` 至今**一条 print 诊断都没有**，11 处宽 except 全挂在这个开关后面；
  - #60 那个量出来的 +4.4s 模态楔死一旦回归，表现是"某几题莫名多花两分钟"，
    而 `modal_guard_not_installed` 那一行 stderr 在批里从未出现过。

补法不是再多一行 dbg，而是给一条**不走开关的通道**：`logger.record_swallow()`（t9）
记账 → `Logger.observe()` 抽干成 `"event": "swallow"` 的 JSONL 行 → `_meta` 白名单把
汇总带进 `reports/*.json`。三条纪律逐条由下面的 case 钉住：

  1. 记账与 `JEV_DEBUG` **无关**（默认就记）；
  2. 控制流**一字不动** —— 该降级还降级、该 return None 还 return None；
  3. 异常摘要**有界**：类型名 + 截断，第三方正文不进工件（#79 同族）。

运行：python tests/test_swallow_artifact.py
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import tempfile
import contextlib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


def _reset_swallows():
    """清空模块级记账，每条 case 从干净状态开始。

    通道本身是进程级的（见 logger 里的注释）：降级发生在 Logger 建起来之前，
    所以计数器不能挂在实例上；代价就是测试之间要显式复位。
    """
    from jev_ultrafast import logger
    logger.reset_swallows()


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def except_block(src: str, except_match) -> str:
    """取 except 行的块体：按缩进划界（同 tests/test_debug_channel.py 的切分器）。

    **缩进要从 except 行自己量**：这个仓库的 except 子句带 `^[ \t]+except` 前缀匹配，
    所以 match 起点已经落在行首（紧跟在换行符后），从 match.start() 往前找换行只会
    量到它自己那一行、拿到空前缀 —— 缩进恒为 0 会让块体一路吞到函数尾，把循环体里的
     `raise last` 也算进这个块体（一条假红，且最难查：红的是仪器不是代码）。
    """
    line = src[src.rfind("\n", 0, m_start(except_match)) + 1:
              src.index("\n", except_match.start())]
    indent = len(line) - len(line.lstrip())
    lines = src[src.index("\n", except_match.end()) + 1:].split("\n")
    out = []
    for ln in lines:
        if not ln.strip():
            out.append(ln)
            continue
        if len(ln) - len(ln.lstrip()) <= indent:
            break
        out.append(ln)
    return "\n".join(out[:14])


def m_start(match) -> int:
    """match.start() 的显式取用（可读性：except_block 里要区分"行起点"与"match 起点"）。"""
    return match.start()


def code_lines(block: str) -> str:
    """去掉注释行之后的块体。

    为什么必须要这一步：块体的注释里**可以**出现 raise 这个词——browser.py 的
    `# 末次异常仍会由循环外的 raise last 抛出` 就是在解释"为什么这里不抛"。
    拿注释当红线会造出一条假红，而假红最贵的代价是让人去改代码迁就仪器。
    """
    return "\n".join(ln for ln in block.split("\n") if not ln.lstrip().startswith("#"))


def indented_excepts(src: str):
    """只认有缩进的 except 子句。

    注释与文档串里也有 "except Exception" 这个词组（browser.py 的 Fix O 注释、
    logger.py 的 dbg 文档串都在讲它），它们不是子句，不许被当站点。
    """
    return re.finditer(r"^[ \t]+except Exception[^\n]*", src, re.M)


# ---------------------------------------------------------------------------
# 通道本身：默认就记账，不经 JEV_DEBUG
# ---------------------------------------------------------------------------

@case("不设 JEV_DEBUG 也记账（老通道的病灶：默认零输出）")
def t_records_without_the_debug_flag():
    from jev_ultrafast.logger import record_swallow, swallow_summary

    _reset_swallows()
    os.environ.pop("JEV_DEBUG", None)
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        record_swallow("probe_site", "ValueError: boom")
    assert swallow_summary() == [{"site": "probe_site", "count": 1,
                                 "kinds": {"ValueError": 1}}], swallow_summary()
    # 不给开关时 stderr 仍然必须干净：留痕不许变成噪声。
    assert err.getvalue() == "", f"没开 JEV_DEBUG 也往 stderr 写了：{err.getvalue()!r}"


@case("JEV_DEBUG=1 时同一件事仍然走 dbg（老通道不丢，只是不再唯一）")
def t_debug_flag_still_emits():
    from jev_ultrafast.logger import record_swallow

    _reset_swallows()
    os.environ["JEV_DEBUG"] = "1"
    try:
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            record_swallow("probe_site", "ValueError: boom")
        assert "probe_site" in err.getvalue(), f"开了开关反而不出声：{err.getvalue()!r}"
    finally:
        os.environ.pop("JEV_DEBUG", None)


@case("诊断串有界：异常类型名保留，第三方正文被截断在工件外")
def t_diag_is_bounded():
    from jev_ultrafast.logger import exc_diag

    got = exc_diag(ValueError("x" * 4000))
    assert got.startswith("ValueError: "), got[:40]
    assert len(got) < 200, f"摘要没有被截断（{len(got)} 字符）——长串会把一行 jsonl 撑爆"
    assert "x" * 200 not in got, "整段异常正文进了工件（#79：第三方内容不进可分享工件）"


@case("swallow 事件落 jsonl：同一份文件、event/task_id/timestamp 三件套齐全")
def t_swallow_event_reaches_jsonl():
    from jev_ultrafast.logger import Logger, record_swallow

    _reset_swallows()
    with tempfile.TemporaryDirectory() as tmp:
        log_dir = Path(tmp) / "logs"
        with Logger("t-swallow", log_dir, flush_every=1) as lg:
            record_swallow("modal_guard_not_installed", "RuntimeError: daemon 不支持")
            ev = lg.observe({"history": [], "decisions": [], "text_calls": []})
            assert [e["event"] for e in ev] == ["swallow"], ev
        rows = _read_jsonl(log_dir / "t-swallow.jsonl")
        assert len(rows) == 1, rows
        row = rows[0]
        assert row["event"] == "swallow", row
        assert row["site"] == "modal_guard_not_installed", row
        assert row["detail"] == "RuntimeError: daemon 不支持", row
        assert row["task_id"] == "t-swallow", row
        assert "timestamp" in row, row


@case("同一条降级只落盘一次（第二次 observe 不许重复搬）")
def t_swallow_drained_once():
    from jev_ultrafast.logger import Logger, record_swallow

    _reset_swallows()
    with tempfile.TemporaryDirectory() as tmp:
        log_dir = Path(tmp) / "logs"
        with Logger("t-once", log_dir, flush_every=1) as lg:
            record_swallow("dom_settle_eval_failed", "StalePage: changed")
            lg.observe({"history": [], "decisions": [], "text_calls": []})
            again = lg.observe({"history": [], "decisions": [], "text_calls": []})
        assert again == [], f"同一条降级被搬了两次：{again}"
        assert len(_read_jsonl(log_dir / "t-once.jsonl")) == 1


@case("抽干队列不等于丢掉汇总：summary 是 reports/*.json 的唯一来源")
def t_summary_survives_the_drain():
    from jev_ultrafast.logger import Logger, record_swallow, swallow_summary

    _reset_swallows()
    with tempfile.TemporaryDirectory() as tmp:
        with Logger("t-sum", Path(tmp) / "logs", flush_every=1) as lg:
            record_swallow("dom_settle_eval_failed", "StalePage: a")
            record_swallow("dom_settle_eval_failed", "StalePage: b")
            record_swallow("listener_probe_failed", "OSError: netstat")
            lg.observe({"history": [], "decisions": [], "text_calls": []})
        assert _read_jsonl(Path(tmp) / "logs" / "t-sum.jsonl"), "jsonl 是空的"
        by = {s["site"]: s for s in swallow_summary()}
        assert by["dom_settle_eval_failed"]["count"] == 2, by
        assert by["dom_settle_eval_failed"]["kinds"] == {"StalePage": 2}, by
        assert by["listener_probe_failed"]["count"] == 1, by


# ---------------------------------------------------------------------------
# 上工件：汇总必须穿过 _meta 白名单到 reports/*.json
# ---------------------------------------------------------------------------

@case("meta.swallow 过白名单；没发生降级的题不写这个键")
def t_swallow_survives_meta_whitelist():
    from jev_ultrafast.evaluator import evaluate

    spec = {"task_id": "t-meta", "category": "positive",
            "success_assertion": {"type": "all_of", "clauses": [
                {"type": "url_matches", "pattern": "example\\.com"}]},
            "extensions": {}}
    pg = {"url": "https://example.com/", "title": "T", "text": "hello", "actions": []}
    rows = [{"site": "modal_guard_not_installed", "count": 1, "kinds": {"RuntimeError": 1}}]
    res = evaluate(spec, pg, [], "done", meta={"swallow": rows})
    assert (res.meta or {}).get("swallow") == rows, (
        f"runner 写了汇总，白名单却只放旧四件：reports/*.json 里读不到 —— {res.meta}")

    _reset_swallows()
    clean = evaluate(spec, pg, [], "done")
    assert "swallow" not in (clean.meta or {}), (
        f"没降级的行也被写了 meta.swallow（批量空结构）：{clean.meta}")


@case("汇总只带站点与计数：URL 与查询串不许跟着进报告")
def t_summary_carries_no_page_content():
    from jev_ultrafast.logger import record_swallow, reset_swallows, swallow_summary
    from jev_ultrafast.logger import exc_diag

    reset_swallows()
    record_swallow("dom_settle_eval_failed",
                   exc_diag(RuntimeError("Document at https://vendor.example/cart?token=abc123")))
    blob = json.dumps(swallow_summary(), ensure_ascii=False)
    assert "vendor.example" not in blob, f"URL 进了汇总：{blob}"
    assert "abc123" not in blob, f"查询串进了汇总：{blob}"


# ---------------------------------------------------------------------------
# 代表性站点：browser.py 那条"装不上就照旧跑"的路径
# ---------------------------------------------------------------------------

@case("代表站点：模态框防御装不上时，产物里有 diagnostic（改前只有 JEV_DEBUG 后面的 stderr）")
def t_modal_guard_failure_is_observable():
    """RED-FIRST 的本体。

    改前这条 case 红：record_swallow 还没接上 Browser.__init__ 的宽 except，
    那一行 stderr 又被 JEV_DEBUG 挡着，批里一个字都没有（t5 普查标 n）。
    """
    import importlib
    from jev_ultrafast import browser as B
    from jev_ultrafast.logger import swallow_summary

    _reset_swallows()
    keys = ("BU_CDP_URL", "BU_CDP_WS", "JEV_CDP_PORT", "JEV_DEBUG")
    saved = {k: os.environ.get(k) for k in keys}
    for k in keys:
        os.environ.pop(k, None)
    try:
        b = importlib.reload(B)

        class Exploding:
            """只让 new-document 脚本注册失败，其余一切照旧 —— 与
            tests/test_browser_modal_guard.py 的失败注入同形状。"""

            def __init__(self):
                self.calls = []

            def cdp(self, method, session_id=None, _response_timeout=None, **params):
                self.calls.append(method)
                if method == "Target.createTarget":
                    return {"targetId": "T1"}
                if method == "Target.attachToTarget":
                    return {"sessionId": "S1"}
                if method == "Page.addScriptToEvaluateOnNewDocument":
                    raise RuntimeError("daemon 不支持")
                return {"result": {"value": "complete"}}

        fake = Exploding()
        b.cdp = fake.cdp
        b._ensure_daemon = lambda: None
        b._assert_owned_browser = lambda: None

        inst = b.Browser("https://example.com/")
        assert inst is not None, "防御注册失败把会话起不来了——那是行为变更，不是留痕"
        assert fake.calls.index("Page.enable") < fake.calls.index("Page.navigate"), fake.calls

        sites = {s["site"] for s in swallow_summary()}
        assert "modal_guard_not_installed" in sites, (
            f"防御装不上在本批产物里没有任何痕迹，site set={sorted(sites)}；"
            "#60 的 +4.4s 回归就只能靠墙钟差猜（t5 普查：browser.py 零 print 诊断）")
        got = next(s for s in swallow_summary()
                   if s["site"] == "modal_guard_not_installed")
        assert "RuntimeError" in got["kinds"], got
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        importlib.reload(B)
        _reset_swallows()


@case("留痕不改控制流：宽 except 的块体里不许出现 raise（#68 的边界）")
def t_swallow_does_not_change_flow():
    """静态断言：装了 record_swallow 的 except 分支仍然只是降级。

    与 test_debug_channel.py 的 t_dbg_does_not_change_flow 同一族，只管 t9 这一刀
    新碰过的四个文件。
    """
    from jev_ultrafast.logger import exc_diag  # noqa: F401  (import 门：通道必须还在)

    checked = 0
    for rel in ("jev_ultrafast/browser.py", "jev_ultrafast/evaluator.py",
                "jev_ultrafast/model.py", "jev_ultrafast/logger.py"):
        src = (REPO / rel).read_text(encoding="utf-8")
        for m in indented_excepts(src):
            block = except_block(src, m)
            if "record_swallow(" not in block:
                continue
            checked += 1
            # 只看**块体自己的代码行**（最多 4 行深）：注释里可以引用 raise，
            # 而循环体/函数体里本来就有的 raise 不属于这个块体 —— 两条都是假红来源。
            assert not re.search(r"(?m)^\s*raise\b", code_lines(block)), (
                "装了留痕顺手把降级改成抛出：\n" + block[:200])
    # 15 = browser 11（含 2 处归属探针）+ evaluator 2 + model 2 + logger 1
    # （budget_snapshot）。少一处就说明这一刀没有铺满，要跟着补而不是放宽判据。
    assert checked >= 15, f"只查到 {checked} 处留痕分支，少于已装的 15 处：仪器没跑全"


@case("没有任何一处退化成裸 except / 裸 pass")
def t_no_bare_swallow_introduced():
    """t9 的边界条件：不许新增静默点。

    判据是"块体既没有留痕也没有注释解释"，纯 except Exception: pass 会红。
    """
    for rel in ("jev_ultrafast/browser.py", "jev_ultrafast/evaluator.py",
                "jev_ultrafast/model.py", "jev_ultrafast/logger.py"):
        src = (REPO / rel).read_text(encoding="utf-8")
        for m in indented_excepts(src):
            block = except_block(src, m)
            has_trace = ("record_swallow(" in block or "dbg(" in block)
            explained = "#" in block
            assert has_trace or explained, (
                f"{rel}: 静默的 except 分支（既不留痕也不解释为什么）：\n" + block[:160])


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                                       # noqa: BLE001
            pass
    failed = 0
    for name, fn in CASES:
        try:
            fn()
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {name}\n      {e}")
        except Exception as e:                                  # noqa: BLE001
            failed += 1
            print(f"ERROR {name}\n      {type(e).__name__}: {e}")
        else:
            print(f"ok    {name}")
    print(f"\n{len(CASES) - failed}/{len(CASES)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

