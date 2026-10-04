param(
    [string]$Version = "",
    [int]$TaskDelay = 3,
    [string]$Tasks = "m1\tasks-laya-subset.jsonl",
    # Decision layer runs in-process (laya_provider SDK), so NO :8000 service is
    # started here -- avoids loading a second copy of the weights into VRAM.
    [string]$LayaModel = "D:\openjev-models\repo\laya-browser\v17s",
    [string]$TextHelper = "groq"
)

# NOTE: keep this file pure ASCII. Windows PowerShell 5.1 reads .ps1 as ANSI
# (GBK on this machine) unless it has a BOM, so non-ASCII comments corrupt parsing.

# ==================================================================
#  CONFIG
# ==================================================================
$Repo         = "C:\Users\Administrator\openjev-ultrafast"
$ChromeExe    = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$ChromeProfile= "C:\chrome-cdp-test"
$PythonJev    = "C:\Users\Administrator\miniconda3\envs\jev\python.exe"

# Laya env (in-process provider, see jev_ultrafast/decider/laya_provider.py)
$LayaEnv = @{
    "DECIDER_MODE"        = "laya"
    "LAYA_DEVICE"         = "cuda"
    "LAYA_BROWSER_MODEL"  = $LayaModel
    "PYTHONUTF8"          = "1"
    "HF_HUB_OFFLINE"      = "1"
    "TORCHDYNAMO_DISABLE" = "1"
}

# Text helper (supplies TYPE_TEXT values). localhost endpoints need no key.
$helperUrl = "https://api.groq.com/openai/v1"; $helperModel = "openai/gpt-oss-120b"; $helperKey = $env:GROQ_API_KEY
if ($TextHelper -eq "deepseek") {
    $helperUrl = "https://api.deepseek.com/v1"; $helperModel = "deepseek-chat"; $helperKey = $env:DEEPSEEK_API_KEY
}
if ($TextHelper -eq "local") {
    $helperUrl = "http://127.0.0.1:11434/v1"; $helperModel = "gemma4:latest"; $helperKey = "local"
}

