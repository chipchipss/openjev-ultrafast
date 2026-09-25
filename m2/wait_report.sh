#!/bin/bash
# 5.4 完成标记：reports/m2.json 一落盘 → 五判据摘要 + 影子统计写 m2_ready.txt
# DE 侧自持（setsid），不依赖发起方会话/ssh 存活。
cd /root/jev-ultrafast || exit 1
[ -f reports/m2_ready.txt ] && exit 0
until [ -f reports/m2.json ]; do sleep 60; done
sleep 5
{
  .venv/bin/python m2/report_view.py reports/m2.json
  echo "== shadow =="
  SH=$(find logs/m2 -name "*.jsonl" -exec grep -h teacher_shadow {} +)
  echo "events=$(echo "$SH" | grep -c '^')"
  echo "agree=$(echo "$SH" | grep -c 'agree.: true')"
  echo "failed=$(find logs/m2 -name "*.jsonl" -exec grep -h 'shadow.*status.*failed' {} + 2>/dev/null | wc -l)"
} > reports/m2_ready.txt 2>&1
