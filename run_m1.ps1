param(
    [string]$Version = "",
    [int]$TaskDelay = 3,
    [switch]$SkipClean,
    [string]$DeciderModel = "Mapika/decider-2b",
    [string]$Fp8 = "0",
    [string]$TextHelper = "groq",
    # ExternalDecider: 决策服务已在 8000 上跑着（如 decider.serve_4bit），本脚本不再加载模型。
    # 不加这个开关而 8000 已被占用时，第二个 uvicorn 会把同一份权重再加载一份进显存/内存。
    [switch]$ExternalDecider
)

# ═══════════════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════════════
$Repo         = "C:\Users\Administrator\openjev-ultrafast"
$DeciderDir   = "D:\openjev-models\decider"
$ChromeExe    = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$ChromeProfile= "C:\chrome-cdp-test"
$PythonJev    = "C:\Users\Administrator\miniconda3\envs\jev\python.exe"
$PythonDecider= "$DeciderDir\.venv\Scripts\python.exe"

# Decider env (must be set BEFORE Start-Process so child inherits them)
$DeciderEnv = @{
    "DECIDER_MODEL"   = $DeciderModel
    "HF_HUB_OFFLINE"  = "1"
    "USE_TF"          = "0"
    "DECIDER_COMPILE" = "0"
    "DECIDER_FP8"     = $Fp8
}

# Benchmark env
$helperUrl = "https://api.groq.com/openai/v1"; $helperModel = "openai/gpt-oss-120b"; $helperKey = $env:GROQ_API_KEY
if ($TextHelper -eq "deepseek") {
    $helperUrl = "https://api.deepseek.com/v1"; $helperModel = "deepseek-chat"; $helperKey = $env:DEEPSEEK_API_KEY
}
$BenchEnv = @{
    "DECIDER_MODE"          = "typesafe"
    "PYTHONUTF8"            = "1"
    "TYPESAFE_BASE_URL"     = "http://127.0.0.1:8000/v1/systemone"
    "TYPESAFE_API_KEY"      = "local"
    "TEXT_HELPER_BASE_URL"  = $helperUrl
    "TEXT_HELPER_MODEL"     = $helperModel
    "TEXT_HELPER_API_KEY"   = $helperKey
    "HTTPX_PROXY"           = "http://127.0.0.1:2080"
}

# ═══════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════
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

# ═══════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════
if (-not $Version) { $Version = "v" + (Get-Date -Format "MMdd-HHmm") }
$ReportPath = "$Repo\reports\m1-$($DeciderModel -replace '[/\\.]','-')-$Version.json"
$LogDir     = "$Repo\logs\m1-$($DeciderModel -replace '[/\\.]','-')-$Version"

$deciderProc = $null
$exitCode = 0

