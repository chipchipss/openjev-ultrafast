# One task at a time against the running StartLux wire server (8090).
# Usage: .\scripts\run_one.ps1 -TaskId s005
param(
    [Parameter(Mandatory = $true)][string]$TaskId,
    [int]$SvcPort = 8090
)
$ErrorActionPreference = "Stop"
$Repo = "C:\Users\Administrator\openjev-ultrafast"
$Stamp = Get-Date -Format "MMdd-HHmmss"
$TaskFile = "$env:TEMP\single_$TaskId.jsonl"
$Report   = "$env:TEMP\one_$($TaskId)_$Stamp.json"
$LogDir   = "$env:TEMP\one_$($TaskId)_$Stamp"

# Chrome (same options the runner uses, proxy included)
Get-Process chrome -EA SilentlyContinue | Stop-Process -Force -EA SilentlyContinue
Start-Sleep 2
$px = "--proxy-server=http://127.0.0.1:2080"
Start-Process "C:\Program Files\Google\Chrome\Application\chrome.exe" `
    "--headless=new --remote-debugging-port=9222 --user-data-dir=C:\chrome-cdp-test --no-first-run --no-default-browser-check $px"
foreach ($i in 1..30) {
    Start-Sleep 1
    try { Invoke-RestMethod "http://127.0.0.1:9222/json/version" -TimeoutSec 2 | Out-Null; break } catch {}
}

$env:DECIDER_MODE = "typesafe"
$env:TYPESAFE_BASE_URL = "http://127.0.0.1:$SvcPort/v1/systemone"
$env:TYPESAFE_API_KEY = "local"
$env:HTTPX_PROXY = "http://127.0.0.1:2080"
$env:PYTHONUTF8 = "1"

& "C:\Users\Administrator\miniconda3\envs\jev\python.exe" -m m1.run_tasks `
    --tasks $TaskFile --log-dir $LogDir --report $Report --task-delay 1
if ($LASTEXITCODE -ne 0) { Write-Host "RUN FAILED"; exit 1 }

& "C:\Users\Administrator\miniconda3\envs\jev\python.exe" -c "
import json, sys
d = json.load(open(r'$Report', encoding='utf-8'))
r = (d.get('results') or [{}])[0].get('result', {})
m = r.get('meta', {})
print('=== $TaskId ===')
print('result:', r.get('result'), '| quadrant:', r.get('quadrant'),
      '| steps:', m.get('steps'), '| model_calls:', m.get('model_calls'),
      '| elapsed_ms:', m.get('elapsed_ms'))
fp = (r.get('evidence') or {}).get('final_url', '')
print('final_url:', fp[:100])
"
Get-Process chrome -EA SilentlyContinue | Stop-Process -Force -EA SilentlyContinue
