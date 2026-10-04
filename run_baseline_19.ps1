param(
    [double]$MaxHours = 2.0,
    [int]$TaskDelay = 1,
    [int]$TaskTimeoutSec = 300,
    [string]$Tasks = "m1\tasks-laya-19.jsonl",
    [string]$DeciderModel = "Mapika/decider-2b",
    [string]$Fp8 = "0",
    [string]$TextHelper = "groq",
    [int]$PilotCount = 2,
    [switch]$NoService,     # decider already listening on 8000
    # Egress proxy for Chrome AND for the preflight probe. Empty = no proxy.
    [string]$ProxyUrl = "http://127.0.0.1:2080",
    [switch]$AllowUnreachableDomains   # run anyway even if some domains are down
)

# NOTE: pure ASCII -- PowerShell 5.1 reads .ps1 as ANSI (GBK) without a BOM.
#
# This is the production configuration: bare decider-2b over the TypeSafe wire,
# one task per process. Every previous baseline (reports/m1-final3.json) was
# produced WITHOUT per-task isolation and still carried 1-4 harness gaps, so the
# number was never measured on a full 19/19 set. This runner is that measurement.

# ==================================================================
#  CONFIG
# ==================================================================
$Repo          = "C:\Users\Administrator\openjev-ultrafast"
$ChromeExe     = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$ChromeProfile = "C:\chrome-cdp-test"
$PythonJev     = "C:\Users\Administrator\miniconda3\envs\jev\python.exe"
$PythonDecider = "D:\openjev-models\decider\.venv\Scripts\python.exe"
$DeciderDir    = "D:\openjev-models\decider"
$Stamp         = Get-Date -Format "MMdd-HHmm"
$PartDir       = "$Repo\reports\baseline-$Stamp"
$OutReport     = "$Repo\reports\m1-baseline-$Stamp.json"
$ProgressLog   = "$Repo\logs\baseline-$Stamp-progress.txt"
$SvcOut        = "$Repo\logs\baseline-$Stamp-svc_out.log"
$SvcErr        = "$Repo\logs\baseline-$Stamp-svc_err.log"

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
    # Chrome must honour the same egress proxy as the rest of the stack. Without
    # --proxy-server, any site that needs the proxy fails to load inside the browser
    # and every task on it degrades to chrome-error:// + steps=0 + correct_abandon --
    # which reads exactly like a model failure. Measured 2026-10-04: s004/l002/x002
    # (all en.wikipedia.org) died this way while wikipedia was unreachable direct.
    $px = if ($ProxyUrl) { "--proxy-server=$ProxyUrl" } else { "" }
    Start-Process $ChromeExe "--headless=new --remote-debugging-port=9222 --user-data-dir=$ChromeProfile --no-first-run --no-default-browser-check $px"
    return (Wait-Cdp 30)
}

# Preflight: prove every task's start domain is reachable BEFORE spending 8
# minutes producing numbers. A run where some pages cannot load is not a weak
# model result, it is a broken measurement -- and it looks identical in the report.
#
# Each domain is probed BOTH direct and through the proxy, because the two failure
# modes need opposite fixes:
#   direct-ok              -> fine, proxy irrelevant
#   needs-proxy, proxy up  -> fine once Chrome passes --proxy-server
#   needs-proxy, proxy down-> unmeasurable until the proxy is started
#   neither                -> genuinely offline
# example.invalid is the negative task's deliberate non-domain: never probe it.
function Get-DomainReachability($tasksFile) {
    $domains = [ordered]@{}
    foreach ($line in (Get-Content $tasksFile -Encoding UTF8)) {
        if ($line.Trim() -eq "") { continue }
        $m = [regex]::Match($line, '"domain"\s*:\s*"([^"]+)"')
        if ($m.Success -and $m.Groups[1].Value -notmatch '\.invalid$') {
            $domains[$m.Groups[1].Value] = $true
        }
    }
    $out = @()
    foreach ($d in $domains.Keys) {
        $probe = "https://$d/"
        $direct = $false; $viaproxy = $false
        try { $null = Invoke-WebRequest -Uri $probe -TimeoutSec 12 -UseBasicParsing; $direct = $true } catch {}
        if ($ProxyUrl) {
            try { $null = Invoke-WebRequest -Uri $probe -Proxy $ProxyUrl -TimeoutSec 12 -UseBasicParsing; $viaproxy = $true } catch {}
        }
        $out += [pscustomobject]@{ domain = $d; direct = $direct; proxy = $viaproxy }
    }
    return $out
}
function Svc-Alive { try { Invoke-RestMethod "http://127.0.0.1:8000/health" -TimeoutSec 3 | Out-Null; return $true } catch { return $false } }
function Wait-Svc($maxSec = 240) { for ($i=0; $i -lt $maxSec/3; $i++) { if (Svc-Alive) { return $true }; Start-Sleep 3 }; return $false }

