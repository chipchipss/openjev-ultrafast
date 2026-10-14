r"""#83 的前置仪器：`_STUCK` 的跨任务抑制今天**看得见吗**？改之前看不见 —— 这组测试就是用来失败的。

来历（`m2/real-log.md` 的 #70 Tier 3 预登记那节）：
`skills._STUCK` 是**模块级**字典，键是页态指纹、值是每个技能剩下的停用拍数，
而且**任务之间不清洗**。夜间档 r3 实测：一轮 100 题里 111 个不同页态指纹有
**25 个被 >1 个任务共用**（最多一个指纹 6 个题共用）。
⇒ 第 N 题写的"让位"笔记，可以在第 N+1 题的前两拍把技能按住 —— 这是**跨任务通道**。
但今天 trace 里没有任何抑制/让位事件（事件种类只有 step/decision/task_result/text_call），
所以这件事**无法复核**，也就无法判断该不该改成每题复位。

这一条只做**仪器**，不做行为变更（复位会消掉跨题抑制，那是行为变更，另开 #83）。

判据的可失败性：三条案在改前都必须红 ——
① `stuck_counters` 这个公开读数**根本不存在**（AttributeError）；
② 写了一条 note 之后 `entries` 不涨（因为没有读数）；
③ 抑制发生时计数不动（同上）。

运行：python tests/test_stuck_counters.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from jev_ultrafast import skills as S                                 # noqa: E402

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


def page(fp, label="Downloads", href="/downloads"):
    return {"url": "https://docs.example.org/", "title": "Docs", "text": "",
            "start_url": "https://docs.example.org/", "fingerprint": fp,
            "actions": [{"kind": "click", "node": 1, "id": "e1", "role": "link",
                         "label": label, "href": href}]}


@case("① 公开读数存在，而且键形如 {notes, suppressed, entries}")
def t_counters_exist():
    c = S.stuck_counters()
    assert set(c) >= {"notes", "suppressed", "entries"}, c
    assert all(isinstance(v, int) for v in c.values()), c


@case("② 写一条 note ⇒ notes 与 entries 各 +1（抑制还没发生）")
def t_note_is_counted():
    before = S.stuck_counters()
    S.note_no_effect("unitfp-note", "explicit_target")
    after = S.stuck_counters()
    assert after["notes"] == before["notes"] + 1, (before, after)
    assert after["entries"] == before["entries"] + 1, (before, after)
    assert after["suppressed"] == before["suppressed"], "note 本身不该算抑制"


@case("③ 抑制真的被数到：同一页态第二拍不许由被停用的技能说话")
def t_suppression_is_counted():
    # 先让某技能在这个页态上"没效果"一次，再走一拍 route()：那一拍它必须被按住，
    # 并且按住这件事要留下计数。
    p = page("unitfp-suppress")
    S.note_no_effect("unitfp-suppress", "explicit_target")
    before = S.stuck_counters()
    S.route(p, "Open the 'Downloads' page.", [{"url": "https://elsewhere.invalid/",
                                               "kind": "click", "page_changed": True,
                                               "outcome": {"url_changed": True}}])
    after = S.stuck_counters()
    assert after["suppressed"] >= before["suppressed"] + 1, (before, after)


@case("④ 仪器不许改变行为：同一页态有无 note，route 的产出只可能差在被抑制的那一档")
def t_instrument_does_not_change_outputs():
    p = page("unitfp-neutral-a")
    goal = "Open the 'Downloads' page."
    hist = [{"url": "https://elsewhere.invalid/", "kind": "click",
             "page_changed": True, "outcome": {"url_changed": True}}]
    d_clean = S.route(p, goal, hist)
    # 同一内容换个指纹（没有被抑制记录），产出必须一致 —— 计数器只是旁观者。
    p2 = dict(p, fingerprint="unitfp-neutral-b")
    d2 = S.route(p2, goal, hist)
    assert (d_clean or {}) .get("operation") == (d2 or {}).get("operation"), (d_clean, d2)
    assert (d_clean or {}) .get("skill") == (d2 or {}).get("skill"), (d_clean, d2)


@case("⑥ 跨任务的抑制要能单独数出来：A 题写的笔记把 B 题按住 ⇒ cross_task +1")
def t_cross_task_is_counted():
    # 这是 #83 唯一需要的量：**"上一题的笔记按住这一题"发生了几次**。
    # 今天已有的读数数不出它 —— entries_at_start 数的是整张表非空，
    # 100 行那批里 61 行进场时表非空，但真正被按住的那一次发生在**写笔记的同一题里**。
    p = page("unitfp-cross")
    S.set_current_task("task-A")
    S.note_no_effect("unitfp-cross", "explicit_target")
    S.set_current_task("task-B")
    before = S.stuck_counters()
    S.route(p, "Open the 'Downloads' page.", [{"url": "https://elsewhere.invalid/",
                                               "kind": "click", "page_changed": True,
                                               "outcome": {"url_changed": True}}])
    after = S.stuck_counters()
    assert after["cross_task"] >= before["cross_task"] + 1, (before, after)


@case("⑦ 同一题里的抑制不算跨题：owner 与当前任务相同时 cross_task 不动")
def t_same_task_is_not_cross():
    p = page("unitfp-sametask")
    S.set_current_task("task-C")
    S.note_no_effect("unitfp-sametask", "explicit_target")
    before = S.stuck_counters()
    S.route(p, "Open the 'Downloads' page.", [{"url": "https://elsewhere.invalid/",
                                               "kind": "click", "page_changed": True,
                                               "outcome": {"url_changed": True}}])
    after = S.stuck_counters()
    assert after["suppressed"] >= before["suppressed"] + 1, (before, after)
    assert after["cross_task"] == before["cross_task"], (before, after)


@case("⑤ 仪器字段必须活到 reports/*.json：evaluator._meta 的白名单不许把它丢掉")
def t_meta_whitelist_carries_stuck():
    # #67/#65 同一族教训：runner 写进 meta 的仪器字段被 evaluator._meta 的白名单静默丢弃，
    # 于是"文档里的数字对不到工件"。这条案就是把那一次重犯挡在合入之前。
    from jev_ultrafast.evaluator import evaluate
    spec = {"task_id": "unit-stuck", "success_assertion": {"type": "url_matches",
                                                           "pattern": "example"}}
    final_page = {"url": "https://docs.example.org/downloads", "title": "Downloads",
                  "text": "Downloads"}
    meta = {"steps": 2, "model_calls": 2, "api_calls": 0, "elapsed_ms": 10,
            "stuck": {"entries_at_start": 3, "notes": 1, "suppressed": 2}}
    tr = evaluate(spec, final_page, [{"url": "https://docs.example.org/"}], "done", meta=meta)
    assert tr.meta.get("stuck") == meta["stuck"], tr.meta


if __name__ == "__main__":
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
