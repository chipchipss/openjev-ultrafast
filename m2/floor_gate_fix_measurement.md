# t17 floor-gate repair — MEASURED before design (2026-10-18)

Zero model calls. Probes: m2/probe_floor_gate_fix.py (9 candidates, click effect),
m2/probe_floor_gate_fix2.py (the 3 named candidates in depth: URL/title/text before
vs after). Owned headless Chrome :9222 (profile chrome-cdp-test, started and stopped
by the probe session; 0 chrome left afterwards, operator browser untouched).
Raw outputs committed: m2/out_floor_gate_probe.txt, m2/out_floor_gate_probe2.txt.

## The 9 measured candidates (probe #1, one fresh page per click)

| page | candidate label | floor score | page_changed | what probe #2 says actually happened |
|---|---|---|---|---|
| github.com/ | Open Enter your email | 100 (button) | **False** | NOTHING: url/title/text_len/text head all identical before/after (probe2) |
| github.com/ | Search or jump to, type / to search | 50 (button) | True | opens the search panel (state change, useful toward any search goal) |
| rfc-editor.org/ | Subscribe to new RFCs | 90 (button) | **True (BUT)** | page MUTATED to a login/interstitial: text 1106 -> 270 chars, indexed 26 -> 3, url+title unchanged (probe2) — a destructive dead-end: the homepage's own nav was wiped |
| rfc-editor.org/ | datatracker.ietf.org | -10 (link) | False | no effect (external link click no-op in this session state) |
| rfc-editor.org/ | Search (href=/search/) | -10 (link) | True | navigates to /search/ — useful |
| MDN zh-CN | **Web APIs** | 90 (button) | True | page CONTENT CHANGED: text 482 -> 760, indexed 18 -> 31, "Web APIs: Programming interfaces / Web API reference..." — the measured hop-1 of s005's two-hop path (probe2) |
| MDN zh-CN | HTML / CSS / JavaScript JS | 50 (button) | True | same shape: content panels expand (legit nav) |

## The decisive finding

**page_changed=True/False does NOT separate dead-ends from hops.**

- github footer email disclosure: page_changed=False (true zero-effect).
- rfc Subscribe: page_changed=**True** but it is a DEAD-END — it replaces the page
  with a login interstitial (text shrinks 1106→270, indexed 26→3). t15's trace
  channel would have recorded "changed" and learned nothing.
- MDN 'Web APIs': page_changed=True and PRODUCITIVE — content grows 482→760,
  indexed 18→31 (the hop that leads to Fetch API).

So design (a) (effect-instrumentation) is measured useless for the rfc case, and
design (c) (category word overlap) cannot separate 'Subscribe to new RFCs' from
'Web APIs' either — both share zero content tokens with their goals ('rfc' stem
matches, but that same stem would have to be the gate's signal for rfc... and
'Web APIs' shares ZERO tokens with s005's goal — Search MDN fetch Fetch API —
so ANY token-based allow-list blocks the legitimate hop first).

## What DOES separate them (measured, not a word list)

The destructive dead-ends and the productive hops differ in the **page-state
transition they produce**:

- dead-end (github email, rfc Subscribe): the page state does not grow —
  text_len and indexed count stay flat or SHRINK (489→489; 1106→270 / 26→3).
- productive hop (Web APIs, HTML, CSS, Search, Search-or-jump): the page state
  GROWS — text_len and indexed count increase (482→760 / 18→31).

## Design chosen: HISTORY-PROMISE on the page-state transition (design b, refined)

Gate only on **repetition of a measured no-growth click**: when the floor's
preferred CLICK candidate has already been clicked earlier in THIS task from the
same page state (same page fingerprint) and that click produced **no page
transition at all** (url path unchanged AND title unchanged — the probe2 verdict
shape), the floor must not re-fire it. It may pick the next-best candidate
(none here → abstain).