# ==================================================================
#  HELPERS
# ==================================================================
function Log($msg)  { Write-Host "[$(Get-Date -Format 'HH:mm:ss')] $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "[$(Get-Date -Format 'HH:mm:ss')]   OK  $msg" -ForegroundColor Green }
function Fail($msg) { Write-Host "[$(Get-Date -Format 'HH:mm:ss')]  FAIL $msg" -ForegroundColor Red; throw $msg }

function Wait-Url($url, $maxSec = 60, $intervalSec = 2) {
    for ($i = 0; $i -lt ($maxSec / $intervalSec); $i++) {
        try { Invoke-RestMethod $url -TimeoutSec 1 | Out-Null; return $true }
        catch { Start-Sleep $intervalSec }
    }
    return $false
}

function Set-Env($h) { foreach ($k in $h.Keys) { Set-Item -Path "env:$k" -Value $h[$k] } }

# ==================================================================
#  MAIN
# ==================================================================
if (-not $Version) { $Version = "v" + (Get-Date -Format "MMdd-HHmm") }
$ReportPath = "$Repo\reports\m1-laya-$Version.json"
$LogDir     = "$Repo\logs\m1-laya-$Version"
$exitCode = 0

try {
    Log "=== Laya Runner ($Version) ==="
    Log "  model=$LayaModel"
    Log "  tasks=$Tasks"

    # -- 0. Load .env (GROQ/DEEPSEEK key; without it TYPE_TEXT escalation fails) --
    Log "Step 0: load .env"
    Get-Content "$Repo\.env" -EA SilentlyContinue |
        Where-Object { $_ -match '^\s*[A-Za-z_][A-Za-z0-9_]*\s*=' } |
        ForEach-Object {
            $p = $_.Split('=', 2)
            Set-Item -Path "env:$($p[0].Trim())" -Value $p[1].Trim()
        }
    if ($env:GROQ_API_KEY) { Ok "env loaded (GROQ key present)" } else { Log "  WARN: no GROQ_API_KEY -- TYPE_TEXT will fail" }

    # -- 1. GPU precheck (hard rule: must be < 500MB before a benchmark) --
    $gpuUsed = [int]((nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits) -replace '\s','')
    Log "Step 1: GPU in use = ${gpuUsed}MB"
    if ($gpuUsed -gt 500) { Log "  WARN: >500MB occupied -- another model may be resident" }

    # -- 2. Kill old processes, clean CDP residue --
    Log "Step 2: kill old processes, clean CDP residue"
    Get-Process python -EA SilentlyContinue | Where-Object { $_.Id -ne $PID } | ForEach-Object {
        try {
            $cl = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)" -EA Stop).CommandLine
            if ($cl -match "decider|run_tasks|serve\.py") { Stop-Process -Id $_.Id -Force -EA SilentlyContinue }
        } catch {}
    }
    Get-Process chrome, msedge, chromium -EA SilentlyContinue | Stop-Process -Force -EA SilentlyContinue
    Start-Sleep 3
    Remove-Item -Recurse -Force $ChromeProfile -EA SilentlyContinue
    Remove-Item -Recurse -Force "$env:USERPROFILE\.config\browser-harness" -EA SilentlyContinue
    Ok "old processes killed, CDP state cleared"

    # -- 3. Start Chrome CDP --
    Log "Step 3: start headless CDP Chrome (9222)"
    Start-Process $ChromeExe "--headless=new --remote-debugging-port=9222 --user-data-dir=$ChromeProfile --no-first-run --no-default-browser-check"
    if (-not (Wait-Url "http://127.0.0.1:9222/json/version" 30 1)) { Fail "CDP 9222 not ready after 30s" }
    Ok "CDP ready"

    # -- 4. Set env --
    Log "Step 4: set env"
    Set-Env $LayaEnv
    Set-Env @{
        "TEXT_HELPER_BASE_URL" = $helperUrl
        "TEXT_HELPER_MODEL"    = $helperModel
        "TEXT_HELPER_API_KEY"  = $helperKey
        "HTTPX_PROXY"          = "http://127.0.0.1:2080"
    }
    Ok "DECIDER_MODE=laya, TEXT_HELPER=$helperModel"

    # -- 5. Run benchmark --
    Log "Step 5: run tasks -> $ReportPath"
    Set-Location $Repo
    $start = Get-Date
    & $PythonJev -m m1.run_tasks --tasks $Tasks --log-dir $LogDir --report $ReportPath --task-delay $TaskDelay
    $benchExit = $LASTEXITCODE
    $elapsed = ((Get-Date) - $start).TotalMinutes
    Log "  finished in $([Math]::Round($elapsed, 1)) min (exit $benchExit)"

    # -- 6. Summary --
    Log "Step 6: summary"
    $py = @'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
s = d["summary"]
print("  PASS=%d FAIL=%d ERROR=%d UNKNOWN=%d" % (s["pass"], s["fail"], s["error"], s["unknown"]))
print("  quadrants: %s" % s["quadrants"])
print("  failure_modes: %s" % s["failure_modes"])
print("  acceptance: %s" % d["acceptance"])
print("  --- per task ---")
for r in d["results"]:
    res = r["result"]
    if not isinstance(res, dict):
        print("  %-5s ERROR  %s" % (r["task_id"], str(res.get("error"))[:90]))
        continue
    m = res.get("meta", {})
    print("  %-5s %-6s %-16s steps=%-4s calls=%-4s %sms" % (
        r["task_id"], res.get("result"), res.get("quadrant"),
        m.get("steps"), m.get("model_calls"),
        m.get("decision_lat_p50", m.get("latency_ms", "-"))))
'@
    $py | Out-File -FilePath "$env:TEMP\summary_laya.py" -Encoding ascii
    & $PythonJev "$env:TEMP\summary_laya.py" $ReportPath

    Log "=== DONE: $Version ($([Math]::Round($elapsed,1)) min) ==="
    Log "Report: $ReportPath"

} catch {
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] ERROR: $_" -ForegroundColor Red
    $exitCode = 1
} finally {
    Log "Cleanup: stopping Chrome"
    Get-Process chrome -EA SilentlyContinue | Stop-Process -Force -EA SilentlyContinue
    Start-Sleep 10
    $left = (Get-Process chrome -EA SilentlyContinue | Measure-Object).Count
    Log "Verify 10s later: chrome processes = $left  (must be 0)"
    if ($left -ne 0) { $exitCode = 1 }
}

exit $exitCode