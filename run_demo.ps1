param(
    [string]$Task = "flights",          # flights | wikipedia
    [string]$Date = "auto",             # flights only: YYYY-MM-DD or auto
    [int]$SvcPort = 8090,               # StartLux wire port (llama :8081 is internal)
    [string]$ProxyUrl = "http://127.0.0.1:2080",
    [string]$TextHelper = "startlux",
    # llama-server behind the wire; also serves as the Text Helper (local, zero cloud).
    [int]$LlamaPort = 8081,
    # Keep the browser open at the end so you can look at the result yourself.
    [switch]$KeepOpen,
    # Leave the decision stack running after the demo (it is slow to reload).
    [switch]$KeepService
)

# ==================================================================
#  One command to actually USE this thing.
#
#    .\run_demo.ps1                      # Google Flights, end to end
#    .\run_demo.ps1 -Task wikipedia
#    .\run_demo.ps1 -Task flights -KeepOpen
#
#  Cold box: downloads the StartLux GGUF + llama.cpp binaries on demand
#  (scripts\startlux_serve.ps1 owns provisioning), starts the decision
#  stack (llama-server :8081 + wire :8090), starts Chrome through your
#  proxy, runs the demo with upstream's independent verification, then
#  cleans up what it started. A wire already answering on $SvcPort is
#  reused. The demo itself runs with api_calls=0 -- the text helper is
#  not needed because the skills layer reads field values straight out
#  of the goal.
#
#  NOTE: ASCII only. PowerShell 5.1 reads .ps1 as ANSI (GBK) without a BOM.
# ==================================================================

$Repo          = "C:\Users\Administrator\openjev-ultrafast"
$ChromeExe     = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$ChromeProfile = "C:\chrome-cdp-test"
$PythonJev     = "C:\Users\Administrator\miniconda3\envs\jev\python.exe"
$ServeScript   = "$Repo\scripts\startlux_serve.ps1"
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

# Only ever kill Chrome processes that belong to this harness (they carry the
# CDP profile in their command line). The user's own browser must survive a
# demo run -- this used to be Stop-Process on every chrome.exe.
function Get-CdpChrome {
    Get-CimInstance Win32_Process -Filter "Name = 'chrome.exe'" -EA SilentlyContinue |
        Where-Object { $_.CommandLine -like "*chrome-cdp-test*" }
}
function Stop-CdpChrome {
    Get-CdpChrome | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -EA SilentlyContinue }
}

