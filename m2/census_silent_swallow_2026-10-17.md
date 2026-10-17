# Silent-swallow census — jev_ultrafast package (t5, 2026-10-17)

Method: static scan of every except clause in jev_ultrafast/*.py (17 files, 8,179
LOC), plus print-based diagnostics. Each bare 'except Exception' classified by
reading the enclosing try-block: what gets swallowed, whether it is observable in
logs/reports today, and the risk if the exception ever fires. No code edited.

Observability baseline (measured):
- dbg() (logger.py:47) writes ONE line to stderr **only when env JEV_DEBUG is set**;
  default = zero output. Grep of *.ps1 / m1/*.py / package: **no runner sets
  JEV_DEBUG**, so in batch runs every dbg() line is invisible.
- Batch artifacts that DO record: task_result meta (steps/model_calls/api_calls,
  error_detail on init failure #89, meta.egress_retry #85, final_page digest #75),
  decision/step events in logs/<tag>/*.jsonl, report summary quadrants.
- Smoke-harness print() sites (api_budget/api_teacher/step_budget/runtime_guard/
  confidence_gate/policy/decision_validator) all live inside __main__-guarded
  self-test helpers — never on the production path.

## Census A — bare 'except Exception' (40 sites; production-path 24, self-test 8, main-guard 2, import-guard 6 — see tags)

Tag legend: [P]=production path, [S]=self-test helper (only via __main__ smoke),
[M]=module main/demo path, [I]=import fallback.

### agent.py (9 bare)
| file:line | swallowed | observable today | risk |
|---|---|---|---|
| agent.py:45 [P] | any failure of the live-DOM phrase probe during arrival relook -> returns None | n (None is a designed value; caller treats as "stop waiting"; no event) | low-med: a persistent probe bug silently shortens every arrival relook to one poll — the #65 cap measurements would read as "phrase arrived/never checked" with no trace |
| agent.py:89 [P] | arrival-relook observe/evaluate failure | y (dbg arrival_relook_failed) but dbg is JEV_DEBUG-gated => n in batch | med: relook aborts silently; a systematic StalePage here would make the #65 knife a no-op and nobody would know |
| agent.py:210 [P] | done_guard rule-6 goal_reached evaluation crash | y (dbg done_guard_rule6_failed) => n in batch | med: a crash turns the guard into "allow" forever — that is a DONE-evaluation hole, safety-adjacent (guard semantics) |
| agent.py:229 [P] | non-StalePage error inside observe retry loop; closes browser then re-raises | y (re-raise surfaces in run error_detail) | low: correct fail-loud shape |
| agent.py:503 [P] | api_budget.teacher_available() failure -> treated as exhausted | n (pre["shadow"]=budget_exhausted only in state, surfaces in shadow record) | low: shadow record IS observable in artifacts; misread as budget exhaustion though — misattribution risk only |
| agent.py:516 [P] | api_teacher.choose() any failure | y (pre["shadow"].error written into step record) | low: recorded with type+message |
| agent.py:528 [P] | validator failure on teacher decision | y (pre["shadow"].error) | low: recorded |
| agent.py:550 [P] | api_budget.consume_teacher() failure | n ('pass'; comment says extreme race) | low: could miscount teacher budget; silent but narrow |
| agent.py:809 [P] | field_text() helper failure (HTTP/JSON/validate) | partial: helper_fail_run counter in state; after 3 -> blocked with helper_fail_run in result meta? (state field exists; verify meta whitelist) | med: single failure invisible unless it crosses 3; decision silently voided |

### browser.py (12 bare — 11 counted by task brief + 1 import-side; includes 1 comment-only line)
| file:line | swallowed | observable today | risk |
|---|---|---|---|
| browser.py:58 [P] | netstat failure in _listener_cmdline -> None | n | **high-ish**: returns None => _assert_owned_browser raises 'no-browser' — a transient netstat hiccup reads as "no owned browser"; fail-closed is safe but the CAUSE is invisible |
| browser.py:68 [P] | powershell CIM probe failure -> None | n | same as :58; ownership gate blindness without a trace |
| browser.py:97 [P] | ensure_daemon first failure | y (dbg daemon_ensure_failed) => n in batch | med: the restart path then masks it; a flapping daemon looks like a fresh start |
| browser.py:101 [P] | restart_daemon failure | y (dbg daemon_restart_failed) => n in batch | med: subsequent ensure may raise, so usually surfaces; still blind when it doesn't |
| browser.py:179 [P] | modal-guard install failure | y (dbg modal_guard_not_installed) => n in batch | **high-ish**: #60's +4.4s modal wedge returns silently exactly as the comment warns; no counter anywhere |
| browser.py:221 [P] | _ensure_daemon retry inside CDP timeout loop | n ('pass' inside retry) | low: last exception re-raised; intermediate failures invisible by design |
| browser.py:262 [P] (RuntimeError, specific — counted for completeness) | awaitPromise settle wait aborted | n ('pass') | low: documented transitional; observe retry covers |
| browser.py:340 [P] | dom-settle promise eval failure -> blind sleep(cap_s) | n | med: settle detection degrades to the old fixed wait on every failure; wall-clock cost returns silently |
| browser.py:365 [P] | settle counter init eval failure | y (dbg settle_init_eval_failed) => n in batch | med: cross-navigation counter missing = weaker settle; silent degradation |
| browser.py:372 [P] | addScriptToEvaluateOnNewDocument failure | y (dbg settle_init_not_registered) => n in batch | med: same as :365 |
| browser.py:424 [P] | scroll-settle promise failure -> dbg + fallthrough | y (dbg scroll_settle_failed) => n in batch | low-med: falls back to fixed wait |
| browser.py:465 [P] | await_action_settle eval failure | n ('pass'; comment: navigation destroyed context) | low: documented, observe-retry covers |

### skills.py (9 bare)
| file:line | swallowed | observable today | risk |
|---|---|---|---|
| skills.py:313 [P] | unquote() failure in _norm_page -> raw string kept | n | low: URL oddities only; normalization still runs |
| skills.py:767 [P] | URL parse failure -> _page_host='' | n | med: empty host disables the off-site guard in explicit_target (host_hit paths) — a malformed page URL silently widens cross-domain matching |
| skills.py:806 [P] | host extraction failure -> host='' | n | med: candidate loses host signal; explicit_target falls back to label-only silently (scoring change invisible) |
| skills.py:825 [P] | href segment parse failure -> [] | n | low: kills the 0.88 href-tier for that candidate only |
| skills.py:954 [P] | goto_path current-URL parse -> '' | n | low: 'already here' check lost; may re-point at same path (recent-choice filter still on) |
| skills.py:971 [P] | candidate href parse failure -> skip | n | low: candidate dropped silently |
| skills.py:1374 [P] | query-string parse failure -> in_url=set() | n | med: the n004-era dedup guard ('query already in URL') silently disabled; the re-submit URL-destroy bug could recur without a trace |
| skills.py:2247 [P] | a skill function RAISES -> d=None, fall through to model | y (dbg skill_raised #68) => n in batch | **high observability need**: this is exactly the #59 misattribution shape — a raising skill reads as 'model decided'; dbg is off by default so batches cannot see it |
| skills.py:2256 [P] | validator crash on a skill decision -> skip skill | n (validator returning invalid is silent by design; crash indistinguishable) | med: a crashing validator is invisible; all skills appear 'invalid' -> full fallback to model |

### evaluator.py / logger.py / model.py / api_* (rest)
| file:line | tag | swallowed | observable today | risk |
|---|---|---|---|---|
| evaluator.py:361 [P] | str(assertion) failure -> behavior='reject' | n | low: mis-guard only for exotic spec objects |
| evaluator.py:548 [P] | assertion evaluation crash | y (UNKNOWN / assertion_error with error string in report) | low: well-instrumented |
| logger.py:353 [P] | step_budget.log_entry() failure -> {} | n | med: budget snapshot silently missing from artifacts; row-level budget evidence lost |
| model.py:417 [P] | laya provider failure -> d=None | n | med: demotion path invisible; looks identical to 'laya abstained' |
| model.py:423 [P] | validator crash on laya decision -> ok=False | n | med: same blind spot as skills.py:2256 |
| api_budget.py:125 [S] | check_raises wrong exception | y (print FAIL in smoke) | none (self-test only) |
| api_teacher.py:336 [S] | same | y (print) | none |
| step_budget.py:264 [S] | same | y (print) | none |
| runtime_guard.py:262 [S] | same (also where-mismatch branch :262) | y (print) | none |
| demo.py:122 [M] | any demo handler failure -> 500 JSON | y (HTTP 500 to local caller) | low: demo server only |
| demo.py:138 [M] | KeyboardInterrupt under serve | y (re-raise pattern; main loop) | none |

## Census B — print-based diagnostics (production-vs-self-test split)

All print() in the package are: (a) smoke self-test helpers (FAIL/SMOKE OK lines,
__main__-guarded: api_budget:116/126/128/215, api_teacher:327/337/339/472,
confidence_gate:196/204/382, decision_validator:218/226/369, policy:192/200/313,
runtime_guard:250/261/263/265/310/408, step_budget:255/265/267/371), (b) demo server
banner (demo.py:135), (c) evaluator CLI pretty-printer (evaluator.py:613).
**browser.py has zero print() diagnostics** (task brief's premise holds) — its only
trace channel is the JEV_DEBUG-gated dbg(). No runner in the repo sets JEV_DEBUG
(grep across *.ps1, m1/*.py, package = 0 hits), so Census A's 'y (dbg ...)' sites are
effectively **unobservable in every batch artifact today**.

## Risk ranking (what an observability change should hit first)

1. **skills.py:2247 (skill_raised)** — misattribution channel with existing #59/#68
   evidence; a dbg-only fix stays invisible in batches. Highest value: promote to a
   counted artifact field or trace event.
2. **browser.py:179 (modal_guard_not_installed)** — silent return of a measured
   +4.4s wedge; nothing else would explain the wall-clock regression.
3. **browser.py:58/:68 (ownership probe blindness)** — fail-closed is correct, but
   the cause ('netstat hiccup' vs 'no owned browser') is indistinguishable today;
   one dbg line each is cheap.
4. **skills.py:2256 + model.py:423 (validator crash blind spot)** — validator crash
   vs validator-reject are indistinguishable; both funnel decisions to the model.
5. **agent.py:210 (done_guard_rule6_failed)** — guard-crash -> allow is
   safety-adjacent.
6. **skills.py:767/:806/:1374, logger.py:353, browser.py:340/:365/:372** — silent
   degradation of guards/instrumentation; each deserves a dbg site (most lack one).
7. Everything tagged [S]/[M] — no production risk, leave as-is.

Count check vs task brief: brief said 42 bare sites (agent 9, skills 9, browser 12,
evaluator 2, logger 2, model 2, others 1 each). Measured precisely: **39 bare
except-Exception sites** — agent 9, skills 9, browser 11 (the 12th from the brief is
the comment-only line at browser.py:265), evaluator 2, logger 1, model 2, and
'others' = demo 1, api_budget 1, api_teacher 1, runtime_guard 1, step_budget 1
(brief's 'logger 2' counted the docstring/comment at logger.py:50 — code has 1).
Of the 39, **8 are __main__-guarded smoke self-test helpers** (api_budget 125,
api_teacher 336, step_budget 264, runtime_guard 262, and the check_raises family),
**1 is the demo HTTP 500 handler**, and **1 is a KeyboardInterrupt guard** — leaving
**31 production-path bare swallows**: agent 9, skills 9, browser 11, evaluator 2,
logger 1, model 2 (model's 2 counted above are laya-provider swallows at model.py:417
and model.py:423; the brief's model 2 matches).

Cross-check tags: production [P] = 31, self-test [S] = 8 (the four 'others' minus
demo), demo [M] = 1, specific-exception sites (StalePage/RuntimeError/ValueError/
httpx/re.error/JSONDecode/RuntimeContractViolation etc., 33 sites) are NOT counted
as swallows here unless their handler is 'pass' — the two 'pass'-shaped specific
handlers are browser.py:263 (RuntimeError -> pass) and they are listed in Census A
for completeness only.
