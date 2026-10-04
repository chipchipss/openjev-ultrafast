param(
    [string]$Task = "flights",          # flights | wikipedia
    [string]$Date = "auto",             # flights only: YYYY-MM-DD or auto
    [string]$DeciderModel = "Mapika/decider-2b",
    [string]$ProxyUrl = "http://127.0.0.1:2080",
    [string]$TextHelper = "groq",
    # Keep the browser open at the end so you can look at the result yourself.
    [switch]$KeepOpen
)

# ==================================================================
#  One command to actually USE this thing.
#
#    .\run_demo.ps1                      # Google Flights, end to end
#    .\run_demo.ps1 -Task wikipedia
#    .\run_demo.ps1 -Task flights -KeepOpen
#
#  Starts the local decider, starts Chrome (through your proxy), runs the
#  demo with upstream's independent verification, then cleans up. Verified
#  end to end on 2026-10-04; the demo itself runs with api_calls=0, i.e.
#  no cloud API is involved -- the text helper is not needed because the
#  skills layer reads field values straight out of the goal.
#
#  NOTE: ASCII only. PowerShell 5.1 reads .ps1 as ANSI (GBK) without a BOM.
# ==================================================================

$Repo          = "C:\Users\Administrator\openjev-ultrafast"
$ChromeExe     = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$ChromeProfile = "C:\chrome-cdp-test"
$PythonJev     = "C:\Users\Administrator\miniconda3\envs\jev\python.exe"
$PythonDecider = "D:\openjev-models\decider\.venv\Scripts\python.exe"
$DeciderDir    = "D:\openjev-models\decider"
$Stamp         = Get-Date -Format "MMdd-HHmm"
$Out           = "$Repo\reports\demo-$Task-$Stamp.json"
$ProgressLog   = "$Repo\logs\demo-$Task-$Stamp.log"

function Log($m)  { $l = "[$(Get-Date -Format 'HH:mm:ss')] $m"; Write-Host $l -ForegroundColor Cyan
                    Add-Content $ProgressLog $l -Encoding ascii }
function Ok($m)   { Log "   OK  $m" }
function Warn($m) { Log "  WARN $m" }
function Die($m)  { Log "  FAIL $m"; throw $m }
function Set-Env($h) { foreach ($k in $h.Keys) { Set-Item -Path "env:$k" -Value $h[$k] } }

function Wait-Url($url, $maxSec = 60, $intervalSec = 2) {
    for ($i = 0; $i -lt ($maxSec / $intervalSec); $i++) {
        try { Invoke-RestMethod $url -TimeoutSec 2 | Out-Null; return $true } catch { Start-Sleep $intervalSec }
    }
    return $false
}

function Cdp-Alive { try { Invoke-RestMethod "http://127.0.0.1:9222/json/version" -TimeoutSec 2 | Out-Null; return $true } catch { return $false } }

function Start-Chrome {
    Get-Process chrome -EA SilentlyContinue | Stop-Process -Force -EA SilentlyContinue
    Start-Sleep 2
    Remove-Item -Recurse -Force $ChromeProfile -EA SilentlyContinue
    # Chrome must honour the same egress proxy as the rest of the stack.
    $px = if ($ProxyUrl) { "--proxy-server=$ProxyUrl" } else { "" }
    Start-Process $ChromeExe "--headless=new --remote-debugging-port=9222 --user-data-dir=$ChromeProfile --no-first-run --no-default-browser-check $px"
    for ($i = 0; $i -lt 30; $i++) { if (Cdp-Alive) { return $true }; Start-Sleep 1 }
    return $false
}

$exitCode = 0
$svcProc = $null
New-Item -ItemType Directory -Force -Path "$Repo\logs", "$Repo\reports" | Out-Null
Set-Content $ProgressLog "" -Encoding ascii

