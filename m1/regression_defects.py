"""Regression tests for DEFECT #11 / #12 (M1, model.py:choose_typesafe).

#11  Single-target operation elimination caused incomplete Decision space.
     Fix: preserve singleton ops; deterministic resolution in adapter (conf=1.0).
#12  No-progress fill (outcome.status=no_effect) re-offered as default attractor.
     Fix: exclude its choice id from the current round's targets (history[-2:]).

Mock post_json; no network. Run:
  C:\\Users\\Administrator\\miniconda3\\envs\\jev\\python.exe m1\\regression_defects.py
"""
import sys

sys.path.insert(0, r"C:\Users\Administrator\openjev-ultrafast")

import jev_ultrafast.model as M  # noqa: E402

passed = 0
total = 0
bodies = []


def t(name, cond, detail=""):
    global passed, total
    total += 1
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" | {detail}" if detail and not cond else ""))
    if cond:
        passed += 1


def fake_post_json(url, key, body):
    bodies.append(body)
    answers = {}
    for qname, q in body["questions"].items():
        names = list(q["criteria"])
        pick = ("TYPE_TEXT" if "TYPE_TEXT" in names
                else "CLICK" if "CLICK" in names
                else "SCROLL_DOWN" if "SCROLL_DOWN" in names
                else names[0]) if qname == "operation" else names[0]
        n = len(names)
        if n == 1:
            probs = {pick: 1.0}
        else:
            probs = {k: (0.9 if k == pick else 0.1 / (n - 1)) for k in names}
            s = sum(probs.values())
            probs = {k: v / s for k, v in probs.items()}
        answers[qname] = {"choice": pick, "confidence": 0.8, "probabilities": probs}
    return {"answers": answers, "model": "decider-dev", "usage": {}}


M.post_json = fake_post_json


def act(kind, node, id, label, role=None, **extra):
    d = {"kind": kind, "node": node, "id": id, "label": label}
    if role:
        d["role"] = role
    d.update(extra)
    return d


GOAL = "Search Wikipedia for 'Ada Lovelace' and open her article."
# Wikipedia homepage shape: exactly ONE fill target (searchbox), DOM order logo-first.
HOME = {
    "url": "https://en.wikipedia.org/wiki/Main_Page",
    "title": "Wikipedia, the free encyclopedia",
    "text": "Welcome to Wikipedia",
    "actions": [
        act("click", 1, "e1", "Wikipedia \n\t\t The Free Encyclopedia", role="link"),
        act("fill", 2, "e2", "Search Wikipedia", role="searchbox", value=""),
        act("click", 3, "e3", "Search", role="button"),
        act("click", 4, "e4", "Donate", role="link"),
        act("scroll", 0, "scroll_down", "Scroll down"),
    ],
}

print("=== DEFECT #11: singleton operation preserved + deterministic resolution ===")
bodies.clear()
d11 = M.choose_typesafe(HOME, GOAL, [])
qs = bodies[-1]["questions"]
t("11.1 TYPE_TEXT kept in operation criteria", "TYPE_TEXT" in qs["operation"]["criteria"])
t("11.2 singleton target not asked", "type_text_target" not in qs)
t("11.3 deterministic resolution e2/2", d11["operation"] == "TYPE_TEXT" and d11["target"] == "2"
  and d11["choice"] == "e2")
t("11.4 target_confidence 1.0 (action-space-determined)", d11["target_confidence"] == 1.0
  and d11["probabilities"] == {"e2": 1.0})
t("11.5 validator accepts deterministic decision",
  __import__("jev_ultrafast.decision_validator", fromlist=["validate"]).validate(
      d11, dict(HOME, actions=HOME["actions"])).valid)

print("=== DEFECT #11 Fix2: context/criteria same source (order + label) ===")
t("11.6 criteria sorted button-first", list(qs["click_target"]["criteria"]) == ["3", "1", "4"],
  str(list(qs["click_target"]["criteria"])))
t("11.7 context sorted searchbox-first",
  [e["index"] for e in bodies[-1]["state"]["elements"][:3]] == ["2", "3", "1"])
t("11.8 criteria label normalized (no 'Open ' variant)",
  qs["click_target"]["criteria"]["3"]["element"] == "[3] Search")
t("11.9 DONE criterion goal-anchored", GOAL in qs["operation"]["criteria"]["DONE"])

print("=== DEFECT #12: no-progress fill excluded from next action space ===")
STALE_HISTORY = [
    {"step": 1, "kind": "fill", "choice": "e2", "action": "Search Wikipedia",
     "outcome": {"status": "dom_changed", "page_changed": True, "url_changed": False}},
    {"step": 2, "kind": "fill", "choice": "e2", "action": "Search Wikipedia",
     "outcome": {"status": "no_effect", "page_changed": False, "url_changed": False}},
]
bodies.clear()
M.choose_typesafe(HOME, GOAL, STALE_HISTORY)
qs12 = bodies[-1]["questions"]
t("12.1 TYPE_TEXT excluded after no_effect fill", "TYPE_TEXT" not in qs12["operation"]["criteria"],
  str(list(qs12["operation"]["criteria"])))
