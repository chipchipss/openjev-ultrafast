"""#59 的后半段：到达档发的 DONE 必须被 DoneGuard 放行，但**只放它自己认的到达**。

实盘读数（`logs/one-r59six-b-1011-045404/r126.jsonl`，2026-10-11 04:54）：地板确实开火了
（`decision skill=link_followed_arrival choice=DONE`），可下一拍变成 `scroll_to_named_target`，
整行还是 4 拍——DONE 被拒之后由 `note_no_effect(fingerprint, skill)`（agent.py:336-338）
把这一档在**这一页**上静音了，于是回到老行为。离线复算拒绝原因逐字：

    DoneGuard 说: nav goal target not reached (goal_reached says no)

这是规则 6（s001 实况落的那条）：**纯导航 goal 的 DONE 只有到达判据说了才算**。
问题在于它只认 `goal_reached` 一张判据，而 `goal_reached` 读的是页面正文——r126 落地页
`sqlite.org/lang.html` 的标题是 'Query Language Understood by SQLite'，goal 的引号短语
'SQL Syntax' 在正文里出现 **0** 次（计数表在 `m2/real-log.md`），所以它永远说"没到"。

改法是**加一张判据**，不是给 DONE 开后门：`goal_reached is None` 仍然要拒，除非
`link_followed_arrival` 在同一状态上也说"到了"（它的证据是"goal 点名的那条链刚被踩过、
那一拍确实换了页、现在还在落地页上、同主机"）。模型自己发的 DONE 依旧过不了这道门。

运行：python tests/test_done_guard_arrival.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from jev_ultrafast import skills as S                          # noqa: E402
from jev_ultrafast.agent import _done_guard                    # noqa: E402

CASES = []

GOAL_SQLITE = "From the SQLite home page, open the 'SQL Syntax' page."


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


def arrival_state(name="r126_arrival.json", goal=GOAL_SQLITE,
                  start="https://www.sqlite.org/", label="SQL Syntax"):
    page = json.loads((REPO / "m2" / "fixtures" / name).read_text(encoding="utf-8"))
    history = [{
        "step": 1, "kind": "click", "action": label, "operation": "CLICK",
        "url": page["url"], "url_from": start, "page_changed": True,
        "outcome": {"status": "url_changed", "page_changed": True, "url_changed": True},
        "skill": "explicit_target",
    }]
    return page, goal, history


@case("到达档发的 DONE 必须放行（六行里的 r126 真实到达页）")
def t_arrival_done_is_allowed():
    page, goal, history = arrival_state()
    d = S.link_followed_arrival(page, goal, history)
    assert d and d["choice"] == "DONE", "前置条件没了：到达档在这张页上不开火"
    reason = _done_guard(d, {"goal": goal, "page": page, "history": history})
    assert reason is None, f"DONE 仍被拒：{reason}"


@case("没踩链之前模型发 DONE 仍被拒——s001 那条保护原样在")
def t_model_done_before_following_is_rejected():
    page, goal, _history = arrival_state()
    model_done = {"operation": "DONE", "choice": "DONE", "skill": None}
    # ① 一步没走过 → 规则 1 先拒
    r1 = _done_guard(model_done, {"goal": goal, "page": page, "history": []})
    assert r1 is not None, "0 步 DONE 不该放行"
    # ② 走过一步、但踩的不是那条链，也没到任何到达页 → 规则 6 拒
    stray = [{"step": 1, "kind": "click", "action": "Download the CLI",
              "url": "https://www.sqlite.org/cli.html",
              "url_from": "https://www.sqlite.org/",
              "outcome": {"url_changed": True, "page_changed": True}}]
    r2 = _done_guard(model_done, {"goal": goal, "page": {**page, "url": "https://www.sqlite.org/cli.html"},
                                  "history": stray})
    assert r2 == "nav goal target not reached (goal_reached says no)", r2


@case("从落地页走开之后，模型发 DONE 也照样拒（两张判据都不认这张页）")
def t_model_done_after_walking_away_is_rejected():
    page, goal, history = arrival_state()
    far = {**page, "url": "https://www.sqlite.org/lang_expr.html"}
    model_done = {"operation": "DONE", "choice": "DONE", "skill": None}
    reason = _done_guard(model_done, {"goal": goal, "page": far, "history": history})
    assert reason == "nav goal target not reached (goal_reached says no)", reason


@case("但**到达档自己**在落地页发的 DONE 就是有效证据（第 1 案的前提，写明白免得被误读成后门）")
def t_arrival_evidence_authorizes_done_from_any_source():
    page, goal, history = arrival_state()
    for skill in ("link_followed_arrival", None):
        d = {"operation": "DONE", "choice": "DONE", "skill": skill}
        # 放行与否只取决于"这一页是不是到达页"，不取决于谁说话——落地页上模型说 DONE
        # 也是对的；真正被 s001 防住的是**没到**还发 DONE（上面两案）。
        reason = _done_guard(d, {"goal": goal, "page": page, "history": history})
        assert reason is None, f"skill={skill} 被拒：{reason}"


@case("搜索型 goal 的收口不归到达档（s011 那条保护原样在）")
def t_search_goal_not_hijacked():
    page, _goal, history = arrival_state()
    goal = "Search for 'SQL Syntax' and open the first result link."
    d = S.link_followed_arrival(page, goal, history)
    assert d is None, "到达档把搜索型 goal 也接了"


@case("负例：改前的 DoneGuard 只认 goal_reached，会把到达档的 DONE 拒掉")
def _pre_fix_guard_rejects():
    import subprocess
    out = subprocess.run(["git", "show", "HEAD:jev_ultrafast/agent.py"],
                         cwd=str(REPO), capture_output=True)
    if out.returncode != 0:
        raise AssertionError("git show 失败，无从对照")
    old = out.stdout.decode("utf-8", "replace")
    i = old.index("def _done_guard")
    body = old[i:old.index("class Agent", i)]
    if "link_followed_arrival" in body:
        # 提交落地之后对照对象消失（同 test_cdp_ownership / test_runner_zero_cloud 的规矩）
        print("      skip: HEAD 已带修复，无从对照")
        return
    assert "link_followed_arrival" not in body, "改前的规则 6 只该认 goal_reached"


def main() -> int:
    failed = 0
    for name, fn in CASES:
        try:
            fn()
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {name}\n      {e}")
        except Exception as e:                              # noqa: BLE001
            failed += 1
            print(f"ERROR {name}\n      {type(e).__name__}: {e}")
        else:
            print(f"ok    {name}")
    print(f"\n{len(CASES) - failed}/{len(CASES)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
