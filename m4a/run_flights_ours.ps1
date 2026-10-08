# Upstream jev-ultrafast Google Flights task, run on OUR stack (local decider-2b + skills).
# Upstream published: TypeSafe jev-1.13.0 + Mercury, median 7.092 s, 3/3 passed.
# Prereq: decider serve on :8000 (Mapika/decider-2b) + CDP Chrome on 9222.
param(
    [string]$Task = "flights",
    [string]$Out = "",
    [string]$Date = "auto"
)
$ErrorActionPreference = 'Continue'
Set-Location C:\Users\Administrator\openjev-ultrafast
$Repo = "C:\Users\Administrator\openjev-ultrafast"
. "$Repo\scripts\text_helper.ps1"

# 默认 typesafe(decider)，但尊重外部传入的 DECIDER_MODE（对比实验用，如 laya_decider）
if (-not $env:DECIDER_MODE) { $env:DECIDER_MODE = "typesafe" }
$env:TYPESAFE_BASE_URL   = "http://127.0.0.1:8000/v1/systemone"
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
$env:M15_ALL_KIND_STALE      = "1"
$env:M15_CYCLE_CUT           = "1"

$pyArgs = @("m4a\run_flights_ours.py", "--task", $Task, "--date", $Date)
if ($Out) { $pyArgs += @("--out", $Out) }
& "C:\Users\Administrator\miniconda3\envs\jev\python.exe" @pyArgs