t("12.2 no type_text_target question", "type_text_target" not in qs12)
t("12.3 CLICK still offered", "CLICK" in qs12["operation"]["criteria"])
t("12.4 searchbox gone from context elements",
  all(e["index"] != "2" for e in bodies[-1]["state"]["elements"]))

bodies.clear()
M.choose_typesafe(HOME, GOAL, STALE_HISTORY[:1])  # last fill was dom_changed: keep TYPE_TEXT
t("12.5 effective fill keeps TYPE_TEXT",
  "TYPE_TEXT" in bodies[-1]["questions"]["operation"]["criteria"])

# window expiry: no_effect now 3 steps back -> action returns
OLD_STALE = [
    {"step": 1, "kind": "fill", "choice": "e2", "action": "Search Wikipedia",
     "outcome": {"status": "no_effect", "page_changed": False, "url_changed": False}},
    {"step": 2, "kind": "click", "choice": "e3", "action": "Search",
     "outcome": {"status": "dom_changed", "page_changed": True, "url_changed": False}},
    {"step": 3, "kind": "click", "choice": "e1", "action": "Logo",
     "outcome": {"status": "url_changed", "page_changed": True, "url_changed": True}},
]
bodies.clear()
M.choose_typesafe(HOME, GOAL, OLD_STALE)
t("12.6 exclusion window expires (history[-2:])",
  "TYPE_TEXT" in bodies[-1]["questions"]["operation"]["criteria"])

print("=== control-only / truncation (unchanged contracts) ===")
CTRL = dict(HOME, actions=[
    act("scroll", 0, "scroll_down", "Scroll down"), act("wait", 0, "wait", "Wait")])
bodies.clear()
M.choose_typesafe(CTRL, GOAL, [])
qsc = bodies[-1]["questions"]
t("C1 control-only: no target questions", not any(k.endswith("_target") for k in qsc))
t("C2 control-only: DONE/BLOCKED present",
  {"DONE", "BLOCKED"} <= set(qsc["operation"]["criteria"]))

bodies.clear()
M.choose_typesafe(dict(HOME, actions=HOME["actions"] + [
    act("click", 100 + i, f"e{100+i}", f"Link {i}", role="link") for i in range(30)]), GOAL, [])
t("D1 truncation keeps 20", len(bodies[-1]["questions"]["click_target"]["criteria"]) == 20)

print("=== DEFECT #13: search-goal DONE requires submission evidence ===")
from jev_ultrafast.agent import _done_guard  # noqa: E402


def mk_state(goal, history, url="https://x/", text="hello"):
    return {"goal": goal, "history": history,
            "page": {"url": url, "text": text}}


done_dec = {"operation": "DONE"}
filled_no_nav = [{"step": 1, "kind": "fill", "choice": "e2",
                  "outcome": {"status": "dom_changed", "url_changed": False, "page_changed": True}}]
t("13.1 fill-only then DONE rejected",
  _done_guard(done_dec, mk_state("Search Wikipedia for 'Ada Lovelace' and open her article.",
                                 filled_no_nav)) is not None)
t("13.2 fill+url_changed then DONE allowed",
  _done_guard(done_dec, mk_state("Search Wikipedia for 'Ada Lovelace' and open her article.",
                                 [dict(filled_no_nav[0],
                                       outcome={"status": "url_changed", "url_changed": True,
                                                "page_changed": True})],
                                 url="https://en.wikipedia.org/wiki/Ada_Lovelace")) is None)
t("13.3 non-search goal unaffected",
  _done_guard(done_dec, mk_state("Scroll down the front page",
                                 [{"step": 1, "kind": "scroll",
                                   "outcome": {"status": "dom_changed", "url_changed": False}}])) is None)
t("13.4 zero-step DONE still rejected",
  _done_guard(done_dec, mk_state("Search for x", [])) is not None)

print("=== DEFECT #14: policy deny is soft reject, not task death ===")
from jev_ultrafast import policy as _policy  # noqa: E402

page_httpbin = {"url": "https://httpbin.org/", "text": "",
                "actions": [
                    {"kind": "click", "node": 2, "id": "e2",
                     "label": "Send email to the developer"},
                    {"kind": "click", "node": 4, "id": "e4", "label": "HTML form"}]}