try {
    Log "=== OpenJEV Ultrafast M1 Runner ($Version) ==="

    # ── 1. Disable sleep ──────────────────────────────────────────
    if (-not $SkipClean) {
        Log "Step 1: disable sleep/lock"
        powercfg /change standby-timeout-ac 0 2>$null
        powercfg /change monitor-timeout-ac 0 2>$null
        Ok "sleep disabled"
    }

    # ── 2. Kill old processes ─────────────────────────────────────
    if (-not $SkipClean) {
        Log "Step 2: kill old processes"
        Get-Process python -EA SilentlyContinue | Where-Object { $_.Id -ne $PID } | ForEach-Object {
            try {
                $cl = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)" -EA Stop).CommandLine
                if ($cl -match "decider|run_tasks|serve\.py") {
                    Stop-Process -Id $_.Id -Force -EA SilentlyContinue
                }
            } catch {}
        }
        Get-Process chrome, msedge, chromium -EA SilentlyContinue | Stop-Process -Force
        Start-Sleep 3
        Ok "old processes killed"
    }

    # ── 3. Clean CDP residue ──────────────────────────────────────
    if (-not $SkipClean) {
        Log "Step 3: clean CDP residue"
        Remove-Item -Recurse -Force $ChromeProfile -EA SilentlyContinue
        Remove-Item -Recurse -Force "$env:USERPROFILE\.config\browser-harness" -EA SilentlyContinue
        Ok "CDP state cleared"
    }

    # ── 4. Start Chrome CDP ───────────────────────────────────────
    Log "Step 4: start headless CDP Chrome (9222)"
    Start-Process $ChromeExe "--headless=new --remote-debugging-port=9222 --user-data-dir=$ChromeProfile --no-first-run --no-default-browser-check"
    if (-not (Wait-Url "http://127.0.0.1:9222/json/version" 30 1)) {
        Fail "CDP 9222 not ready after 30s"
    }
    Ok "CDP ready"

    # ── 5. Start decider-2B ───────────────────────────────────────
    if ($ExternalDecider) {
        Log "Step 5: use external decider on 8000 (no local load)"
        if (-not (Wait-Url "http://127.0.0.1:8000/health" 10 2)) { Fail "external decider not answering /health on 8000" }
        Ok "external decider ready"
    } else {
        Log "Step 5: start decider ($DeciderModel, fp8=$Fp8) on 8000"
        if (-not (Test-Path "$Repo\logs")) { New-Item -ItemType Directory "$Repo\logs" -Force | Out-Null }

        # Set decider env in current session so Start-Process inherits them
        foreach ($k in $DeciderEnv.Keys) { Set-Item -Path "env:$k" -Value $DeciderEnv[$k] }

        $deciderProc = Start-Process $PythonDecider `
            -ArgumentList "-m","uvicorn","decider.serve:app","--host","0.0.0.0","--port","8000" `
            -WorkingDirectory $DeciderDir `
            -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput "$Repo\logs\decider_stdout.log" `
            -RedirectStandardError  "$Repo\logs\decider_stderr.log"

        Log "  decider pid $($deciderProc.Id), waiting for /health..."
        if (-not (Wait-Url "http://127.0.0.1:8000/health" 120 3)) {
            Fail "decider not ready after 120s (see $Repo\logs\decider_stderr.log)"
        }
        Ok "decider ready (pid $($deciderProc.Id))"
    }

    # ── 6. Set benchmark env ──────────────────────────────────────
    Log "Step 6: set benchmark env"
    foreach ($k in $BenchEnv.Keys) { Set-Item -Path "env:$k" -Value $BenchEnv[$k] }
    Ok "env set"

    # ── 7. Run benchmark ──────────────────────────────────────────
    Log "Step 7: run 20 tasks -> $ReportPath"
    Set-Location $Repo
    $start = Get-Date
    & $PythonJev -m m1.run_tasks `
        --tasks m1\tasks.jsonl `
        --log-dir $LogDir `
        --report $ReportPath `
        --task-delay $TaskDelay
    $benchExit = $LASTEXITCODE
    $elapsed = ((Get-Date) - $start).TotalMinutes

    Log "  benchmark finished in $([Math]::Round($elapsed, 1)) min (exit $benchExit)"

    # ── 8. Summary ────────────────────────────────────────────────
    Log "Step 8: summary"
    Get-Content $ReportPath | & $PythonJev -c "import json,sys; d=json.load(sys.stdin); s=d['summary']; print('  PASS=%d FAIL=%d ERROR=%d' % (s['pass'],s['fail'],s['error'])); print('  quadrants:', s['quadrants']); print('  failure_modes:', s['failure_modes']); print('  system_modes:', s.get('system_modes',{})); print('  acceptance:', d['acceptance'])"

    Log "=== DONE: $Version ($([Math]::Round($elapsed,1)) min) ==="
    Log "Report: $ReportPath"

} catch {
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] ERROR: $_" -ForegroundColor Red
    $exitCode = 1
} finally {
    # ── Cleanup ───────────────────────────────────────────────────
    if ($deciderProc -and -not $deciderProc.HasExited) {
        Log "Cleanup: stopping decider (pid $($deciderProc.Id))"
        Stop-Process -Id $deciderProc.Id -Force -EA SilentlyContinue
    }
    Log "Cleanup: stopping Chrome"
    Get-Process chrome -EA SilentlyContinue | Stop-Process -Force -EA SilentlyContinue
}

exit $exitCode
