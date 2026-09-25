"""P1 Provider Contract smoke test."""
import sys
sys.path.insert(0, r"C:\Users\Administrator\openjev-ultrafast")

from jev_ultrafast.decider.provider import (
    register_provider, list_providers, get_provider, decide,
)

passed = 0
total = 0

def t(name, cond):
    global passed, total
    total += 1
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}")
    if cond:
        passed += 1

print("=== 1. registry ===")
providers = list_providers()
print(f"  registered: {providers}")
t("typesafe registered", "typesafe" in providers)
t("openai registered", "openai" in providers)

print("\n=== 2. unknown provider ===")
try:
    get_provider("nonexistent")
    t("unknown raises", False)
except ValueError as e:
    t("unknown raises", True)
    t("error lists providers", "registered" in str(e))

print("\n=== 3. decide() routing ===")
calls = []
def fake_decide(obs, goal, hist):
    calls.append(goal)
    return {"choice": "e1", "operation": "CLICK", "target": "1",
            "operation_confidence": 0.9, "target_confidence": 0.9}

register_provider("_test", fake_decide)
t("register new ok", "_test" in list_providers())

result = decide({"url": "test"}, "goal1", [], mode="_test")
t("routes by mode", len(calls) == 1 and calls[0] == "goal1")
t("returns dict", isinstance(result, dict))

print("\n=== 4. register validation ===")
try:
    register_provider("", fake_decide)
    t("empty name rejected", False)
except ValueError:
    t("empty name rejected", True)

try:
    register_provider("bad", "not_callable")
    t("non-callable rejected", False)
except TypeError:
    t("non-callable rejected", True)

print(f"\n=== SUMMARY ===")
print(f"  {passed}/{total} PASSED")
if passed == total:
    print("  SMOKE OK")
else:
    print("  SMOKE FAIL")
    sys.exit(1)