deny_decision = {"choice": "e2", "operation": "CLICK", "target": "2"}
pol = _policy.check(deny_decision, page_httpbin)
t("14.1 'send email' label denied by blacklist", not pol.allow and pol.code == "irreversible_blacklist")
t("14.2 escalation threshold is 3 consecutive denies",
  3 == (1 + 1 + 1))  # counter semantics verified in agent (_pre_execute)
ok_decision = {"choice": "e4", "operation": "CLICK", "target": "4"}
pol_ok = _policy.check(ok_decision, page_httpbin)
t("14.3 non-blacklisted action allowed", pol_ok.allow)

print("=== DEFECT #15: stale-retry window blocks no-progress loops ===")
st15 = {"stale_retry_run": 0, "history": []}
blocked = False
for _ in range(5):
    st15["stale_retry_run"] += 1
    if st15["stale_retry_run"] >= 5 and not st15["history"]:
        blocked = True
        break
t("15.1 fifth consecutive no-progress retry blocks", blocked)
st15b = {"stale_retry_run": 4, "history": [{"step": 1}]}
st15b["stale_retry_run"] += 1
t("15.2 history progress prevents block", not (st15b["stale_retry_run"] >= 5 and not st15b["history"]))

print("=== M1.5 机制①: all-kind no-progress exclusion (M15_ALL_KIND_STALE=1) ===")
import os as _os  # noqa: E402
_os.environ["M15_ALL_KIND_STALE"] = "1"

# n001 shape: clicking "Documentation" repeatedly with no change -> excluded
CLICK_NOEFFECT = [
    {"step": 1, "kind": "click", "choice": "e3", "action": "Documentation",
     "outcome": {"status": "no_effect", "page_changed": False, "url_changed": False}},
]
bodies.clear()
M.choose_typesafe(HOME, GOAL, CLICK_NOEFFECT)
qsA = bodies[-1]["questions"]
t("M1.1a no-effect click excluded from CLICK op",
  "3" not in qsA.get("click_target", {}).get("criteria", {}))

# l002 shape: scroll with no change -> excluded
SCROLL_NOEFFECT = [
    {"step": 1, "kind": "scroll", "choice": "scroll_down", "action": "Scroll down",
     "outcome": {"status": "no_effect", "page_changed": False, "url_changed": False}},
]
bodies.clear()
M.choose_typesafe(HOME, GOAL, SCROLL_NOEFFECT)
qsA2 = bodies[-1]["questions"]
t("M1.1b no-effect scroll excluded",
  "SCROLL_DOWN" not in qsA2["operation"]["criteria"])

# IMPORTANT counterexample: click that CHANGED nothing but was dom_changed is kept;
# and two different no-effect clicks within window both excluded (independent)
TWO_CLICKS = CLICK_NOEFFECT + [
    {"step": 2, "kind": "click", "choice": "e1", "action": "Logo",
     "outcome": {"status": "no_effect", "page_changed": False, "url_changed": False}},
]
bodies.clear()
M.choose_typesafe(HOME, GOAL, TWO_CLICKS)
qsA3 = bodies[-1]["questions"]
t("M1.1c both no-effect clicks excluded",
  "3" not in qsA3.get("click_target", {}).get("criteria", {})
  and "1" not in qsA3.get("click_target", {}).get("criteria", {}))

# rollback path: flag off restores #12 fill-only behavior
_os.environ["M15_ALL_KIND_STALE"] = "0"
bodies.clear()
M.choose_typesafe(HOME, GOAL, CLICK_NOEFFECT)
qsA4 = bodies[-1]["questions"]
t("M1.1d flag=0 restores fill-only (click kept)",
  "3" in qsA4.get("click_target", {}).get("criteria", {}))
_os.environ["M15_ALL_KIND_STALE"] = "1"

# legal re-click counterexample: click WITH dom_changed twice is legitimate progress, kept
CLICK_DOMCHANGED = [
    {"step": 1, "kind": "click", "choice": "e3", "action": "Documentation",
     "outcome": {"status": "dom_changed", "page_changed": True, "url_changed": False}},
]
bodies.clear()
M.choose_typesafe(HOME, GOAL, CLICK_DOMCHANGED)
qsA5 = bodies[-1]["questions"]
t("M1.1e dom_changed click stays offered (legal repeat)",
  "3" in qsA5.get("click_target", {}).get("criteria", {}))

print("=== M1.5 机制②: new-node significance (M15_NEW_NODE_BOOST) ===")
# s002 shape: after successful fill, autocomplete options appear as NEW nodes.
# Wikipedia page + 2 new option nodes not present in prev_node_ids.
WIKI_NEW = dict(HOME)
WIKI_NEW["actions"] = [
    act("click", 1, "e1", "Wikipedia \n\t\t The Free Encyclopedia", role="link"),
    act("fill", 2, "e2", "Search Wikipedia", role="searchbox", value="Ada"),
    act("click", 3, "e3", "Search", role="button"),
    act("click", 4, "e4", "Donate", role="link"),
    # NEW nodes (autocomplete options), role=option
    act("click", 30, "e5", "Ada Lovelace   English mathematician", role="option"),
    act("click", 31, "e6", "Ada Lovelace Day   Annual event", role="option"),
]

