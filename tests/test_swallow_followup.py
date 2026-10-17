
r"""t12：剩下 5 处静默降级 + runner 把汇总接进 reports/*.json。

t9 做了 4 个文件里 20 处；t5 普查风险排序的前几名全在 **skills.py / agent.py**——
这两个文件不在 t9 的 inScope 里，所以这一刀补上，并且把 meta.swallow 真正接到
生产 runner 上（t9 只把评测器白名单那一半做好，reports/*.json 里至今读不到汇总）。

按风险排序（t5 的 Risk ranking）：

  1. **skills.py:2325 skill_raised** —— #59 误诊那一整轮的形状：技能内部抛异常被吞成
     d = None，行为上"回落模型"是对的，可**哪个技能、抛了什么**在批里零痕迹，
     于是"技能明明能判达"被读成"模型能力问题"。它是这一刀里价值最高的一处。
  2. **agent.py:210 done_guard_rule6_failed** —— rule-6 守卫**崩了**与"干净放行"
     今天读起来一模一样。崩 = 这道闸形同虚设，而它守着 DONE 判定，安全相邻。
  3. **skills.py:767 / 806 / 1374** —— 守卫/仪表被 URL 解析失败静默缴械：
     _page_host='' 会关掉 explicit_target 的越域守卫；host='' 让候选丢掉主机信号；
     in_url=set() 让"同一句 query 别重复提交"守卫失效。
  4. **skills.py:2334** —— 校验器**崩了**与"校验器说非法"不可分辨，两条都 continue。

纪律同 t9：**不改控制流**（仍然 d=None / 仍然 continue / 仍然 return None），
只补一条有界诊断；**不走开关**（record_swallow 默认就记账）。

运行：python tests/test_swallow_followup.py
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
    from jev_ultrafast import logger
    logger.reset_swallows()


def _sites() -> dict:
    """本次记账里按站点聚合的读数。"""
    from jev_ultrafast.logger import swallow_summary
    return {s["site"]: s for s in swallow_summary()}


def except_block(src: str, except_match) -> str:
    """取 except 行的块体（按缩进划界，缩进从 except 行自己量）。"""
    line = src[src.rfind("\n", 0, except_match.start()) + 1:
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


def code_lines(block: str) -> str:
    return "\n".join(ln for ln in block.split("\n") if not ln.lstrip().startswith("#"))


def indented_excepts(src: str):
    return re.finditer(r"^[ \t]+except Exception[^\n]*", src, re.M)


def _skill_page():
    """一个足够简单的页：route() 会真的去调技能。"""
    return {"url": "https://example.com/", "title": "T", "text": "hello",
            "actions": [{"id": "e1", "kind": "click", "node": 1, "role": "link",
                         "label": "Docs", "href": "/docs", "value": ""}],
            "guards": {}, "fingerprint": "fp-1", "marker": "m", "marker_stable": 1,
            "page_key": [1.0, "https://example.com/", 0, 0, 1120, 780],
            "scroll": {"y": 0, "height": 900}, "w": 1120, "h": 780,
            "start_url": "https://example.com/", "omitted_actions": 0}


# ---------------------------------------------------------------------------
# ① skills.py:2325 skill_raised —— #59 误诊通道（本刀价值最高的一处）
# ---------------------------------------------------------------------------

@case("① skill_raised：技能抛异常时，降级里必须留下站点名 + 异常类型（#59 误诊通道）")
def t_skill_raised_records():
    from jev_ultrafast import skills as S

    _reset_swallows()

    def boom(page, goal, history):
        raise ValueError("skill exploded on purpose")

    saved = S.SKILLS
    S.SKILLS = (boom,)                  # 只有一个技能，且它必抛
    try:
        got = S.route(_skill_page(), "Open the docs page.", [])
    finally:
        S.SKILLS = saved
    # 行为一字不改：仍然回落模型（None），这一点与留痕同样重要
    assert got is None, f"技能异常不该改变 route() 的产出：{got!r}"
    sites = _sites()
    hit = [s for s in sites.values() if s["site"].startswith("skill_raised")]
    assert hit, (
        f"技能抛了异常，批里却零痕迹 —— #59 那轮把'技能已能判达'读成'模型能力问题'"
        f"就是这个形状。sites={sorted(sites)}")
    # 站点名带技能名（哪个技能抛的），kinds 那一格是异常类型直方图
    assert hit[0]["site"] == "skill_raised:boom", hit[0]
    assert "ValueError" in hit[0]["kinds"], hit[0]
    assert hit[0]["count"] == 1, hit[0]


@case("① 落盘形状：skill_raised 进 jsonl，带 site 与异常类型，不是只有 stderr")
def t_skill_raised_reaches_jsonl():
    from jev_ultrafast.logger import Logger
    from jev_ultrafast import skills as S

    _reset_swallows()

    def boom(page, goal, history):
        raise KeyError("missing")

    saved = S.SKILLS
    S.SKILLS = (boom,)
    try:
        S.route(_skill_page(), "Open the docs page.", [])
    finally:
        S.SKILLS = saved

    with tempfile.TemporaryDirectory() as tmp:
        log_dir = Path(tmp) / "logs"
        with Logger("t12-skill", log_dir, flush_every=1) as lg:
            lg.observe({"history": [], "decisions": [], "text_calls": []})
        rows = [json.loads(l) for l in
                (log_dir / "t12-skill.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    sw = [r for r in rows if r.get("event") == "swallow"]
    hit = [r for r in sw if str(r.get("site", "")).startswith("skill_raised")]
    assert hit, f"jsonl 里没有 skill_raised：{rows}"
    got = hit[0]
    assert got["site"] == "skill_raised:boom", got
    assert "KeyError" in (got.get("detail") or ""), got


@case("① 没抛异常的正常路径不留痕（不许把噪声塞进每一行）")
def t_clean_route_records_nothing():
    from jev_ultrafast import skills as S

    _reset_swallows()
    S.route(_skill_page(), "Open the docs page.", [])
    sites = _sites()
    assert not [s for s in sites if s.startswith("skill_raised")], f"没抛异常也留了痕：{sites}"


# ---------------------------------------------------------------------------
# ② agent.py:210 done_guard_rule6_failed —— 守卫崩了 vs 干净放行
# ---------------------------------------------------------------------------

def _done_guard_call(boom: bool):
    """驱动 `_done_guard` 的 rule-6 那一段：goal_reached 抛异常时它怎么走。

    走真实代码路径而不是重写一遍判据：这是"崩了会静默变成 allow"这一形状的复现。
    """
    from jev_ultrafast import agent as A
    from jev_ultrafast import skills as S

    # 要让控制流真的走到 rule-6：rule-1 要求有历史动作，rule-2/3/5 要求这个 goal
    # 既不是停在搜索页、也不是提交/搜索类。用一个普通导航目标 + 一条 click 历史。
    state = {"goal": "Open the 'Releases' page.",
             "page": {"url": "https://example.com/", "title": "T", "text": "hello",
                      "actions": [], "fingerprint": "fp"},
             "history": [{"kind": "click", "page_changed": True,
                          "outcome": {"url_changed": True}}],
             "_arrival_relooked": True}
    decision = {"choice": "e1", "operation": "DONE", "target": None, "skill": "goal_reached"}

    real_reached, real_link = S.goal_reached, S.link_followed_arrival

    def boom_reached(page, goal, history):
        raise ValueError("guard exploded on purpose")

    def clean_reached(page, goal, history):
        return None

    S.goal_reached = boom_reached if boom else clean_reached
    S.link_followed_arrival = clean_reached
    try:
        return A._done_guard(decision, state), state
    finally:
        S.goal_reached, S.link_followed_arrival = real_reached, real_link


@case("② done_guard_rule6_failed：rule-6 守卫崩了必须留痕（今天崩了=干净放行）")
def t_done_guard_crash_records():
    _reset_swallows()
    verdict, _state = _done_guard_call(boom=True)
    # 崩了照旧走 return None（= 放行，控制流不许改）：这正是"崩了读起来像干净放行"
    # 的形状，也是留痕的价值所在。
    assert verdict is None, f"rule-6 崩了不该变成拒绝：{verdict!r}"
    sites = _sites()
    assert "done_guard_rule6_failed" in sites, (
        f"rule-6 守卫崩了却零痕迹 —— 崩与干净放行在批里读起来一模一样，"
        f"这道闸等于没有告警。sites={sorted(sites)}")
    assert "ValueError" in sites["done_guard_rule6_failed"]["kinds"], sites


@case("② 判据不响的时候不留痕（守卫正常判没到不是事故）")
def t_done_guard_clean_is_silent():
    _reset_swallows()
    verdict, _state = _done_guard_call(boom=False)
    # 干净路径的结论是拒绝（goal_reached 说没到），不是放行。这一条只断言"没有抛异常"
    # 这件事不产生留痕；结论本身由 test_done_guard_arrival 那族管。
    assert verdict == "nav goal target not reached (goal_reached says no)", verdict
    sites = _sites()
    assert "done_guard_rule6_failed" not in sites, f"没抛异常也留了痕：{sites}"



# ---------------------------------------------------------------------------
# ③ skills.py:767 / 806 / 1374 -- 守卫与仪表被 URL 解析失败静默缴械
# ---------------------------------------------------------------------------

def _explode_urlparse(monkey_attr: str):
    """把 skills 模块里的 `_urlparse` 换成一个 .netloc / .query 一读就抛的替身。

    为什么不造一个"自己炸的 URL 字符串"：`urlparse()` 读的是**传入的字符串**，
    返回的对象才是 .netloc 的宿主 —— 让 url 属性自己炸，炸的是解析**之后**的事，
    形状不对。真正等价的故障是"解析这一步就失败"，所以换掉解析器本身，且只换
    skills 模块这一个名字（测试结束还原）。
    """
    from jev_ultrafast import skills as S

    real = S._urlparse

    class _Boom:
        @property
        def netloc(self):
            raise ValueError("malformed url")

        @property
        def query(self):
            raise ValueError("malformed url")

        path = ""

    def boom(url):
        return _Boom()

    S._urlparse = boom
    return S, real


@case("③ explicit_target：页面 URL 解析失败时记 site（越域守卫被静默关掉）")
def t_page_host_parse_failure_records():
    from jev_ultrafast import skills as S

    _reset_swallows()
    page = _skill_page()
    S, real = _explode_urlparse("netloc")
    try:
        S.explicit_target(page, "Open the 'Docs' page.", [])
    finally:
        S._urlparse = real
    sites = _sites()
    assert "explicit_target_page_host_failed" in sites, (
        f"_page_host 解析失败静默变成空串，越域守卫被关掉，批里读不出因：{sorted(sites)}")


@case("③ explicit_target：候选 href/site 解析失败时记 site（候选丢掉主机信号）")
def t_candidate_host_parse_failure_records():
    from jev_ultrafast import skills as S

    _reset_swallows()
    page = _skill_page()
    page["url"] = "https://example.com/search?q=docs"
    page["actions"] = [{"id": "e1", "kind": "click", "node": 1, "role": "link",
                        "label": "Docs", "href": "/docs", "value": ""}]
    S, real = _explode_urlparse("netloc")
    try:
        S.explicit_target(page, "Open the 'Docs' page.", [])
    finally:
        S._urlparse = real
    sites = _sites()
    assert "explicit_target_host_failed" in sites, (
        f"候选 host 解析失败静默变成空串，这一档退化成只认 label：{sorted(sites)}")


@case("③ search_submit：查询串解析失败时记 site（重复提交守卫失效）")
def t_query_parse_failure_records():
    from jev_ultrafast import skills as S

    _reset_swallows()
    page = _skill_page()
    page["url"] = "https://example.com/search?q=docs"
    page["actions"] = [{"id": "e1", "kind": "click", "node": 1, "role": "button",
                        "label": "Search", "href": "", "value": ""}]
    # 历史里要有一条"往搜索框填过"的 fill，且 `_searchbox` 认它的 action 文案
    hist = [{"kind": "fill", "action": "Search", "text": "docs", "page_changed": True}]
    S, real = _explode_urlparse("query")
    try:
        S.search_submit(page, "Search for docs and submit.", hist)
    except Exception as e:                                  # noqa: BLE001
        raise AssertionError(f"search_submit 因 URL 解析失败抛出：{type(e).__name__}: {e}")
    finally:
        S._urlparse = real
    sites = _sites()
    assert "form_submit_query_failed" in sites, (
        f"查询串解析失败静默变成空集合，重复提交守卫失效：{sorted(sites)}")


@case("③ route()：校验器崩了与说非法必须分得开")
def t_validator_crash_records():
    from jev_ultrafast import skills as S
    from jev_ultrafast import decision_validator as DV

    _reset_swallows()

    def boom_validate(d, page):
        raise RuntimeError("validator exploded on purpose")

    saved = S.SKILLS
    # 用一个在这个夹具上**真的会产出 decision** 的技能：validator 只在 d 非空时才被调用
    S.SKILLS = (S.explicit_target,)
    real = DV.validate
    DV.validate = boom_validate
    try:
        got = S.route(_skill_page(), "Open the 'Docs' page.", [])
    finally:
        S.SKILLS = saved
        DV.validate = real
    assert got is None, f"校验器崩了不该改变 route() 的产出：{got!r}"
    sites = _sites()
    assert "decision_validator_crashed" in sites, (
        f"校验器崩了与说非法不可分辨，两条都 continue：{sorted(sites)}")
    assert "RuntimeError" in sites["decision_validator_crashed"]["kinds"], sites



# ---------------------------------------------------------------------------
# ④ runner 接线：meta["swallow"] 必须真的到达 reports/*.json
# ---------------------------------------------------------------------------

@case("④ runner 把 swallow_summary() 写进 meta，评测器带进报告（离线证明，不只读代码）")
def t_runner_wires_swallow_into_meta():
    from jev_ultrafast import evaluator as E
    from jev_ultrafast.logger import record_swallow, reset_swallows
    from m1 import run_tasks as RT

    reset_swallows()
    record_swallow("skill_raised", "ValueError: boom")

    spec = {"task_id": "t12-meta", "category": "positive",
            "success_assertion": {"type": "all_of", "clauses": [
                {"type": "url_matches", "pattern": "example\\.com"}]},
            "extensions": {}}
    pg = {"url": "https://example.com/", "title": "T", "text": "hello",
          "actions": [], "fingerprint": "f"}

    state = {"history": [], "decisions": [], "page": pg}
    base = {"steps": 1, "model_calls": 0, "api_calls": 0, "elapsed_ms": 10}
    # 走 runner 自己那条 meta 组装函数（而不是在测试里重抄一遍形状）
    meta = RT._task_meta(state, {"entries": 0, "notes": 0, "suppressed": 0,
                                "cross_task": 0}, base) if hasattr(RT, "_task_meta") else None
    if meta is None:
        raise AssertionError(
            "m1/run_tasks.py 没有可复用的 meta 组装函数（_task_meta）——"
            "runner 接线无法被离线测试证明，只能读代码，那正是本条要禁的")

    res = E.evaluate(spec, pg, [], "done", meta=meta)
    got = (res.meta or {}).get("swallow")
    assert isinstance(got, list) and got, (
        f"runner 写的 meta 没有把 swallow 汇总带进报告：meta={res.meta}")
    assert any(s.get("site") == "skill_raised" for s in got), got


# ---------------------------------------------------------------------------
# 静态守卫：不许新增裸 except / 裸 pass；留痕不许改控制流
# ---------------------------------------------------------------------------

#: 本刀**亲手碰过**的 except 行号。静态判据只查这些点：agent.py 里另有几处早就存在、
#: 且不在 t12 inScope 的宽 except（45/229/503/516/528），把它们一起要求是越界执法。
TOUCHED_EXCEPTS = {
    "jev_ultrafast/skills.py": {767, 806, 1374, 2325, 2334},
    "jev_ultrafast/agent.py": {210},
}


@case("本刀碰过的 except 分支都不是裸 pass（既不留痕也不解释）")
def t_no_bare_swallow_introduced():
    for rel, lines_want in TOUCHED_EXCEPTS.items():
        src = (REPO / rel).read_text(encoding="utf-8")
        for m in indented_excepts(src):
            lineno = src[:m.start()].count("\n") + 1
            if lineno not in lines_want:
                continue
            block = except_block(src, m)
            has_trace = ("record_swallow(" in block or "dbg(" in block)
            explained = "#" in block
            assert has_trace or explained, (
                f"{rel}:{lineno} 静默的 except 分支（既不留痕也不解释为什么）：\n" + block[:160])


@case("装了留痕的 except 分支里不许出现代码级 raise")
def t_swallow_does_not_change_flow():
    checked = 0
    for rel in ("jev_ultrafast/skills.py", "jev_ultrafast/agent.py"):
        src = (REPO / rel).read_text(encoding="utf-8")
        for m in indented_excepts(src):
            block = except_block(src, m)
            if "record_swallow(" not in block:
                continue
            checked += 1
            assert not re.search(r"(?m)^\s*raise\b", code_lines(block)), (
                "装了留痕顺手把降级改成抛出：\n" + block[:200])
    assert checked >= 6, f"只查到 {checked} 处留痕分支，少于已装的 6 处：仪器没跑全"


@case("6 个目标站点全都接上了 record_swallow（站点名逐一认）")
def t_all_six_sites_are_wired():
    src = (REPO / "jev_ultrafast" / "skills.py").read_text(encoding="utf-8")
    ag = (REPO / "jev_ultrafast" / "agent.py").read_text(encoding="utf-8")
    # skill_raised 的站点名是 f-string（带技能名），所以它认前缀而不是完整字面量
    want = {
        "skills.py skill_raised": ("skills.py", 'record_swallow(f"skill_raised:'),
        "skills.py page_host": ("skills.py", 'record_swallow("explicit_target_page_host_failed"'),
        "skills.py candidate host": ("skills.py", 'record_swallow("explicit_target_host_failed"'),
        "skills.py form_submit query": ("skills.py", 'record_swallow("form_submit_query_failed"'),
        "skills.py validator crash": ("skills.py", 'record_swallow("decision_validator_crashed"'),
        "agent.py done_guard rule6": ("agent.py", 'record_swallow("done_guard_rule6_failed"'),
    }
    text = {"skills.py": src, "agent.py": ag}
    for label, (rel, needle) in want.items():
        assert needle in text[rel], f"{label} 还没接上留痕通道（{needle}）"


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


