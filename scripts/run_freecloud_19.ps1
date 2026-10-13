# #80 runner: a CLOUD decision model over the 19-task freeze set. ASCII only (PS 5.1 ANSI).
#
# This is NOT the zero-cloud path and it is NOT the L4 freeze anchor.
# run_one.ps1 hard-codes DECIDER_MODE=typesafe against the local StartLux wire (:8090),
# which is what every citable reading in this repo uses. This script exists separately on
# purpose: it points the DECISION layer at an OpenAI-compatible cloud endpoint
# (DECIDER_MODE=openai -> jev_ultrafast/decider/choose_2b.py, which already speaks
# chat + response_format=json_object + validate-and-retry), while the TEXT HELPER stays
# local on :8081. Exactly one variable moves, so a reading here can be attributed.
#
# Hard rule kept: never touch a browser we do not own (chrome-cdp-test via chrome_guard),
# and never fire at a cloud endpoint without a key (fail closed below).
#
# Usage:
#   .\scripts\run_freecloud_19.ps1 -Model openai/gpt-oss-20b
#   .\scripts\run_freecloud_19.ps1 -Model openai/gpt-oss-20b -TasksFile m1\tasks-laya-19.jsonl
#   .\scripts\run_freecloud_19.ps1 -Model allam-2-7b -TaskId s005          # one-row pilot
param(
    [Parameter(Mandatory = $true)][string]$Model,
    [string]$Provider = "groq",
    [string]$TasksFile = "m1\tasks-laya-19.jsonl",
    [string]$TaskId = "",
    [string]$Tag = "",
    [int]$LlamaPort = 8081,          # local Text Helper -- stays local, on purpose
    [int]$TaskDelay = 1
)
$ErrorActionPreference = "Stop"
$Repo = "C:\Users\Administrator\openjev-ultrafast"
$PythonJev = "C:\Users\Administrator\miniconda3\envs\jev\python.exe"

# ---- 1) endpoint: resolve through the ONE table in scripts/text_helper.ps1 -------------
# tests/test_runner_safety.py allows a cloud URL to be spelled out in exactly one file
# (text_helper.ps1) -- that gate is what keeps "no runner defaults to cloud" true.
# This runner is deliberately cloud-only, so it must not grow its own copy of the URLs.
. "$Repo\scripts\text_helper.ps1"
try { $ep = Resolve-CloudEndpoint -Choice $Provider }
catch { Write-Host "REFUSING: $($_.Exception.Message)" -ForegroundColor Red; exit 2 }
$BaseUrl = $ep.Url
$Key = $ep.Key

# ---- 2) task file ---------------------------------------------------------------
$Full = if ([System.IO.Path]::IsPathRooted($TasksFile)) { $TasksFile } else { Join-Path $Repo $TasksFile }
if (-not (Test-Path $Full)) { Write-Host "task file missing: $Full"; exit 2 }
$Stamp = Get-Date -Format "MMdd-HHmmss"
if ($TaskId) {
    # Same fail-closed ambiguity check as run_one.ps1: an id defined in two corpora
    # would silently measure the wrong task.
    $pat = "`"task_id`"\s*:\s*`"$TaskId`""
    $hits = @(Select-String -Path $Full -Pattern $pat -EA SilentlyContinue)
    if ($hits.Count -ne 1) { Write-Host "expected exactly 1 row for $TaskId in $Full, got $($hits.Count)"; exit 2 }
    $RunFile = Join-Path $env:TEMP "freecloud_$TaskId_$Stamp.jsonl"
    $hits[0].Line | Set-Content -Path $RunFile -Encoding UTF8
    $Label = "freecloud-$TaskId"
} else {
    $RunFile = $Full
    $Label = "freecloud-19"
}
if (-not $Tag) {
    # PS method calls need parens: "$Model.Replace(...)" binds to the string expansion and
    # leaks the literal text into the file name -- which then wrote the report into a stray
    # directory named after the model. Sanitize up front instead.
    $Safe = ($Model -replace '[^A-Za-z0-9._-]', '_')
    $Tag = "$Label-$Safe"
}
$Report = "$Repo\reports\$Tag-$Stamp.json"
$LogDir = "$Repo\logs\$Tag-$Stamp"

# ---- 3) owned Chrome (P0: our profile only) -------------------------------------
. "$Repo\scripts\chrome_guard.ps1"
Stop-OwnedChrome
Start-Sleep 2
& "$Repo\scripts\start_owned_chrome.ps1"

# ---- 4) environment: cloud decider + LOCAL text helper --------------------------
$env:DECIDER_MODE = "openai"
$env:DECIDER_2B_BASE_URL = $BaseUrl
$env:DECIDER_2B_MODEL = $Model
$env:DECIDER_2B_API_KEY = $Key
$env:HTTPX_PROXY = "http://127.0.0.1:2080"
$env:PYTHONUTF8 = "1"
$helper = Resolve-TextHelper -Choice "startlux" -LlamaPort $LlamaPort
Assert-TextHelper $helper
$env:TEXT_HELPER_BASE_URL = $helper.Url
$env:TEXT_HELPER_MODEL = $helper.Model
$env:TEXT_HELPER_API_KEY = $helper.Key
$env:TEXT_HELPER_MAX_TOKENS = "128"
$env:TEXT_HELPER_MAX_RETRIES = "2"
$env:BU_CDP_URL = "http://127.0.0.1:9222"

Write-Host ""
Write-Host "=== CLOUD DECIDER RUN (not zero-cloud, not the L4 freeze anchor) ===" -ForegroundColor Yellow
Write-Host "  decision layer : $env:DECIDER_MODE -> $BaseUrl  model=$Model"
Write-Host "  text helper    : LOCAL $env:TEXT_HELPER_BASE_URL ($env:TEXT_HELPER_MODEL)  <- one variable moves"
Write-Host "  tasks          : $RunFile"
Write-Host "  report / logs  : $Report"
Write-Host ""

& $PythonJev -X utf8 -m m1.run_tasks --tasks $RunFile --log-dir $LogDir --report $Report --task-delay $TaskDelay
$code = $LASTEXITCODE
Write-Host "report: $Report"
Write-Host ("verdict: " + $(if ($code -eq 0) { "ran" } else { "exit $code (no report => BLOCKED, not a fail)" }))
exit $code
