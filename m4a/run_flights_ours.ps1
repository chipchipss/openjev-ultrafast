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

# 默认 typesafe(decider)，但尊重外部传入的 DECIDER_MODE（对比实验用，如 laya_decider）
if (-not $env:DECIDER_MODE) { $env:DECIDER_MODE = "typesafe" }
$env:TYPESAFE_BASE_URL   = "http://127.0.0.1:8000/v1/systemone"
$env:TEXT_HELPER_BASE_URL   = "https://api.groq.com/openai/v1"
$env:TEXT_HELPER_MODEL      = "openai/gpt-oss-120b"
$env:TEXT_HELPER_API_KEY    = $env:GROQ_API_KEY
$env:TEXT_HELPER_MAX_TOKENS = "256"
# 兜底：本地端点（Groq 限额/抖动时自动落这里，无需改代码）。
# 该端点模型默认开思考：256 tokens 会被 reasoning 吃光 → content 为空，
# 故 max_tokens 留余量 + reasoning_effort=none（实测 1.4~2.3s）。
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
$env:M15_ALL_KIND_STALE      = "1"
$env:M15_CYCLE_CUT           = "1"

$pyArgs = @("m4a\run_flights_ours.py", "--task", $Task, "--date", $Date)
if ($Out) { $pyArgs += @("--out", $Out) }
& "C:\Users\Administrator\miniconda3\envs\jev\python.exe" @pyArgs
