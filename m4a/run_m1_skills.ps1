# M1 20-task suite on the local decider (TypeSafe mode) + skills layer.
# Env mirrors m4a/run_flights_ours.ps1 (the only working local setup).
# Baseline to compare: reports/m1-skills-v3.json (16/20).
param(
    [string]$Tag = "v8",
    [string]$Tasks = "m1\tasks.jsonl"
)
$ErrorActionPreference = 'Continue'
Set-Location C:\Users\Administrator\openjev-ultrafast

$env:DECIDER_MODE         = "typesafe"
$env:TYPESAFE_BASE_URL    = "http://127.0.0.1:8000/v1/systemone"
$env:TYPESAFE_API_KEY     = "local"
$env:TEXT_HELPER_BASE_URL   = "https://api.groq.com/openai/v1"
$env:TEXT_HELPER_MODEL      = "openai/gpt-oss-120b"
$env:TEXT_HELPER_API_KEY    = $env:GROQ_API_KEY
$env:TEXT_HELPER_MAX_TOKENS = "256"
# 兜底：本地端点（Groq 限额/抖动时自动落这里，无需改代码）。
$env:TEXT_HELPER_FALLBACK_BASE_URL   = "http://127.0.0.1:7863/v1"
$env:TEXT_HELPER_FALLBACK_MODEL      = "cn:glm-5.3-flash"
$env:TEXT_HELPER_FALLBACK_API_KEY    = "81e322066d9fee75e0d283447dc86e27e72b786e7585b501"
$env:TEXT_HELPER_FALLBACK_MAX_TOKENS = "1024"
$env:TEXT_HELPER_FALLBACK_EXTRA_BODY = '{"reasoning_effort":"none"}'
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
