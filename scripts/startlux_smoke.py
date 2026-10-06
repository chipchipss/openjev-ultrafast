"""Smoke-test: the StartLux-Decision package imports and renders a request.

Run with the decider venv:
  /d/openjev-models/decider/.venv/Scripts/python.exe scripts/startlux_smoke.py
"""
import sys

sys.path.insert(0, r"D:\openjev-models\startlux-decision-2b")  # GGUF repo ships the package too
sys.path.insert(0, r"D:\openjev-models\startlux-decision-pkg")

from startlux_decision import jevfmt as J  # noqa: E402

print("jevfmt", J.VERSION, "import ok")

state = {
    "page": {"url": "http://example.test/", "title": "t", "text": "hello"},
    "elements": [],
    "recent_actions": [],
}
question = {
    "type": "choice",
    "criteria": {"a": "A thing", "b": "B thing"},
    "instructions": {"goal": "test goal"},
}
rendered = J.from_systemone(state, question)
print("render ok:", str(rendered)[:120].replace("\n", " "))

from transformers import AutoTokenizer  # noqa: E402

tok = AutoTokenizer.from_pretrained(r"D:\openjev-models\startlux-decision-2b")
letters = J.check_tokenizer(tok)
cfg_ids = [32, 33, 34, 35, 36, 37, 38, 39, 40, 41]
print("tokenizer letter ids match decision_config:", letters[:10] == cfg_ids)
print("SMOKE PASS")
