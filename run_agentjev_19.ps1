param(
    [double]$MaxHours = 1.0,
    [int]$TaskDelay = 1,
    [int]$TaskTimeoutSec = 420,
    [string]$Tasks = "m1\tasks-laya-19.jsonl",
    # Two wrapped checkpoints exist; agentjev.pt is the newest (2026-10-04).
    [string]$Checkpoint = "D:\openjev-models\repo\agent-jev\agentjev.pt",
    [string]$JevRepo = "C:\Users\Administrator\AppData\Local\Temp\agent-jev-main",
    [string]$BaseModel = "Qwen/Qwen3-0.6B",
    [int]$Port = 8149,
    [string]$TextHelper = "groq",
    [int]$PilotCount = 2
)

# NOTE: pure ASCII on purpose -- PowerShell 5.1 reads .ps1 as ANSI (GBK) without a BOM.

# ==================================================================
#  CONFIG
# ==================================================================
$Repo         = "C:\Users\Administrator\openjev-ultrafast"
$ChromeExe    = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$ChromeProfile= "C:\chrome-cdp-test"
$PythonJev    = "C:\Users\Administrator\miniconda3\envs\jev\python.exe"
$Temperatures = "D:\openjev-models\repo\agent-jev\temperatures.json"
$HfHome       = "D:\openjev-models\hf"
$Stamp        = Get-Date -Format "MMdd-HHmm"
$PartDir      = "$Repo\reports\agentjev-$Stamp"
$OutReport    = "$Repo\reports\m1-agentjev-$Stamp.json"
$Baseline     = "$Repo\reports\m1-final3.json"
$ProgressLog  = "$Repo\logs\agentjev-$Stamp-progress.txt"
$SvcOut       = "$Repo\logs\agentjev-$Stamp-svc_out.log"
$SvcErr       = "$Repo\logs\agentjev-$Stamp-svc_err.log"

# ==================================================================
#  HELPERS
# ==================================================================
function Log($m)  { $l = "[$(Get-Date -Format 'HH:mm:ss')] $m"; Write-Host $l -ForegroundColor Cyan; Add-Content $ProgressLog $l -Encoding ascii }
function Ok($m)   { Log "   OK  $m" }
function Warn($m) { Log "  WARN $m" }
function Die($m)  { Log "  FAIL $m"; throw $m }
function Set-Env($h) { foreach ($k in $h.Keys) { Set-Item -Path "env:$k" -Value $h[$k] } }

function Cdp-Alive {
    try { Invoke-RestMethod "http://127.0.0.1:9222/json/version" -TimeoutSec 2 | Out-Null; return $true } catch { return $false }
}
function Wait-Cdp($maxSec = 30) { for ($i=0; $i -lt $maxSec; $i++) { if (Cdp-Alive) { return $true }; Start-Sleep 1 }; return $false }
function Start-Chrome {
    Get-Process chrome -EA SilentlyContinue | Stop-Process -Force -EA SilentlyContinue
    Start-Sleep 2
    Remove-Item -Recurse -Force $ChromeProfile -EA SilentlyContinue
    Start-Process $ChromeExe "--headless=new --remote-debugging-port=9222 --user-data-dir=$ChromeProfile --no-first-run --no-default-browser-check"
    return (Wait-Cdp 30)
}
function Svc-Alive {
    try { $r = Invoke-RestMethod "http://127.0.0.1:$Port/health" -TimeoutSec 3; return ($r.status -eq "ready") } catch { return $false }
}
function Wait-Svc($maxSec = 180) { for ($i=0; $i -lt $maxSec; $i++) { if (Svc-Alive) { return $true }; Start-Sleep 2 }; return $false }