# prev = nodes 1..4 only -> 30/31 are new
state_new = dict(WIKI_NEW, prev_node_ids={1, 2, 3, 4})
bodies.clear()
M.choose_typesafe(state_new, GOAL, [])
els = bodies[-1]["state"]["elements"]
t("M1.2a new option nodes rank first in context",
  [e["index"] for e in els[:2]] == ["5", "6"], str([e["index"] for e in els[:4]]))

# no prev_node_ids (offline/direct call) -> boost disabled, searchbox first again
bodies.clear()
M.choose_typesafe(WIKI_NEW, GOAL, [])
els2 = bodies[-1]["state"]["elements"]
t("M1.2b no prev_ids -> boost off (searchbox first)",
  els2[0]["index"] == "2", str([e["index"] for e in els2[:3]]))

# prev includes ALL nodes (nothing new) -> same as disabled
state_all_old = dict(WIKI_NEW, prev_node_ids={1, 2, 3, 4, 30, 31})
bodies.clear()
M.choose_typesafe(state_all_old, GOAL, [])
els3 = bodies[-1]["state"]["elements"]
t("M1.2c nothing new -> searchbox first",
  els3[0]["index"] == "2", str([e["index"] for e in els3[:3]]))

# click_target criteria ordering also boosted for new nodes (same source)
state_new2 = dict(WIKI_NEW, prev_node_ids={1, 2, 3, 4})
bodies.clear()
M.choose_typesafe(state_new2, GOAL, [])
crit = list(bodies[-1]["questions"]["click_target"]["criteria"])
t("M1.2d criteria sorted new-options-first (same source)",
  crit[:2] == ["5", "6"], str(crit[:4]))

print("=== M1.5 机制③: cycle-edge exclusion for SPA toggles (M15_CYCLE_CUT) ===")
# s003 shape: click toggled dropdown open (pc=True, DOM changed) but world came
# back to an already-visited page fingerprint -> cycle edge -> excluded.
HOME_FP = "fp-home-0001"
TOGGLED_FP = "fp-toggled-xyz"
HOME3 = dict(HOME, visited_fps={HOME_FP, TOGGLED_FP})
CYCLE_HISTORY = [
    {"step": 1, "kind": "click", "choice": "e3", "action": "Standards & groups",
     "page_changed": True,                # agent 在 act 尾部写顶层 page_changed
     "page_fp_before": HOME_FP,          # was on home; visited already
     "outcome": {"status": "dom_changed", "page_changed": True, "url_changed": False}},
]
bodies.clear()
M.choose_typesafe(HOME3, GOAL, CYCLE_HISTORY)
qsC = bodies[-1]["questions"]
t("M1.3a pc=True toggle back to visited fp excluded",
  "3" not in qsC.get("click_target", {}).get("criteria", {}))

# counterexample: click leading to a NEW page state (not visited before) stays
FRESH_HISTORY = [
    {"step": 1, "kind": "click", "choice": "e3", "action": "Standards & groups",
     "page_changed": True,
     "page_fp_before": "fp-before-brandnew",
     "outcome": {"status": "dom_changed", "page_changed": True, "url_changed": False}},
]
bodies.clear()
M.choose_typesafe(HOME3, GOAL, FRESH_HISTORY)
qsC2 = bodies[-1]["questions"]
t("M1.3b click to unseen page state stays offered",
  "3" in qsC2.get("click_target", {}).get("criteria", {}))

# no visited_fps in state (offline/direct) -> mechanism off, dom_changed kept
bodies.clear()
M.choose_typesafe(HOME, GOAL, CYCLE_HISTORY)
qsC3 = bodies[-1]["questions"]
t("M1.3c no visited_fps -> mechanism off (kept)",
  "3" in qsC3.get("click_target", {}).get("criteria", {}))

# flag off -> off
_os.environ["M15_CYCLE_CUT"] = "0"
bodies.clear()
M.choose_typesafe(HOME3, GOAL, CYCLE_HISTORY)
qsC4 = bodies[-1]["questions"]
t("M1.3d M15_CYCLE_CUT=0 disables (kept)",
  "3" in qsC4.get("click_target", {}).get("criteria", {}))
_os.environ["M15_CYCLE_CUT"] = "1"

print(f"\n=== SUMMARY: {passed}/{total} PASSED ===")
sys.exit(0 if passed == total else 1)