Why this is the measured-safe subset:
  - github email: click 1 produces url_changed=False + title_changed=False →
    a second floor fire on the same page state is blocked (the measured
    zero-effect loop is cut). First tick still fires (no first-tick protection —
    accepted, per design (b) contract: "provably no regression").
  - rfc Subscribe: the FIRST click wipes the page (text 1106→270, indexed 26→3)
    — the model lands on an interstitial and BLOCKs (the measured flip). On the
    NEXT tick the floor sees a *different* page state, so a pure same-state
    repeat-gate does not help there. EXTENSION justified by the same probe: the
    gate ALSO fires when the last floor click's landing page state has SHRUNK
    (text_len + indexed count both strictly smaller than the pre-click state)
    AND the URL path is unchanged — the measured signature of a destructive
    interstitial, not a navigation. 'Web APIs' is exempt by measurement: its
    transition GROWS the page (482→760, 18→31) — it can never satisfy the
    shrink predicate.
  - No labels, no domains, no category words: the predicate reads only the
    agent's own history (previous page/text/indexed vs current) and the
    candidate's identity. It is effect-based (measured transition shape), not
    vocabulary-based.
  - First-tick protection is explicitly NOT claimed (design (b) contract:
    zero first-tick protection but provably no regression). The r105/n004
    first-click pathology is NOT fully covered by this gate; what this gate
    buys is: the loop is cut on the second tick instead of burning the whole
    budget, and the destructive wipe (rfc) is detected on tick 2. The batch
    evidence (42/50) shows the burn happens over MULTIPLE ticks, so this is
    the measurable win available without regressing s005.

s005 preservation is structural: 'Web APIs' click GROWS the page (482→760 /
18→31 measured) — the shrink predicate cannot fire on it; and a same-state
repeat requires url+title unchanged, which a content-growing hop on a NEW
state never triggers (the second tick sees a different fingerprint).


## FINAL DESIGN DECISION (post-implementation check, 2026-10-18): MEASURED-NO-GO

The shrink predicate was implemented and then REVERTED after checking what agent.py
actually records in history entries (jev_ultrafast/agent.py:839-869 + :693-718):
page_changed, outcome.url_changed, url (landing), url_from, page_fp_before, text (typed
text only). **text_before/text_after and indexed counts are NOT recorded.**

Against the real fields:
- rfc Subscribe wipe: page_changed=True, outcome.url_changed=False, url == url_from
- MDN Web APIs hop:  page_changed=True, outcome.url_changed=False, url == url_from

**The two shapes are IDENTICAL in every recorded field.** The measured separator
(text/indexed growth vs shrink) exists only in the live browser, and the field that
would carry it lives in agent.py — out of scope for t17.

Therefore:
- NO new gate lands. The existing "no page_changed -> do not re-fire" guard
  (pre-existing, skills.py) already covers the github email case and the x002 blind
  case on tick 2+ (measured: they are no-effect repeats; the r105 batch burn is
  cut by that guard, not extended).
- The rfc destructive wipe remains open. It needs agent.py to record the pre-click
  text length (one line) — that is the next knife, and it is out of scope here.
- skills.py vs rollback commit 47871e9: only a documentation comment differs
  (the measured-no-go note pointing at the probes). Zero behavior change.
- tests/test_floor_goal_gate.py re-scoped honestly: 10/10, no SKIPs, no red-witness
  left behind — cases ①⑥ pin the existing no-effect-repeat guard, case ② pins the
  measured rfc shape (first tick fires; no-effect repeat already blocked) and names
  the wipe gate as measured-no-go, case ⑩ pins the s005 two-hop preservation
  (Web APIs first tick + continued exploration on a grown page state).
- probes + raw outputs committed: m2/probe_floor_gate_fix.py,
  m2/probe_floor_gate_fix2.py, m2/out_floor_gate_probe.txt,
  m2/out_floor_gate_probe2.txt, this report.