function Test-Report($path) {
    if (-not (Test-Path $path)) { return $false }
    & $PythonJev -c "import json,sys;d=json.load(open(sys.argv[1],encoding='utf-8'));r=d.get('results') or [];sys.exit(0 if r and isinstance(r[0].get('result'),dict) else 1)" $path 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Invoke-Task($taskFile, $reportPath, $tid) {
    $so = "$env:TEMP\ajtask_out.log"; $se = "$env:TEMP\ajtask_err.log"
    Remove-Item $so, $se -EA SilentlyContinue
    $p = Start-Process -FilePath $PythonJev `
        -ArgumentList @("-m","m1.run_tasks","--tasks",$taskFile,"--log-dir","$PartDir\logs\$tid","--report",$reportPath,"--task-delay","$TaskDelay") `
        -WorkingDirectory $Repo -PassThru -NoNewWindow -RedirectStandardOutput $so -RedirectStandardError $se
    $p | Wait-Process -Timeout $TaskTimeoutSec -EA SilentlyContinue
    if (-not $p.HasExited) {
        Warn "task exceeded ${TaskTimeoutSec}s -- killing pid $($p.Id)"
        Stop-Process -Id $p.Id -Force -EA SilentlyContinue; Start-Sleep 3; return $false
    }
    return $true
}

# ==================================================================
#  MAIN
# ==================================================================
$exitCode = 0
$svcProc = $null
$started = Get-Date
New-Item -ItemType Directory -Force -Path $PartDir, "$PartDir\logs", "$Repo\logs" | Out-Null
Set-Content $ProgressLog "" -Encoding ascii

try {
    Log "============ AGENT-JEV 0.6B RUN ============"
    Log "  stamp=$Stamp cap=${MaxHours}h ckpt=$Checkpoint"

    # -- 0. env --
    Log "Step 0: load .env"
    Get-Content "$Repo\.env" -EA SilentlyContinue |
        Where-Object { $_ -match '^\s*[A-Za-z_][A-Za-z0-9_]*\s*=' } |
        ForEach-Object { $p = $_.Split('=',2); Set-Item -Path "env:$($p[0].Trim())" -Value $p[1].Trim() }

    $helperUrl = "https://api.groq.com/openai/v1"; $helperModel = "openai/gpt-oss-120b"; $helperKey = $env:GROQ_API_KEY
    if ($TextHelper -eq "deepseek") { $helperUrl = "https://api.deepseek.com/v1"; $helperModel="deepseek-chat"; $helperKey=$env:DEEPSEEK_API_KEY }
    if ($TextHelper -eq "local")   { $helperUrl = "http://127.0.0.1:11434/v1"; $helperModel="gemma4:latest"; $helperKey="local" }
    if ($helperKey) { Ok "GROQ key present" } else { Warn "no GROQ_API_KEY" }

    if (-not (Test-Path $Checkpoint)) { Die "checkpoint not found: $Checkpoint" }
    if (-not (Test-Path "$JevRepo\jev_service\server.py")) { Die "jev_service not found under $JevRepo" }

    # -- 1. GPU precheck: this run loads ONE service and nothing else --
    $gpu = [int]((nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits) -replace '\s','')
    Log "Step 1: GPU in use = ${gpu}MB (must be <500; no other model may be resident)"
    if ($gpu -gt 500) { Die "GPU busy (${gpu}MB). Stop the other model first -- hard rule 3.4 forbids two model services." }

    # -- 2. clean --
    Log "Step 2: kill python, clean CDP residue"
    Get-Process python -EA SilentlyContinue | Where-Object { $_.Id -ne $PID } | ForEach-Object {
        try { $cl = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)" -EA Stop).CommandLine
              if ($cl -match "decider|run_tasks|serve\.py|uvicorn|jev_service") { Stop-Process -Id $_.Id -Force -EA SilentlyContinue } } catch {}
    }
    Get-Process chrome, msedge, chromium -EA SilentlyContinue | Stop-Process -Force -EA SilentlyContinue
    Start-Sleep 3
    Remove-Item -Recurse -Force "$env:USERPROFILE\.config\browser-harness" -EA SilentlyContinue
    Ok "clean"

    # -- 3. start the decision service on :8149 --
    Log "Step 3: start jev_service on :$Port"
    Set-Env @{
        "HF_HOME" = $HfHome; "HF_HUB_OFFLINE" = "1"; "TORCHDYNAMO_DISABLE" = "1"
        "PYTHONUTF8" = "1"; "USE_TF" = "0"
    }
    $svcProc = Start-Process -FilePath $PythonJev `
        -ArgumentList @("-m","jev_service.server","--checkpoint",$Checkpoint,"--model-path",$BaseModel,
                        "--temperatures",$Temperatures,"--port","$Port","--device","cuda:0") `
        -WorkingDirectory $JevRepo -PassThru -NoNewWindow `
        -RedirectStandardOutput $SvcOut -RedirectStandardError $SvcErr
    Log "  svc pid $($svcProc.Id); waiting for /health (FP32 load can take a while)..."
    if (-not (Wait-Svc 240)) {
        Log "  --- svc stderr tail ---"
        if (Test-Path $SvcErr) { Get-Content $SvcErr -Tail 25 | ForEach-Object { Log "  | $_" } }
        Die "jev_service not ready after 240s"
    }
    Ok "service ready"

    # -- 4. Chrome --
    Log "Step 4: start headless CDP Chrome (9222)"
    if (-not (Start-Chrome)) { Die "CDP 9222 not ready" }
    Ok "CDP ready"

    # -- 5. bench env --
    Log "Step 5: set env"
    Set-Env @{
        "DECIDER_MODE" = "agentjev"
        "AGENTJEV_URL" = "http://127.0.0.1:$Port"
        "TEXT_HELPER_BASE_URL" = $helperUrl
        "TEXT_HELPER_MODEL"    = $helperModel
        "TEXT_HELPER_API_KEY"  = $helperKey
        "HTTPX_PROXY"          = "http://127.0.0.1:2080"
        "PYTHONUTF8"           = "1"
    }
    Ok "DECIDER_MODE=agentjev ->127.0.0.1:$Port"

    # -- 6. task loop --
    $lines = @(Get-Content "$Repo\$Tasks" -Encoding UTF8 | Where-Object { $_.Trim() -ne "" })
    Log "Step 6: $($lines.Count) tasks queued"
    $results = @(); $pilotConfirmed = 0; $idx = 0

    foreach ($line in $lines) {
        $idx++
        $tid = ([regex]::Match($line, '"task_id"\s*:\s*"([^"]+)"')).Groups[1].Value
        $isPilot = ($idx -le $PilotCount)
        $reportPath = "$PartDir\$tid.json"
        $taskFile = "$env:TEMP\ajtask.jsonl"

        # Gate fires AFTER the pilot tasks have actually run: at idx == PilotCount
        # it would fire before task 1 executes, so -PilotCount 1 always aborted.
        if ($idx -eq ($PilotCount + 1) -and $pilotConfirmed -eq 0) {
            Log "PILOT GATE FAILED: 0/$PilotCount valid. Aborting -- check $ProgressLog and $SvcErr"
            $exitCode = 3; break
        }
        $eh = ((Get-Date) - $started).TotalHours
        if ($eh -gt $MaxHours) { Log "CAP REACHED ($( [Math]::Round($eh,2) )h) -- stopping before $tid"; break }

        if (Test-Report $reportPath) { Log "[$idx/$($lines.Count)] $tid  SKIP (valid report exists)"; continue }

        $phase = if ($isPilot) { "PILOT" } else { "RUN  " }
        Log "[$idx/$($lines.Count)] $tid  $phase start (elapsed $([Math]::Round($eh,2))h)"

        if (-not (Svc-Alive)) { Warn "service down before $tid -- restarting"; $svcProc = $null; break }
        if (-not (Cdp-Alive))  { Warn "CDP down before $tid -- restarting Chrome"; if (-not (Start-Chrome)) { Warn "Chrome restart failed"; continue } }

        Set-Content -Path $taskFile -Value $line -Encoding ascii
        $ok = Invoke-Task $taskFile $reportPath $tid

        if (-not (Test-Report $reportPath)) {
            if ($ok) {
                Warn "$tid no TaskResult (attempt 1) -- refreshing Chrome, retry once"
                if (Start-Chrome) { Set-Content $taskFile $line -Encoding ascii; [void](Invoke-Task $taskFile $reportPath $tid) }
            } else { Warn "$tid timed out and was killed; no retry after a hang" }
        }

        if (Test-Report $reportPath) {
            $results += $tid; if ($isPilot) { $pilotConfirmed++ }
            Ok "$tid done ($($results.Count) confirmed)"
        } else { Warn "$tid UNRESOLVED after retry -- harness, not model" }
        Start-Sleep 2
    }

    # -- 7. merge --
    Log "Step 7: merge -> $OutReport"
    & $PythonJev -m m1.merge_reports $PartDir $Baseline $OutReport
    Log "=== DONE: $($results.Count)/$($lines.Count) confirmed, $([Math]::Round(((Get-Date)-$started).TotalMinutes,1)) min ==="
    Log "Report: $OutReport"

} catch {
    Log "ERROR: $_"
    $exitCode = 1
} finally {
    Log "Cleanup: stop service, then Chrome, then orphan python"
    if ($svcProc -and -not $svcProc.HasExited) { Stop-Process -Id $svcProc.Id -Force -EA SilentlyContinue }
    Get-Process python -EA SilentlyContinue | Where-Object { $_.Id -ne $PID } | ForEach-Object {
        try { $cl = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)" -EA Stop).CommandLine
              if ($cl -match "run_tasks|decider|serve\.py|uvicorn|jev_service|browser_harness") { Stop-Process -Id $_.Id -Force -EA SilentlyContinue } } catch {}
    }
    Get-Process chrome -EA SilentlyContinue | Stop-Process -Force -EA SilentlyContinue
    Start-Sleep 7
    $chromeLeft = (Get-Process chrome -EA SilentlyContinue | Measure-Object).Count
    $pyLeft = (Get-Process python -EA SilentlyContinue | Where-Object { $_.Id -ne $PID } | Measure-Object).Count
    $svcLeft = (Get-Process python -EA SilentlyContinue | Where-Object {
        try { (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)" -EA Stop).CommandLine -match "jev_service" } catch { $false } } | Measure-Object).Count
    Log "Verify after cleanup: chrome=$chromeLeft (must be 0), stray python=$pyLeft, jev_service=$svcLeft (must be 0)"
    if ($chromeLeft -ne 0 -or $svcLeft -ne 0) { $exitCode = 1 }
}

exit $exitCode