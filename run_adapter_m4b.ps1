param(
    [double]$MaxHours = 1.0,
    [int]$TaskDelay = 1,
    [int]$TaskTimeoutSec = 420,
    [string]$Tasks = "m1\tasks-laya-19.jsonl",
    # Which trained adapter to mount. m4a/adapter_m4b (M4b R1) is the one whose
    # val@20 was op+target 20/20 but which was NEVER evaluated on M1.
    [string]$Adapter = "C:\Users\Administrator\openjev-ultrafast\m4a\adapter_m4b",
    [string]$ModelId = "decider-2b-m4b",
    [int]$Port = 8000,
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
$Stamp        = Get-Date -Format "MMdd-HHmm"
$Tag          = (Split-Path $Adapter -Leaf) + "-" + $Stamp
$PartDir      = "$Repo\reports\adapter-$Stamp"
$OutReport    = "$Repo\reports\m1-$Tag.json"
$Baseline     = "$Repo\reports\m1-final3.json"
$ProgressLog  = "$Repo\logs\adapter-$Stamp-progress.txt"
$SvcOut       = "$Repo\logs\adapter-$Stamp-svc_out.log"
$SvcErr       = "$Repo\logs\adapter-$Stamp-svc_err.log"

# ==================================================================
#  HELPERS
# ==================================================================
function Log($m)  { $l = "[$(Get-Date -Format 'HH:mm:ss')] $m"; Write-Host $l -ForegroundColor Cyan; Add-Content $ProgressLog $l -Encoding ascii }
function Ok($m)   { Log "   OK  $m" }
function Warn($m) { Log "  WARN $m" }
function Die($m)  { Log "  FAIL $m"; throw $m }
function Set-Env($h) { foreach ($k in $h.Keys) { Set-Item -Path "env:$k" -Value $h[$k] } }

function Cdp-Alive { try { Invoke-RestMethod "http://127.0.0.1:9222/json/version" -TimeoutSec 2 | Out-Null; return $true } catch { return $false } }
function Wait-Cdp($maxSec = 30) { for ($i=0; $i -lt $maxSec; $i++) { if (Cdp-Alive) { return $true }; Start-Sleep 1 }; return $false }
function Start-Chrome {
    Get-Process chrome -EA SilentlyContinue | Stop-Process -Force -EA SilentlyContinue
    Start-Sleep 2
    Remove-Item -Recurse -Force $ChromeProfile -EA SilentlyContinue
    Start-Process $ChromeExe "--headless=new --remote-debugging-port=9222 --user-data-dir=$ChromeProfile --no-first-run --no-default-browser-check"
    return (Wait-Cdp 30)
}
function Svc-Alive { try { Invoke-RestMethod "http://127.0.0.1:$Port/v1/models" -TimeoutSec 3 | Out-Null; return $true } catch { return $false } }
function Wait-Svc($maxSec = 300) { for ($i=0; $i -lt $maxSec/2; $i++) { if (Svc-Alive) { return $true }; Start-Sleep 2 }; return $false }

# A dead model service must abort the run IMMEDIATELY. Left undetected it burns
# ~224s per task (6 retries x ~44s of connection-refused) and every task then
# scores as correct_abandon at steps=0 -- a fabricated result, not a measurement.
function Assert-SvcAlive($svcProc, $where) {
    if ($svcProc -and $svcProc.HasExited) {
        Log "SERVER DEAD at $where (pid $($svcProc.Id), exit $($svcProc.ExitCode))."
        Log "  stdout: $SvcOut"
        Log "  stderr: $SvcErr"
        Log "  Last 20 stdout lines:"
        if (Test-Path $SvcOut) { Get-Content $SvcOut -Tail 20 | ForEach-Object { Log "  | $_" } }
        return $false
    }
    return $true
}

function Test-Report($path) {
    if (-not (Test-Path $path)) { return $false }
    # Must have a real TaskResult AND no decider connection failures -- a report
    # full of "connection refused" is a broken run, not a measurement.
    & $PythonJev -c "import json,sys;d=json.load(open(sys.argv[1],encoding='utf-8'));r=d.get('results') or [];ok=bool(r) and isinstance(r[0].get('result'),dict) and 'connection failed' not in json.dumps(d,ensure_ascii=False);sys.exit(0 if ok else 1)" $path 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Invoke-Task($taskFile, $reportPath, $tid) {
    $so = "$env:TEMP\atask_out.log"; $se = "$env:TEMP\atask_err.log"
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
    Log "============ DECIDER-2B + ADAPTER RUN ============"
    Log "  stamp=$Stamp cap=${MaxHours}h"
    Log "  adapter=$Adapter"
    Log "  model_id=$ModelId port=$Port"

    if (-not (Test-Path $Adapter)) { Die "adapter not found: $Adapter" }

    # -- 0. env --
    Log "Step 0: load .env"
    Get-Content "$Repo\.env" -EA SilentlyContinue |
        Where-Object { $_ -match '^\s*[A-Za-z_][A-Za-z0-9_]*\s*=' } |
        ForEach-Object { $p = $_.Split('=',2); Set-Item -Path "env:$($p[0].Trim())" -Value $p[1].Trim() }

    $helperUrl = "https://api.groq.com/openai/v1"; $helperModel = "openai/gpt-oss-120b"; $helperKey = $env:GROQ_API_KEY
    if ($TextHelper -eq "deepseek") { $helperUrl = "https://api.deepseek.com/v1"; $helperModel="deepseek-chat"; $helperKey=$env:DEEPSEEK_API_KEY }
    if ($TextHelper -eq "local")   { $helperUrl = "http://127.0.0.1:11434/v1"; $helperModel="gemma4:latest"; $helperKey="local" }
    if ($helperKey) { Ok "GROQ key present" } else { Warn "no GROQ_API_KEY" }

    # -- 1. GPU gate --
    $gpu = [int]((nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits) -replace '\s','')
    Log "Step 1: GPU in use = ${gpu}MB (must be <500)"
    if ($gpu -gt 500) { Die "GPU busy (${gpu}MB). Stop the other model first -- hard rule 3.4." }

    # -- 2. clean --
    Log "Step 2: kill python, clean CDP residue"
    Get-Process python -EA SilentlyContinue | Where-Object { $_.Id -ne $PID } | ForEach-Object {
        try { $cl = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)" -EA Stop).CommandLine
              if ($cl -match "decider|run_tasks|serve|uvicorn|jev_service") { Stop-Process -Id $_.Id -Force -EA SilentlyContinue } } catch {}
    }
    Get-Process chrome, msedge, chromium -EA SilentlyContinue | Stop-Process -Force -EA SilentlyContinue
    Start-Sleep 3
    Remove-Item -Recurse -Force "$env:USERPROFILE\.config\browser-harness" -EA SilentlyContinue
    Ok "clean"

    # -- 3. start the adapter server --
    Log "Step 3: start m4a/serve_m4b.py on :$Port (4-bit load takes a while)"
    Set-Env @{
        "M4B_ADAPTER" = $Adapter
        "M4B_MODEL_ID"= $ModelId
        "M4B_PORT"    = "$Port"
        "HF_HOME"     = "D:\openjev-models\hf"
        "HF_HUB_OFFLINE" = "1"
        "TRANSFORMERS_OFFLINE" = "1"
        "TORCHDYNAMO_DISABLE" = "1"
        "PYTHONUTF8"  = "1"
        "USE_TF"       = "0"
    }
    $svcProc = Start-Process -FilePath $PythonJev `
        -ArgumentList @("m4a\serve_m4b.py") `
        -WorkingDirectory $Repo -PassThru -NoNewWindow `
        -RedirectStandardOutput $SvcOut -RedirectStandardError $SvcErr
    Log "  svc pid $($svcProc.Id); waiting for /v1/models (up to 300s)..."
    if (-not (Wait-Svc 300)) {
        Log "  --- svc stderr tail ---"
        if (Test-Path $SvcErr) { Get-Content $SvcErr -Tail 30 | ForEach-Object { Log "  | $_" } }
        Die "adapter server not ready after 300s"
    }
    Ok "server ready"

    # -- 4. Chrome --
    Log "Step 4: start headless CDP Chrome (9222)"
    if (-not (Start-Chrome)) { Die "CDP 9222 not ready" }
    Ok "CDP ready"

    # -- 5. bench env --
    Log "Step 5: set env"
    Set-Env @{
        "DECIDER_MODE"        = "openai"
        "DECIDER_2B_BASE_URL" = "http://127.0.0.1:$Port/v1"
        "DECIDER_2B_MODEL"    = $ModelId
        "DECIDER_2B_API_KEY"  = "local"
        "DECIDER_MAX_TOKENS"  = "256"
        "TEXT_HELPER_BASE_URL"= $helperUrl
        "TEXT_HELPER_MODEL"   = $helperModel
        "TEXT_HELPER_API_KEY" = $helperKey
        "HTTPX_PROXY"         = "http://127.0.0.1:2080"
        "PYTHONUTF8"          = "1"
    }
    Ok "DECIDER_MODE=openai -> 127.0.0.1:$Port/v1 ($ModelId)"

    # -- 6. task loop --
    $lines = @(Get-Content "$Repo\$Tasks" -Encoding UTF8 | Where-Object { $_.Trim() -ne "" })
    Log "Step 6: $($lines.Count) tasks queued"
    $results = @(); $pilotConfirmed = 0; $idx = 0

    foreach ($line in $lines) {
        $idx++
        $tid = ([regex]::Match($line, '"task_id"\s*:\s*"([^"]+)"')).Groups[1].Value
        $isPilot = ($idx -le $PilotCount)
        $reportPath = "$PartDir\$tid.json"
        $taskFile = "$env:TEMP\atask.jsonl"

        # Gate fires AFTER the pilot tasks have actually run: at idx == PilotCount
        # it would fire before task 1 executes, so -PilotCount 1 always aborted.
        if ($idx -eq ($PilotCount + 1) -and $pilotConfirmed -eq 0) {
            Log "PILOT GATE FAILED: 0/$PilotCount valid. Aborting -- see $SvcErr"
            $exitCode = 3; break
        }
        $eh = ((Get-Date) - $started).TotalHours
        if ($eh -gt $MaxHours) { Log "CAP REACHED ($( [Math]::Round($eh,2) )h) -- stopping before $tid"; break }

        if (Test-Report $reportPath) { Log "[$idx/$($lines.Count)] $tid  SKIP (valid report exists)"; continue }

        $phase = if ($isPilot) { "PILOT" } else { "RUN  " }
        Log "[$idx/$($lines.Count)] $tid  $phase start (elapsed $([Math]::Round($eh,2))h)"

        if (-not (Assert-SvcAlive $svcProc "before $tid")) { $exitCode = 4; break }
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
        # Catch a dead model service right here rather than 224s later inside the
        # next task's retry storm.
        if (-not (Assert-SvcAlive $svcProc "after $tid")) { $exitCode = 4; break }
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
    Log "Cleanup: stop server, then Chrome, then orphan python"
    if ($svcProc -and -not $svcProc.HasExited) { Stop-Process -Id $svcProc.Id -Force -EA SilentlyContinue }
    Get-Process python -EA SilentlyContinue | Where-Object { $_.Id -ne $PID } | ForEach-Object {
        try { $cl = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)" -EA Stop).CommandLine
              if ($cl -match "run_tasks|decider|serve|uvicorn|jev_service") { Stop-Process -Id $_.Id -Force -EA SilentlyContinue } } catch {}
    }
    Get-Process chrome -EA SilentlyContinue | Stop-Process -Force -EA SilentlyContinue
    Start-Sleep 7
    $chromeLeft = (Get-Process chrome -EA SilentlyContinue | Measure-Object).Count
    $svcLeft = (Get-Process python -EA SilentlyContinue | Where-Object {
        try { (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)" -EA Stop).CommandLine -match "serve_m4b" } catch { $false } } | Measure-Object).Count
    Log "Verify after cleanup: chrome=$chromeLeft (must be 0), serve_m4b=$svcLeft (must be 0)"
    if ($chromeLeft -ne 0 -or $svcLeft -ne 0) { $exitCode = 1 }
}

exit $exitCode