try {
    Log "============ OpenJEV demo: $Task ============"

    # -- 0. prerequisites ------------------------------------------------
    Log "Step 0: prerequisites"
    foreach ($p in @($PythonJev, $PythonDecider, $ChromeExe, "$DeciderDir\decider\serve.py")) {
        if (-not (Test-Path $p)) { Die "missing: $p" }
    }
    Get-Content "$Repo\.env" -EA SilentlyContinue |
        Where-Object { $_ -match '^\s*[A-Za-z_][A-Za-z0-9_]*\s*=' } |
        ForEach-Object { $q = $_.Split('=',2); Set-Item -Path "env:$($q[0].Trim())" -Value $q[1].Trim() }

    $helperUrl = "https://api.groq.com/openai/v1"; $helperModel = "openai/gpt-oss-120b"; $helperKey = $env:GROQ_API_KEY
    if ($TextHelper -eq "local") { $helperUrl = "http://127.0.0.1:11434/v1"; $helperModel = "gemma4:latest"; $helperKey = "local" }
    if ($TextHelper -eq "none") { $helperUrl = ""; $helperModel = ""; $helperKey = "" }

    $gpu = [int]((nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits) -replace '\s','')
    Log "  GPU in use = ${gpu}MB"
    if ($gpu -gt 500) { Die "GPU busy (${gpu}MB). Stop the other model first -- two model services do not fit in 8GB." }

    # -- 1. proxy (warn only: the demo should still try) --------------------
    if ($ProxyUrl) {
        $pxAlive = $false
        try { $null = Invoke-WebRequest -Uri "https://api.groq.com" -Proxy $ProxyUrl -TimeoutSec 8 -UseBasicParsing; $pxAlive = $true } catch {}
        if ($pxAlive) { Ok "proxy $ProxyUrl answering" }
        else { Warn "proxy $ProxyUrl not answering -- sites that need it (wikipedia) will fail to load" }
    }

    # -- 2. decider ------------------------------------------------------
    Log "Step 1: start local decider ($DeciderModel) on 8000"
    Set-Env @{ "DECIDER_MODEL" = $DeciderModel; "HF_HUB_OFFLINE" = "1"; "USE_TF" = "0";
               "DECIDER_COMPILE" = "0"; "DECIDER_FP8" = "0" }
    $svcProc = Start-Process -FilePath $PythonDecider `
        -ArgumentList @("-m","uvicorn","decider.serve:app","--host","0.0.0.0","--port","8000") `
        -WorkingDirectory $DeciderDir -PassThru -NoNewWindow `
        -RedirectStandardOutput "$Repo\logs\demo-decider_out.log" -RedirectStandardError "$Repo\logs\demo-decider_err.log"
    Log "  pid $($svcProc.Id); loading weights..."
    if (-not (Wait-Url "http://127.0.0.1:8000/health" 240 3)) {
        Get-Content "$Repo\logs\demo-decider_err.log" -Tail 20 -EA SilentlyContinue | ForEach-Object { Log "  | $_" }
        Die "decider not ready after 240s"
    }
    Ok "decider ready"

    # -- 3. Chrome --------------------------------------------------------
    Log "Step 2: start Chrome"
    if (-not (Start-Chrome)) { Die "CDP 9222 not ready" }
    Ok "CDP ready"

    # -- 4. run -----------------------------------------------------------
    Log "Step 3: run the demo -> $Out"
    Set-Env @{ "DECIDER_MODE" = "typesafe"; "TYPESAFE_BASE_URL" = "http://127.0.0.1:8000/v1/systemone";
               "TYPESAFE_API_KEY" = "local"; "PYTHONUTF8" = "1"
               "TEXT_HELPER_BASE_URL" = $helperUrl; "TEXT_HELPER_MODEL" = $helperModel
               "TEXT_HELPER_API_KEY" = $helperKey; "HTTPX_PROXY" = $ProxyUrl }
    Set-Location $Repo
    $start = Get-Date
    & $PythonJev m4a\run_flights_ours.py --task $Task --out $Out
    $demoExit = $LASTEXITCODE
    $elapsed = ((Get-Date) - $start).TotalSeconds

    # -- 5. report --------------------------------------------------------
    Log ""
    Log "============ RESULT ============"
    if (Test-Path $Out) {
        $j = Get-Content $Out -Raw | ConvertFrom-Json
        Log ("  status   : {0}" -f $j.status)
        Log ("  task wall: {0}s   steps={1}  decisions={2}" -f $j.wall_s, $j.steps, $j.n_decisions)
        Log ("  total    : {0:N1}s (includes decider load + browser start)" -f $elapsed)
        $v = $j.verification
        if ($v) {
            $parts = @()
            foreach ($p in $v.checks.PSObject.Properties) { $parts += ("{0}={1}" -f $p.Name, $p.Value) }
            Log ("  checks   : {0}" -f ($parts -join "  "))
            if ($v.passed) { Ok "VERIFICATION PASSED ($($parts.Count)/$($parts.Count))" }
            else { Warn "VERIFICATION FAILED -- see $Out" }
        } else {
            Warn "report has no verification block"
        }
    } else {
        Warn "no report written at $Out (exit $demoExit)"
    }
    Log "  report: $Out"
    Log "  log   : $ProgressLog"

} catch {
    Log "ERROR: $_"
    $exitCode = 1
} finally {
    if (-not $KeepOpen) {
        Log "Cleanup: stopping decider and Chrome"
        if ($svcProc -and -not $svcProc.HasExited) { Stop-Process -Id $svcProc.Id -Force -EA SilentlyContinue }
        Get-Process python -EA SilentlyContinue | Where-Object { $_.Id -ne $PID } | ForEach-Object {
            try { $cl = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)" -EA Stop).CommandLine
                  if ($cl -match "run_flights|decider\.serve|uvicorn") { Stop-Process -Id $_.Id -Force -EA SilentlyContinue } } catch {}
        }
        Get-Process chrome -EA SilentlyContinue | Stop-Process -Force -EA SilentlyContinue
        Start-Sleep 7
        $left = (Get-Process chrome -EA SilentlyContinue | Measure-Object).Count
        Log "Verify: chrome=$left (must be 0)"
        if ($left -ne 0) { $exitCode = 1 }
    } else {
        Log "KeepOpen: Chrome and the decider stay up. Close them yourself when done:"
        Log "  Get-Process chrome,python -EA SilentlyContinue | Stop-Process -Force"
    }
}

exit $exitCode