function Start-Chrome {
    Stop-CdpChrome
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
    foreach ($p in @($PythonJev, $ChromeExe, $ServeScript)) {
        if (-not (Test-Path $p)) { Die "missing: $p" }
    }
    Get-Content "$Repo\.env" -EA SilentlyContinue |
        Where-Object { $_ -match '^\s*[A-Za-z_][A-Za-z0-9_]*\s*=' } |
        ForEach-Object { $q = $_.Split('=',2); Set-Item -Path "env:$($q[0].Trim())" -Value $q[1].Trim() }

    # Text Helper: the value a TYPE_TEXT decision types. Default is the local
    # llama-server that already fronts the wire (:8081) -- one resident model,
    # zero cloud calls. groq/ollama stay behind an explicit -TextHelper, and
    # scripts/text_helper.ps1 is the only file that spells a cloud URL out.
    # The reachability gate is NOT here: a cold box brings :8081 up in Step 1,
    # so asserting before that would break the one-command cold start. It runs
    # right after the stack is answering instead.
    . "$Repo\scripts\text_helper.ps1"
    $helper = Resolve-TextHelper -Choice $TextHelper -LlamaPort $LlamaPort
    $env:TEXT_HELPER_BASE_URL = $helper.Url
    $env:TEXT_HELPER_MODEL    = $helper.Model
    $env:TEXT_HELPER_API_KEY  = $helper.Key
    $env:TEXT_HELPER_MAX_TOKENS = "128"; $env:TEXT_HELPER_MAX_RETRIES = "2"
    # Never let the harness go looking for a browser: pin it to the owned
    # chrome-cdp-test instance on 9222 (it would otherwise prefer whatever Chrome
    # has a default-profile DevToolsActivePort, i.e. the user's own browser).
    $env:BU_CDP_URL = "http://127.0.0.1:9222"

    # -- 1. proxy (warn only: the demo should still try) --------------------
    if ($ProxyUrl) {
        $pxAlive = $false
        try { $null = Invoke-WebRequest -Uri "https://api.groq.com" -Proxy $ProxyUrl -TimeoutSec 8 -UseBasicParsing; $pxAlive = $true } catch {}
        if ($pxAlive) { Ok "proxy $ProxyUrl answering" }
        else { Warn "proxy $ProxyUrl not answering -- sites that need it (wikipedia) will fail to load" }
    }

    # -- 2. decision stack --------------------------------------------------
    # The StartLux wire (:8090) fronts llama-server (:8081). Reuse it when it
    # answers; otherwise scripts\startlux_serve.ps1 provisions any missing
    # artifacts (2GB GGUF, llama.cpp CUDA build) and brings the whole stack up.
    Log "Step 1: decision stack (StartLux wire on $SvcPort)"
    $script:startedStack = $false
    if (Wait-Url "http://127.0.0.1:$SvcPort/health" 3 1) {
        Ok "wire already answering on $SvcPort -- reusing"
    } else {
        $gpu = [int]((nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits) -replace '\s','')
        Log "  GPU in use = ${gpu}MB"
        if ($gpu -gt 500) { Die "GPU busy (${gpu}MB) and no wire on $SvcPort. Stop the other model first -- two model services do not fit in 8GB." }
        Log "  starting llama-server + wire (downloads artifacts on a cold box; first time can take minutes)..."
        $svcProc = Start-Process -FilePath "powershell" `
            -ArgumentList @("-NoProfile","-ExecutionPolicy","Bypass","-File",$ServeScript,"-ProxyUrl",$ProxyUrl) `
            -WindowStyle Hidden -PassThru
        $script:startedStack = $true
        if (-not (Wait-Url "http://127.0.0.1:$SvcPort/health" 900 5)) {
            foreach ($lf in @("startlux-llama.err.log","startlux-wire.err.log")) {
                Get-Content "$Repo\logs\$lf" -Tail 10 -EA SilentlyContinue | ForEach-Object { Log "  | $lf : $_" }
            }
            Die "wire not healthy on $SvcPort after 900s (see logs\startlux-*.err.log)"
        }
        Ok "wire ready"
    }

    # -- 3. Chrome --------------------------------------------------------
    # The stack is up, so the helper endpoint named in Step 0 must answer now;
    # a dead helper would show up as steps=0 + status=blocked in the demo output.
    Assert-TextHelper $helper
    Log "Step 2: start Chrome"
    if (-not (Start-Chrome)) { Die "CDP 9222 not ready" }
    Ok "CDP ready"

    # -- 4. run -----------------------------------------------------------
    Log "Step 3: run the demo -> $Out"
    Set-Env @{ "DECIDER_MODE" = "typesafe"; "TYPESAFE_BASE_URL" = "http://127.0.0.1:$SvcPort/v1/systemone";
               "TYPESAFE_API_KEY" = "local"; "PYTHONUTF8" = "1"
               "TEXT_HELPER_BASE_URL" = $helper.Url; "TEXT_HELPER_MODEL" = $helper.Model
               "TEXT_HELPER_API_KEY" = $helper.Key; "HTTPX_PROXY" = $ProxyUrl }
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
        Log "Cleanup: stopping CDP Chrome (and the stack if we started it)"
        Get-Process python -EA SilentlyContinue | Where-Object { $_.Id -ne $PID } | ForEach-Object {
            try { $cl = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)" -EA Stop).CommandLine
                  if ($cl -match "run_flights|browser_harness") { Stop-Process -Id $_.Id -Force -EA SilentlyContinue } } catch {}
        }
        Stop-CdpChrome
        Start-Sleep 5
        $left = (Get-CdpChrome | Measure-Object).Count
        Log "Verify: cdp-chrome=$left (must be 0; the user's own Chrome is never touched)"
        if ($left -ne 0) { $exitCode = 1 }
    } else {
        Log "KeepOpen: Chrome stays up. Close it yourself when done:"
        Log "  Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | Where-Object { \$_.CommandLine -like '*chrome-cdp-test*' } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force }"
    }
    if ($startedStack -and -not $KeepService) {
        Log "Cleanup: stopping llama-server + wire we started (use -KeepService to skip)"
        Get-Process llama-server -EA SilentlyContinue | Stop-Process -Force -EA SilentlyContinue
        Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -EA SilentlyContinue |
            Where-Object { $_.CommandLine -like "*gguf_server*" } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -EA SilentlyContinue }
    } elseif ($startedStack) {
        Log "KeepService: llama-server + wire stay up on $SvcPort"
    }
}

exit $exitCode