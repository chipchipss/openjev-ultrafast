# M1 20-task suite on the local decider (TypeSafe mode) + skills layer.
# Env mirrors m4a/run_flights_ours.ps1 (the only working local setup).
# Baseline to compare: reports/m1-skills-v3.json (16/20).
param(
    [string]$Tag = "v8",
    [string]$Tasks = "m1\tasks.jsonl"
)
$ErrorActionPreference = 'Continue'
Set-Location C:\Users\Administrator\openjev-ultrafast
$Repo = "C:\Users\Administrator\openjev-ultrafast"
. "$Repo\scripts\text_helper.ps1"

$env:DECIDER_MODE         = "typesafe"
$env:TYPESAFE_BASE_URL    = "http://127.0.0.1:8000/v1/systemone"
$env:TYPESAFE_API_KEY     = "local"
# Zero-cloud hard line (2026-10-08): this runner used to reach for Groq by
# default, so a bare invocation sent every TYPE_TEXT value to a cloud model
# while the reports kept api_calls=0 -- that counter only counts the teacher
# path. The endpoint has to be named; startlux and local are on-box, groq and
# deepseek are CLOUD and break the rule (see scripts/text_helper.ps1).
$helper = Resolve-TextHelper -Choice $env:JEV_TEXT_HELPER
Assert-TextHelper $helper
$env:TEXT_HELPER_BASE_URL = $helper.Url
$env:TEXT_HELPER_MODEL    = $helper.Model
$env:TEXT_HELPER_API_KEY  = $helper.Key
$env:TEXT_HELPER_MAX_TOKENS = "256"
# Proxy autodetect: if :2080 is down, do NOT set HTTPX_PROXY -- an explicit
# proxy also routes the local services (decider :8000 / helper :7863) and
# everything fails. Without it the helper falls back to the local endpoint.
$proxyUp = (Test-NetConnection -ComputerName 127.0.0.1 -Port 2080 -WarningAction SilentlyContinue).TcpTestSucceeded
if ($proxyUp) {
    $env:HTTPX_PROXY = "http://127.0.0.1:2080"
} else {
    Remove-Item Env:HTTPX_PROXY -ErrorAction SilentlyContinue
    Write-Host "proxy :2080 down -> HTTPX_PROXY unset (helper will use local fallback)"
}
$env:PYTHONUTF8             = "1"
$env:M15_ALL_KIND_STALE   = "1"
$env:M15_CYCLE_CUT        = "1"

& "C:\Users\Administrator\miniconda3\envs\jev\python.exe" -m m1.run_tasks `
    --tasks $Tasks `
    --log-dir "logs\m1-skills-$Tag" `
    --report "reports\m1-skills-$Tag.json" `
    --task-delay 5
