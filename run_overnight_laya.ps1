param(
    # Hard wall-clock cap for the whole run. When exceeded, the loop stops cleanly
    # (hard rule docs/00-project-plan.md 3.4: a background job must be stoppable).
    [double]$MaxHours = 4.5,
    [int]$TaskDelay = 1,
    # Per-task wall clock. A hung task is killed rather than stalling the night.
    [int]$TaskTimeoutSec = 420,
    [string]$Tasks = "m1\tasks-laya-19.jsonl",
    [string]$LayaModel = "D:\openjev-models\repo\laya-browser\v17s",
    [string]$TextHelper = "groq",
    [int]$PilotCount = 2
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
$Stamp        = Get-Date -Format "MMdd-HHmm"
$PartDir      = "$Repo\reports\overnight-laya-$Stamp"
$OutReport    = "$Repo\reports\m1-laya19-$Stamp.json"
$Baseline     = "$Repo\reports\m1-final3.json"
$RunLog       = "$Repo\logs\overnight-laya-$Stamp.log"
$ProgressLog  = "$Repo\logs\overnight-laya-$Stamp-progress.txt"

$LayaEnv = @{
    "DECIDER_MODE"        = "laya"
    "LAYA_DEVICE"         = "cuda"
    "LAYA_BROWSER_MODEL"  = $LayaModel
    "PYTHONUTF8"          = "1"
    "HF_HUB_OFFLINE"      = "1"
    "TORCHDYNAMO_DISABLE" = "1"
}

# ==================================================================
#  HELPERS
# ==================================================================
function Log($msg) {
    $line = "[$(Get-Date -Format 'HH:mm:ss')] $msg"
    Write-Host $line -ForegroundColor Cyan
    Add-Content -Path $ProgressLog -Value $line -Encoding ascii
}
function Ok($m)  { Log "   OK  $m" }
function Warn($m){ Log "  WARN $m" }
function Die($m) { Log "  FAIL $m"; throw $m }

function Set-Env($h) { foreach ($k in $h.Keys) { Set-Item -Path "env:$k" -Value $h[$k] } }

function Cdp-Alive {
    try { Invoke-RestMethod "http://127.0.0.1:9222/json/version" -TimeoutSec 2 | Out-Null; return $true }
    catch { return $false }
}

function Wait-Cdp($maxSec = 30) {
    for ($i = 0; $i -lt $maxSec; $i++) { if (Cdp-Alive) { return $true }; Start-Sleep 1 }
    return $false
}

function Start-Chrome {
    Get-Process chrome -EA SilentlyContinue | Stop-Process -Force -EA SilentlyContinue
    Start-Sleep 2
    Remove-Item -Recurse -Force $ChromeProfile -EA SilentlyContinue
    Start-Process $ChromeExe "--headless=new --remote-debugging-port=9222 --user-data-dir=$ChromeProfile --no-first-run --no-default-browser-check"
    if (-not (Wait-Cdp 30)) { return $false }
    return $true
}

# A task is only trustworthy if its report has a real TaskResult dict.
function Test-Report($path) {
    if (-not (Test-Path $path)) { return $false }
    $r = & $PythonJev -c "import json,sys;d=json.load(open(sys.argv[1],encoding='utf-8'));r=d.get('results') or [];sys.exit(0 if r and isinstance(r[0].get('result'),dict) else 1)" $path 2>$null
    return ($LASTEXITCODE -eq 0)
}

function Invoke-Task($taskFile, $reportPath) {
    $so = "$env:TEMP\otask_out.log"; $se = "$env:TEMP\otask_err.log"
    Remove-Item $so, $se -EA SilentlyContinue
    $p = Start-Process -FilePath $PythonJev `
        -ArgumentList @("-m", "m1.run_tasks", "--tasks", $taskFile,
                        "--log-dir", "$PartDir\logs\$tid", "--report", $reportPath,
                        "--task-delay", "$TaskDelay") `
        -WorkingDirectory $Repo -PassThru -NoNewWindow `
        -RedirectStandardOutput $so -RedirectStandardError $se
    $p | Wait-Process -Timeout $TaskTimeoutSec -EA SilentlyContinue
    if (-not $p.HasExited) {
        Warn "task exceeded ${TaskTimeoutSec}s -- killing pid $($p.Id)"
        Stop-Process -Id $p.Id -Force -EA SilentlyContinue
        Start-Sleep 3
        return $false
    }
    return $true
}

# ==================================================================
#  MAIN
# ==================================================================
$exitCode = 0
$started = Get-Date
New-Item -ItemType Directory -Force -Path $PartDir, "$PartDir\logs", "$Repo\logs" | Out-Null
Set-Content -Path $ProgressLog -Value "" -Encoding ascii

try {
    Log "================ OVERNIGHT LAYA RUN ================"
    Log "  stamp=$Stamp  cap=${MaxHours}h  tasks=$Tasks  model=$LayaModel"

    # -- 0. env --
    Log "Step 0: load .env"
    Get-Content "$Repo\.env" -EA SilentlyContinue |
        Where-Object { $_ -match '^\s*[A-Za-z_][A-Za-z0-9_]*\s*=' } |
        ForEach-Object { $p = $_.Split('=', 2); Set-Item -Path "env:$($p[0].Trim())" -Value $p[1].Trim() }

    $helperUrl = "https://api.groq.com/openai/v1"; $helperModel = "openai/gpt-oss-120b"; $helperKey = $env:GROQ_API_KEY
    if ($TextHelper -eq "deepseek") { $helperUrl = "https://api.deepseek.com/v1"; $helperModel = "deepseek-chat"; $helperKey = $env:DEEPSEEK_API_KEY }
    if ($TextHelper -eq "local")   { $helperUrl = "http://127.0.0.1:11434/v1"; $helperModel = "gemma4:latest"; $helperKey = "local" }

    if ($helperKey) { Ok "GROQ key present" } else { Warn "no GROQ_API_KEY -- TYPE_TEXT may fail" }

    # -- 1. GPU precheck: never run two model services at once (hard rule 3.4) --
    $gpu = [int]((nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits) -replace '\s','')
    Log "Step 1: GPU in use = ${gpu}MB"
    if ($gpu -gt 500) { Warn ">500MB occupied -- something else may hold VRAM. This run loads NO service (in-process laya), so it is safe." }

    # -- 2. clean slate --
    Log "Step 2: kill python, clean CDP residue"
    Get-Process python -EA SilentlyContinue | Where-Object { $_.Id -ne $PID } | ForEach-Object {
        try {
            $cl = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)" -EA Stop).CommandLine
            if ($cl -match "decider|run_tasks|serve\.py|uvicorn") { Stop-Process -Id $_.Id -Force -EA SilentlyContinue }
        } catch {}
    }
    Get-Process chrome, msedge, chromium -EA SilentlyContinue | Stop-Process -Force -EA SilentlyContinue
    Start-Sleep 3
    Remove-Item -Recurse -Force "$env:USERPROFILE\.config\browser-harness" -EA SilentlyContinue
    Ok "clean"

    # -- 3. Chrome --
    Log "Step 3: start headless CDP Chrome (9222)"
    if (-not (Start-Chrome)) { Die "CDP 9222 not ready after 30s" }
    Ok "CDP ready"

    # -- 4. env --
    Log "Step 4: set env"
    Set-Env $LayaEnv
    Set-Env @{
        "TEXT_HELPER_BASE_URL" = $helperUrl
        "TEXT_HELPER_MODEL"    = $helperModel
        "TEXT_HELPER_API_KEY"  = $helperKey
        "HTTPX_PROXY"          = "http://127.0.0.1:2080"
    }
    Ok "DECIDER_MODE=laya (in-process, no service on :8000)"

    # -- 5. task list --
    $lines = @(Get-Content "$Repo\$Tasks" -Encoding UTF8 | Where-Object { $_.Trim() -ne "" })
    Log "Step 5: $($lines.Count) tasks queued"

    $results = @()
    $pilotConfirmed = 0
    $idx = 0
    foreach ($line in $lines) {
        $idx++
        $tid = ([regex]::Match($line, '"task_id"\s*:\s*"([^"]+)"')).Groups[1].Value
        $isPilot = ($idx -le $PilotCount)

        # Pilot gate: an unattended run must not burn hours on a broken harness.
        # Gate fires AFTER the pilot tasks have actually run: at idx == PilotCount
        # it would fire before task 1 executes, so -PilotCount 1 always aborted.
        if ($idx -eq ($PilotCount + 1) -and $pilotConfirmed -eq 0) {
            Log "PILOT GATE FAILED: 0/$PilotCount produced a valid TaskResult."
            Log "Harness is systematically broken -- aborting instead of wasting the night."
            Log "Parts kept in $PartDir for inspection."
            $exitCode = 3
            break
        }

        # wall-clock cap
        $elapsedH = ((Get-Date) - $started).TotalHours
        if ($elapsedH -gt $MaxHours) {
            Log "CAP REACHED after $([Math]::Round($elapsedH,2))h -- stopping before $tid"
            break
        }

        $reportPath = "$PartDir\$tid.json"
        $taskFile = "$env:TEMP\otask.jsonl"

        # resume: skip if a trustworthy report already exists
        if (Test-Report $reportPath) { Log "[$idx/$($lines.Count)] $tid  SKIP (report already valid)"; continue }

        $phase = if ($isPilot) { "PILOT" } else { "RUN  " }
        Log "[$idx/$($lines.Count)] $tid  $phase start (elapsed $([Math]::Round($elapsedH,2))h)"

        # chrome must be alive for every task (daemon death is contained by the fresh process)
        if (-not (Cdp-Alive)) { Warn "CDP down before $tid -- restarting Chrome"; if (-not (Start-Chrome)) { Warn "Chrome restart failed"; continue } }

        Set-Content -Path $taskFile -Value $line -Encoding ascii
        $ok = Invoke-Task $taskFile $reportPath

        if (-not (Test-Report $reportPath)) {
            if ($ok) {
                # process exited but produced no usable TaskResult -> daemon-level failure
                Warn "$tid produced no TaskResult (attempt 1) -- refreshing Chrome and retrying once"
                if (-not (Start-Chrome)) { Warn "Chrome restart failed; skipping $tid"; continue }
                Set-Content -Path $taskFile -Value $line -Encoding ascii
                [void](Invoke-Task $taskFile $reportPath)
            } else {
                Warn "$tid timed out and was killed; skipping (no retry after a hang)"
            }
        }

        if (Test-Report $reportPath) {
            $results += $tid
            if ($isPilot) { $pilotConfirmed++ }
            Ok "$tid done ($($results.Count) confirmed)"
        } else {
            Warn "$tid UNRESOLVED after retry -- treat as harness, not model"
        }
        Start-Sleep 2
    }

    # -- 6. merge --
    Log "Step 6: merge $PartDir -> $OutReport"
    & $PythonJev -m m1.merge_reports $PartDir $Baseline $OutReport
    $mergeExit = $LASTEXITCODE

    # -- 7. calibration warning evidence --
    $warnFile = "$env:TEMP\otask_err.log"
    if (Test-Path $warnFile) {
        $cal = Select-String -Path $warnFile -Pattern "invalid temperatures|uncalibrated" -SimpleMatch:$false -EA SilentlyContinue
        if ($cal) { Warn "checkpoint calibration warning observed: $($cal[0].Line.Trim())" }
    }

    Log "=== OVERNIGHT DONE: $($results.Count)/$($lines.Count) tasks confirmed, $([Math]::Round(((Get-Date)-$started).TotalMinutes,1)) min ==="
    Log "Merged report: $OutReport"
    Log "Progress log : $ProgressLog"

} catch {
    Log "ERROR: $_"
    $exitCode = 1
} finally {
    Log "Cleanup: stopping Chrome, then orphan python"
    Get-Process chrome -EA SilentlyContinue | Stop-Process -Force -EA SilentlyContinue
    Start-Sleep 3
    # Kill orphaned benchmark/daemon processes, then verify AFTER killing.
    Get-Process python -EA SilentlyContinue | Where-Object { $_.Id -ne $PID } | ForEach-Object {
        try {
            $cl = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)" -EA Stop).CommandLine
            if ($cl -match "run_tasks|decider|serve\.py|uvicorn|browser_harness") {
                Stop-Process -Id $_.Id -Force -EA SilentlyContinue
            }
        } catch {}
    }
    Start-Sleep 7
    $left = (Get-Process chrome -EA SilentlyContinue | Measure-Object).Count
    $pyLeft = (Get-Process python -EA SilentlyContinue | Where-Object { $_.Id -ne $PID } | Measure-Object).Count
    Log "Verify after cleanup: chrome=$left (must be 0), stray python=$pyLeft"
    if ($left -ne 0) { $exitCode = 1 }
}

exit $exitCode