# One task or one task file against the running StartLux wire server (8090).
# Usage: .\scripts\run_one.ps1 -TaskId s005
#        .\scripts\run_one.ps1 -TasksFile m2\tasks_real.jsonl -Tag real-1007-x
param(
    [string]$TaskId,
    [string]$TasksFile,
    [string]$Tag = "adhoc",
    [int]$SvcPort = 8090
)
$ErrorActionPreference = "Stop"
if (-not $TaskId -and -not $TasksFile) { Write-Host "need -TaskId or -TasksFile"; exit 2 }
$Repo = "C:\Users\Administrator\openjev-ultrafast"
$Stamp = Get-Date -Format "MMdd-HHmmss"
if ($TaskId) {
    $TaskFile = "$env:TEMP\single_$TaskId.jsonl"
    # Single-task readings must be citable from the docs (纪律⑤: 数字要能对到
    # reports/*.json), but this branch used to drop them in %TEMP%, where they
    # vanish on the next disk cleanup.
    $Report   = "$Repo\reports\one-$($TaskId)-$Stamp.json"
    $LogDir   = "$Repo\logs\one-$($TaskId)-$Stamp"
    $Label    = $TaskId
    # Extract the single line ourselves: the caller had to pre-build this file
    # before, and a stale one silently measures the wrong task.
    $src = Get-ChildItem -Path @((Join-Path $Repo "m1"), (Join-Path $Repo "m2")) `
            -Filter "tasks*.jsonl" -EA SilentlyContinue |
        ForEach-Object { Select-String -Path $_.FullName -Pattern "`"task_id`":`"$TaskId`"" -EA SilentlyContinue } |
        Select-Object -First 1
    if ($src) { $src.Line | Set-Content -Path $TaskFile -Encoding UTF8 }
    elseif (-not (Test-Path $TaskFile)) { Write-Host "no task $TaskId found and no $TaskFile"; exit 2 }
} else {
    $TaskFile = if ([System.IO.Path]::IsPathRooted($TasksFile)) { $TasksFile } else { Join-Path $Repo $TasksFile }
    $Report   = "$Repo\reports\$Tag-$Stamp.json"
    $LogDir   = "$Repo\logs\$Tag-$Stamp"
    $Label    = $Tag
}

# Hard rule: never touch the user's own browser. A bare `Get-Process chrome |
# Stop-Process` closes everything on the box; only our chrome-cdp-test profile
# is ours to kill (same guard as run_baseline_19.ps1 / run_demo.ps1).
function Stop-CdpChrome {
    Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" -EA SilentlyContinue |
        Where-Object { $_.CommandLine -like "*chrome-cdp-test*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -EA SilentlyContinue }
}

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
