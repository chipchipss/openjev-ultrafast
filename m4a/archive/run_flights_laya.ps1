# Comparison wrapper: DECIDER_MODE=laya_decider (laya front-end + decider fallback).
# Only sets the mode; all other env comes from run_flights_ours.ps1.
param(
    [string]$Task = "wikipedia",
    [string]$Out = "reports/wiki-laya.json"
)
$env:DECIDER_MODE = "laya_decider"
& "$PSScriptRoot\run_flights_ours.ps1" -Task $Task -Out $Out
