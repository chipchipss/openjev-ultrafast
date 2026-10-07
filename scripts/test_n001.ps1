# One task n001 single validation against StartLux wire (overnight run).
$ErrorActionPreference = "Continue"
$Repo = "C:\Users\Administrator\openjev-ultrafast"
$Stamp = Get-Date -Format "MMdd-HHmmss"
$TaskFile = "$env:TEMP\single_n001.jsonl"
$Report   = "$env:TEMP\one_n001_$Stamp.json"
$LogDir   = "$env:TEMP\one_n001_$Stamp"

# write the single-task file (no BOM - run_tasks.jsonl parser rejects UTF-8 BOM)
[IO.File]::WriteAllText($TaskFile, '{"task_id":"n001","domain":"www.python.org","category":"navigate","goal":"Open the Python documentation section from the top navigation.","budget":{"steps":10},"success_assertion":{"type":"all_of","clauses":[{"type":"url_matches","pattern":"docs\\.python\\.org"}]}}')

Get-CimInstance Win32_Process -Filter "Name = 'chrome.exe'" | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep 2
Start-Process "C:\Program Files\Google\Chrome\Application\chrome.exe" "--headless=new --remote-debugging-port=9222 --user-data-dir=C:\chrome-cdp-test --no-first-run --proxy-server=http://127.0.0.1:2080"
Start-Sleep 5

$env:DECIDER_MODE = "typesafe"
$env:TYPESAFE_BASE_URL = "http://127.0.0.1:8090/v1/systemone"
$env:TYPESAFE_API_KEY = "local"
$env:HTTPX_PROXY = "http://127.0.0.1:2080"
$env:PYTHONUTF8 = "1"

& "C:\Users\Administrator\miniconda3\envs\jev\python.exe" -m m1.run_tasks `
    --tasks $TaskFile --log-dir $LogDir --report $Report --task-delay 1

& "C:\Users\Administrator\miniconda3\envs\jev\python.exe" -c "
import json
d = json.load(open(r'$Report', encoding='utf-8'))
r = (d.get('results') or [{}])[0].get('result', {})
m = r.get('meta', {})
print('=== n001 single-task ===')
print('result:', r.get('result'), '| quadrant:', r.get('quadrant'), '| steps:', m.get('steps'), '| elapsed_ms:', m.get('elapsed_ms'))
print('final_url:', (r.get('evidence') or {}).get('final_url', ''))
"
Get-CimInstance Win32_Process -Filter "Name = 'chrome.exe'" | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
