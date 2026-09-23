#!/usr/bin/env bash
set -euo pipefail

REPO="${1:?usage: integrate.sh <your-m1-repo> [target-fork-dir]}"
TARGET="${2:-./jev-ultrafast}"

[ -d "$TARGET/jev_ultrafast" ] || { echo "not a jev-ultrafast fork: $TARGET"; exit 1; }

cd "$TARGET"

# 1. agent.py（替换）
cp "$REPO/agent.py" jev_ultrafast/agent.py

# 2. 7 个新模块
for f in decision_validator policy confidence_gate step_budget runtime_guard logger evaluator; do
    cp "$REPO/$f.py" "jev_ultrafast/$f.py"
done

# 3. decider / prompts
rm -rf jev_ultrafast/decider jev_ultrafast/prompts
cp -r "$REPO/decider" jev_ultrafast/
cp -r "$REPO/prompts" jev_ultrafast/

# 4. m1 / docs / specs
cp -r "$REPO/m1" .
cp -r "$REPO/docs" .
cp -r "$REPO/specs" .

echo "files copied. Now:"
echo "  1) apply model.py bridge patch (see integrate.md)"
echo "  2) apply m1/run_tasks.py import patch"
echo "  3) update .env.example"
echo "  4) py_compile check"
