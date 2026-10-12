# One task or one task file against the running StartLux wire server (8090).
# Usage: .\scripts\run_one.ps1 -TaskId s005
#        .\scripts\run_one.ps1 -TasksFile m2\tasks_real.jsonl -Tag real-1007-x
param(
    [string]$TaskId,
    [string]$TasksFile,
    [string]$Tag = "adhoc",
    [int]$SvcPort = 8090,
    # llama-server behind the StartLux wire. Same stack, same GGUF: it is the
    # Text Helper (see below), so nothing leaves the box.
    [int]$LlamaPort = 8081
)
$ErrorActionPreference = "Stop"
if (-not $TaskId -and -not $TasksFile) { Write-Host "need -TaskId or -TasksFile"; exit 2 }
$Repo = "C:\Users\Administrator\openjev-ultrafast"
$Stamp = Get-Date -Format "MMdd-HHmmss"
if ($TaskId) {
    $TaskFile = "$env:TEMP\single_$TaskId.jsonl"
    # Single-task readings must be citable from the docs (rule 5: every number in
    # a doc has to map to a reports/*.json), but this branch used to drop them in
    # %TEMP%, where they vanish on the next disk cleanup.
    $Report   = "$Repo\reports\one-$($TaskId)-$Stamp.json"
    $LogDir   = "$Repo\logs\one-$($TaskId)-$Stamp"
    $Label    = $TaskId
    # Extract the single line ourselves: the caller had to pre-build this file
    # before, and a stale one silently measures the wrong task.
    # Whitespace-tolerant pattern: m2/tasks_real.jsonl is written with json.dumps
    # default separators ("task_id": "r113") while m1/tasks.jsonl is compact; the
    # old exact match only covered the compact form, so no real-web task could run.
    #
    # Fail closed on AMBIGUOUS ids. Found 2026-10-11: `-TaskId r152` was defined both by
    # m2/tasks_real.jsonl (its reserve row) and m2/tasks_real_100.jsonl (the new 50), and
    # `Select-Object -First 1` silently took whichever file the directory walk hit first --
    # a single-task reading that measures the wrong task. Either pass -TasksFile, or the id
    # must have exactly one definition in the repo.
    # (Keep this file ASCII-only in comments: Windows PowerShell 5.1 reads a BOM-less file
    # as ANSI, and a mangled multi-byte byte that happens to be 0x60 is a line continuation
    # -- it would swallow the next line into a comment.)
    $pat = "`"task_id`"\s*:\s*`"$TaskId`""
    if ($TasksFile) {
        $roots = @($(if ([System.IO.Path]::IsPathRooted($TasksFile)) { $TasksFile } else { Join-Path $Repo $TasksFile }))
    } else {
        $roots = @(Get-ChildItem -Path @((Join-Path $Repo "m1"), (Join-Path $Repo "m2")) `
                    -Filter "tasks*.jsonl" -EA SilentlyContinue | ForEach-Object { $_.FullName })
    }
    $hits = @($roots | ForEach-Object {
        Select-String -Path $_ -Pattern $pat -EA SilentlyContinue
    })
    $hitFiles = @($hits | ForEach-Object { $_.Path } | Sort-Object -Unique)
    if ($hits.Count -eq 0) { Write-Host "no task $TaskId found in $(if ($TasksFile) { $TasksFile } else { 'm1/ + m2/tasks*.jsonl' })"; exit 2 }
    if ($hitFiles.Count -gt 1) {
        Write-Host "task id $TaskId is defined in $($hitFiles.Count) files -- refusing to guess which one you meant:" -ForegroundColor Red
        $hitFiles | ForEach-Object { Write-Host "    $_" }
        Write-Host "pass -TasksFile <file> to pick one explicitly."
        exit 2
    }
    $src = $hits[0]
    if ($src) { $src.Line | Set-Content -Path $TaskFile -Encoding UTF8 }
    elseif (-not (Test-Path $TaskFile)) { Write-Host "no task $TaskId found and no $TaskFile"; exit 2 }
} else {
    $TaskFile = if ([System.IO.Path]::IsPathRooted($TasksFile)) { $TasksFile } else { Join-Path $Repo $TasksFile }
    $Report   = "$Repo\reports\$Tag-$Stamp.json"
    $LogDir   = "$Repo\logs\$Tag-$Stamp"
    $Label    = $Tag
}

# Hard rule: never touch the user's own browser. The predicate for "ours" lives in exactly one
# file (scripts/chrome_guard.ps1) -- this used to be a fourth copy of it, kept in sync by comments.
. "$Repo\scripts\chrome_guard.ps1"
function Stop-CdpChrome { Stop-OwnedChrome }

# Chrome (same options the runner uses, proxy included)
Stop-CdpChrome
Start-Sleep 2
$px = "--proxy-server=http://127.0.0.1:2080"
Start-Process "C:\Program Files\Google\Chrome\Application\chrome.exe" `
    "--headless=new --remote-debugging-port=9222 --user-data-dir=C:\chrome-cdp-test --no-first-run --no-default-browser-check $px"
foreach ($i in 1..30) {
    Start-Sleep 1
    try { Invoke-RestMethod "http://127.0.0.1:9222/json/version" -TimeoutSec 2 | Out-Null; break } catch {}
}
# Port 9222 answered is not proof it answered with OUR browser: if a foreign
# Chrome already holds the port, ours exits on the bind and the harness would
# silently drive someone else's browser. Ours must be running.
$mine = @(Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" -EA SilentlyContinue |
            Where-Object { $_.CommandLine -like "*chrome-cdp-test*" })
if ($mine.Count -eq 0) { Write-Host "CDP chrome (chrome-cdp-test) is not running -- port 9222 belongs to another browser"; exit 1 }

$env:DECIDER_MODE = "typesafe"
$env:TYPESAFE_BASE_URL = "http://127.0.0.1:$SvcPort/v1/systemone"
$env:TYPESAFE_API_KEY = "local"
$env:HTTPX_PROXY = "http://127.0.0.1:2080"
$env:PYTHONUTF8 = "1"

# Text Helper -- the value a model-proposed TYPE_TEXT asks to type. This script
# used to set none of the TEXT_HELPER_* vars, so every such decision died inside
# field_text() and agent.py blocked the run after 3 in a row (helper_fail_run):
# r119 lost 3 model calls and 0 steps, twice in a row (b7 and the post-Fix-E
# single). The StartLux llama-server on :8081 serves it from the GGUF that is
# already resident -- the same one model the wire uses, so nothing new starts
# and nothing leaves the box (hard rule: exactly one resident model, zero cloud).
# A dead helper stops the run instead of measuring a silently crippled agent;
# the endpoint itself comes from scripts/text_helper.ps1, so no runner picks one.
. "$Repo\scripts\text_helper.ps1"
$helper = Resolve-TextHelper -Choice "startlux" -LlamaPort $LlamaPort
Assert-TextHelper $helper
$env:TEXT_HELPER_BASE_URL = $helper.Url
$env:TEXT_HELPER_MODEL = $helper.Model
$env:TEXT_HELPER_API_KEY = $helper.Key
$env:TEXT_HELPER_MAX_TOKENS = "128"
$env:TEXT_HELPER_MAX_RETRIES = "2"
# Pin the harness to the chrome-cdp-test instance this script just started; unset,
# browser_harness scans Chrome's default profile first and can drive the user's own
# browser (jev_ultrafast/browser.py owns the check).
$env:BU_CDP_URL = "http://127.0.0.1:9222"
Write-Host "text helper: llama-server :$LlamaPort (local)"

& "C:\Users\Administrator\miniconda3\envs\jev\python.exe" -m m1.run_tasks `
    --tasks $TaskFile --log-dir $LogDir --report $Report --task-delay 1
if ($LASTEXITCODE -ne 0) { Write-Host "RUN FAILED"; exit 1 }

& "C:\Users\Administrator\miniconda3\envs\jev\python.exe" -c "
import json
d = json.load(open(r'$Report', encoding='utf-8'))
s = d.get('summary', {})
print('=== $Label === pass', s.get('pass'), '/', s.get('total'),
      '| fp', s.get('false_positive'), '|', s.get('quadrants'))
api = 0
for r in d.get('results', []):
    t = r.get('result')
    if isinstance(t, str) or t is None:
        print('   ', r.get('task_id'), 'ERROR', t); continue
    m = t.get('meta', {}); api += m.get('api_calls', 0) or 0
    e = t.get('evidence') or {}
    print('   ', t['task_id'], t['result'], t.get('quadrant'), t.get('failure_mode'),
          '| steps', m.get('steps'), '| model', m.get('model_calls'),
          '|', (e.get('final_url') or '')[:80])
print('api_calls total:', api)
print('report:', r'$Report')
"
Stop-CdpChrome
Start-Sleep 2
$all = @(Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" -EA SilentlyContinue)
$cdp = @($all | Where-Object { $_.CommandLine -like "*chrome-cdp-test*" })
Write-Host "verify: cdp-chrome=$($cdp.Count) (must be 0), non-cdp chrome left=$($all.Count - $cdp.Count) (this script never targets those)"