# A report is trustworthy only if it has a real TaskResult AND no transport
# failures. A run full of "connection refused" measures the proxy, not the model.
function Test-Report($path) {
    if (-not (Test-Path $path)) { return $false }
    & $PythonJev -c "import json,sys;d=json.load(open(sys.argv[1],encoding='utf-8'));r=d.get('results') or [];ok=bool(r) and isinstance(r[0].get('result'),dict) and 'connection failed' not in json.dumps(d,ensure_ascii=False);sys.exit(0 if ok else 1)" $path 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Assert-SvcAlive($svcProc, $where) {
    if ($svcProc -and $svcProc.HasExited) {
        Log "DECIDER SERVICE DEAD at $where (pid $($svcProc.Id), exit $($svcProc.ExitCode))."
        Log "  stderr: $SvcErr"
        if (Test-Path $SvcErr) { Get-Content $SvcErr -Tail 20 | ForEach-Object { Log "  | $_" } }
        return $false
    }
    return $true
}

function Invoke-Task($taskFile, $reportPath, $tid) {
    $so = "$env:TEMP\btask_out.log"; $se = "$env:TEMP\btask_err.log"
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
    Log "=========== BASELINE: bare decider-2b, 19 tasks, isolated ==========="
    Log "  stamp=$Stamp cap=${MaxHours}h model=$DeciderModel fp8=$Fp8"

    # -- 0. env --
    Log "Step 0: load .env"
    Get-Content "$Repo\.env" -EA SilentlyContinue |
        Where-Object { $_ -match '^\s*[A-Za-z_][A-Za-z0-9_]*\s*=' } |
        ForEach-Object { $p = $_.Split('=',2); Set-Item -Path "env:$($p[0].Trim())" -Value $p[1].Trim() }

    $helperUrl = "https://api.groq.com/openai/v1"; $helperModel = "openai/gpt-oss-120b"; $helperKey = $env:GROQ_API_KEY
    if ($TextHelper -eq "deepseek") { $helperUrl = "https://api.deepseek.com/v1"; $helperModel="deepseek-chat"; $helperKey=$env:DEEPSEEK_API_KEY }
    if ($TextHelper -eq "local")   { $helperUrl = "http://127.0.0.1:11434/v1"; $helperModel="gemma4:latest"; $helperKey="local" }
    if ($helperKey) { Ok "GROQ key present" } else { Warn "no GROQ_API_KEY -- TYPE_TEXT will fail" }

    # -- 1. GPU gate: exactly one model resident, never two --
    $gpu = [int]((nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits) -replace '\s','')
    Log "Step 1: GPU in use = ${gpu}MB"
    if ($gpu -gt 500 -and -not $NoService) { Die "GPU busy (${gpu}MB). Stop the other model first -- hard rule 3.4." }

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

    # -- 3. decider service --
    if ($NoService) {
        Log "Step 3: use existing service on 8000"
        if (-not (Wait-Svc 10)) { Die "no /health on 8000" }
        Ok "service reachable"
    } else {
        Log "Step 3: start decider ($DeciderModel, fp8=$Fp8) on 8000"
        Set-Env @{
            "DECIDER_MODEL" = $DeciderModel; "HF_HUB_OFFLINE" = "1"
            "USE_TF" = "0"; "DECIDER_COMPILE" = "0"; "DECIDER_FP8" = $Fp8
        }
        $svcProc = Start-Process -FilePath $PythonDecider `
            -ArgumentList @("-m","uvicorn","decider.serve:app","--host","0.0.0.0","--port","8000") `
            -WorkingDirectory $DeciderDir -PassThru -NoNewWindow `
            -RedirectStandardOutput $SvcOut -RedirectStandardError $SvcErr
        Log "  svc pid $($svcProc.Id); waiting for /health (up to 240s)..."
        if (-not (Wait-Svc 240)) {
            Log "  --- svc stderr tail ---"
            if (Test-Path $SvcErr) { Get-Content $SvcErr -Tail 25 | ForEach-Object { Log "  | $_" } }
            Die "decider not ready after 240s"
        }
        Ok "decider ready"
    }

    # -- 3.5 PREFLIGHT: are the task domains actually reachable? --
    Log "Step 3.5: preflight reachability of task domains (proxy=$ProxyUrl)"
    $pxAlive = $false
    if ($ProxyUrl) {
        try { $null = Invoke-WebRequest -Uri "https://api.groq.com" -Proxy $ProxyUrl -TimeoutSec 8 -UseBasicParsing; $pxAlive = $true } catch {}
        Log "  proxy $ProxyUrl answering = $pxAlive"
    }
    $reach = @(Get-DomainReachability "$Repo\$Tasks")
    $needsProxy = @($reach | Where-Object { -not $_.direct -and $_.proxy })
    $dead       = @($reach | Where-Object { -not $_.direct -and -not $_.proxy })
    $directOnly = @($reach | Where-Object { $_.direct })
    Log "  reachable direct : $($directOnly.Count) / $($reach.Count)  [$($directOnly.domain -join ' ')]"
    if ($needsProxy.Count) { Log "  need proxy       : $($needsProxy.Count)  [$($needsProxy.domain -join ' ')]" }
    if ($dead.Count)       { Log "  UNREACHABLE      : $($dead.Count)  [$($dead.domain -join ' ')]" }

    if ($dead.Count -gt 0) {
        Log "Aborting: those pages cannot load, so their tasks would measure the network, not the agent."
        Log "Fix the network, or pass -AllowUnreachableDomains to proceed anyway."
        $exitCode = 5; throw "preflight failed"
    }
    if ($needsProxy.Count -gt 0 -and -not $pxAlive) {
        Log "Aborting: $($needsProxy.Count) domain(s) need the proxy and $ProxyUrl is not answering."
        Log "Start the proxy, or pass -AllowUnreachableDomains to proceed (those tasks will degrade)."
        $exitCode = 5; throw "preflight failed"
    }
    if ($needsProxy.Count -gt 0) { Ok "proxy-backed domains will load (Chrome gets --proxy-server)" }
    Ok "preflight passed"

    # -- 4. Chrome --
    Log "Step 4: start headless CDP Chrome (9222)"
    if (-not (Start-Chrome)) { Die "CDP 9222 not ready" }
    Ok "CDP ready"

    # -- 5. bench env (production path: TypeSafe wire, no proxy on loopback) --
    Log "Step 5: set env"
    Set-Env @{
        "DECIDER_MODE"          = "typesafe"
        "TYPESAFE_BASE_URL"     = "http://127.0.0.1:8000/v1/systemone"
        "TYPESAFE_API_KEY"      = "local"
        "TEXT_HELPER_BASE_URL"  = $helperUrl
        "TEXT_HELPER_MODEL"     = $helperModel
        "TEXT_HELPER_API_KEY"   = $helperKey
        "HTTPX_PROXY"           = "http://127.0.0.1:2080"
        "PYTHONUTF8"            = "1"
    }
    Ok "DECIDER_MODE=typesafe -> 127.0.0.1:8000"

    # -- 6. task loop --
    $lines = @(Get-Content "$Repo\$Tasks" -Encoding UTF8 | Where-Object { $_.Trim() -ne "" })
    Log "Step 6: $($lines.Count) tasks queued"
    $results = @(); $pilotConfirmed = 0; $idx = 0

    foreach ($line in $lines) {
        $idx++
        $tid = ([regex]::Match($line, '"task_id"\s*:\s*"([^"]+)"')).Groups[1].Value
        $isPilot = ($idx -le $PilotCount)
        $reportPath = "$PartDir\$tid.json"
        $taskFile = "$env:TEMP\btask.jsonl"

        # Gate fires AFTER the pilot tasks have actually run: at idx == PilotCount
        # it would fire before task 1 executes, so -PilotCount 1 always aborted.
        if ($idx -eq ($PilotCount + 1) -and $pilotConfirmed -eq 0) {
            Log "PILOT GATE FAILED: 0/$PilotCount valid. Aborting."; $exitCode = 3; break
        }
        $eh = ((Get-Date) - $started).TotalHours
        if ($eh -gt $MaxHours) { Log "CAP REACHED ($( [Math]::Round($eh,2) )h) -- stopping before $tid"; break }

        if (Test-Report $reportPath) { Log "[$idx/$($lines.Count)] $tid  SKIP (valid report exists)"; continue }

        $phase = if ($isPilot) { "PILOT" } else { "RUN  " }
        Log "[$idx/$($lines.Count)] $tid  $phase start (elapsed $([Math]::Round($eh,2))h)"

        if (-not (Assert-SvcAlive $svcProc "before $tid")) { $exitCode = 4; break }
        if (-not (Cdp-Alive)) { Warn "CDP down before $tid -- restarting Chrome"; if (-not (Start-Chrome)) { Warn "Chrome restart failed"; continue } }

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
        } else { Warn "$tid UNRESOLVED after retry" }
        Start-Sleep 2
        if (-not (Assert-SvcAlive $svcProc "after $tid")) { $exitCode = 4; break }
    }

    # -- 7. merge --
    Log "Step 7: merge -> $OutReport"
    & $PythonJev -m m1.merge_reports $PartDir "$Repo\reports\m1-final3.json" $OutReport
    Log "=== DONE: $($results.Count)/$($lines.Count) confirmed, $([Math]::Round(((Get-Date)-$started).TotalMinutes,1)) min ==="
    Log "Report: $OutReport"

} catch {
    Log "ERROR: $_"
    $exitCode = 1
} finally {
    Log "Cleanup: stop decider, then Chrome, then orphan python"
    if ($svcProc -and -not $svcProc.HasExited) { Stop-Process -Id $svcProc.Id -Force -EA SilentlyContinue }
    Get-Process python -EA SilentlyContinue | Where-Object { $_.Id -ne $PID } | ForEach-Object {
        try { $cl = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)" -EA Stop).CommandLine
              if ($cl -match "run_tasks|decider|serve|uvicorn|jev_service") { Stop-Process -Id $_.Id -Force -EA SilentlyContinue } } catch {}
    }
    Get-Process chrome -EA SilentlyContinue | Stop-Process -Force -EA SilentlyContinue
    Start-Sleep 7
    $chromeLeft = (Get-Process chrome -EA SilentlyContinue | Measure-Object).Count
    $pyLeft = (Get-Process python -EA SilentlyContinue | Where-Object { $_.Id -ne $PID } | Measure-Object).Count
    Log "Verify after cleanup: chrome=$chromeLeft (must be 0), stray python=$pyLeft"
    if ($chromeLeft -ne 0) { $exitCode = 1 }
}

exit $exitCode