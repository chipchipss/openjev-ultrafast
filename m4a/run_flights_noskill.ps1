# 对照实验用：同 harness/同 goal，关闭技能层（M16_SKILLS=0）→ 每个决策都过 decider。
# 仅用于「全模型决策 vs 技能优先」同口径对比，不参与正式跑分。
param([string]$Out = "reports/flights-noskill.json")
$env:M16_SKILLS = "0"
& "$PSScriptRoot\run_flights_ours.ps1" -Task flights -Date auto -Out $Out
