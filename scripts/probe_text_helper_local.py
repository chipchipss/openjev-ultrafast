"""Can the local StartLux-Decision-2B serve as the Text Helper? (zero cloud)

Posts the real text_value.txt system prompt + an r119-shaped field context to
llama-server on :8081 (OpenAI-compatible), temperature 0, response_format
json_object. Prints the raw content and whether it parses to {"text": ...}.
"""
import json
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

GOAL = ("Search Hugging Face for 'bert-base-uncased' and open the model page "
        "'google-bert/bert-base-uncased'.")

CTX = {
    "goal": GOAL,
    "field": {"label": "Search models, datasets, users...", "role": "textbox",
              "value": ""},
    "page": {"title": "Hugging Face – The AI community building the future.",
             "url": "https://huggingface.co/",
             "text": "Models Datasets Spaces Docs Pricing "
                     "Search models, datasets, users..."},
    "recent_actions": [],
}

CASES = [
    ("HF search box (r119)", CTX, "bert-base-uncased"),
    ("OSM search box", {"goal": "On OpenStreetMap, search for 'Zurich'.",
                       "field": {"label": "Search", "role": "textbox", "value": ""},
                       "page": {"title": "OpenStreetMap", "text": "Search"},
                       "recent_actions": []}, "Zurich"),
    ("no value in goal (D17 null)", {"goal": "Log in to the site.",
                                     "field": {"label": "Password", "role": "textbox",
                                               "value": ""},
                                     "page": {"title": "Login", "text": "Password"},
                                     "recent_actions": []}, None),
    # n004 -- the ONLY task in the 19-set whose fill went to the cloud helper.
    ("n004 RFC search box", {"goal": "Open RFC 9110 from the RFC index.",
                             "field": {"label": "Search RFCs", "role": "textbox",
                                       "value": ""},
                             "page": {"title": "RFC Editor", "url": "https://www.rfc-editor.org/",
                                      "text": "Search RFCs Find Document Title Search"},
                             "recent_actions": []}, "RFC 9110"),
]


def ask(system: str, ctx: dict) -> tuple[str, float]:
    import time
    body = {
        "model": "D:\\openjev-models\\startlux-decision-2b\\StartLux-Decision-2B-Q8_0.gguf",
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": json.dumps(ctx, ensure_ascii=False)}],
        "temperature": 0.0,
        "max_tokens": 256,
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        "http://127.0.0.1:8081/v1/chat/completions",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    t = time.perf_counter()
    with urllib.request.urlopen(req, timeout=120) as r:
        out = json.loads(r.read().decode())
    latency = (time.perf_counter() - t) * 1000
    return out["choices"][0]["message"]["content"], latency


def main() -> int:
    system = (REPO / "jev_ultrafast" / "prompts" / "text_value.txt").read_text(
        encoding="utf-8").strip()
    failures = 0
    for name, ctx, expect in CASES:
        try:
            content, latency = ask(system, ctx)
        except Exception as e:                              # noqa: BLE001
            print(f"[{name}] HTTP/parse error: {type(e).__name__}: {e}")
            failures += 1
            continue
        print(f"[{name}] {latency:.0f}ms raw={content!r}")
        try:
            obj = json.loads(content)
        except json.JSONDecodeError:
            print("   -> NOT JSON")
            failures += 1
            continue
        ok_shape = isinstance(obj, dict) and set(obj) == {"text"}
        got = obj.get("text") if ok_shape else None
        verdict = "SHAPE BAD" if not ok_shape else (
            "MATCH" if got == expect else f"MISMATCH (want {expect!r})")
        print(f"   -> shape_ok={ok_shape} text={got!r} {verdict}")
        if verdict != "MATCH":
            failures += 1
    print(f"\nusable as text helper: {failures == 0}  ({len(CASES) - failures}/{len(CASES)} cases)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
