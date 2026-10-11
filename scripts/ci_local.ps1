param(
    [switch]$Full,                 # smoke(tier1) + 3 freeze rounds + one real regression batch
    [ValidateSet(19, 50, 100)][int]$Tasks = 50,
    [int]$MinPass = 43,            # floor for the 50-row set: b24/b26 = 45/44, b25/b27 = 43/44 -- see m2/real-log.md
    [double]$MaxWallMinutes = 14,  # gated build measured b27 = 9.5 min (b26 = 24.9); over 14 means the gate never skipped or the stack slowed
    [int]$SvcPort = 8090,
    [string]$TasksFile = ""
)
$ErrorActionPreference = "Stop"
# ASCII only (PowerShell 5.1 reads .ps1 as ANSI without a BOM).
#
# L3 "CI automation" on this project's own terms: one unattended command on the box that owns the GPU,
# the model and the browser, writing a machine-checkable verdict. GitHub-hosted CI is NOT what
# this is -- and the reason is measured, not stylistic: the decision wire is a local
# llama.cpp + StartLux-Decision-2B GGUF (2.7 GB, CUDA), and every batch needs a real Chrome
# through the operator's proxy. A runner without those cannot reproduce the numbers this repo
# is allowed to cite (hard rule: every number maps to reports/*.json).
#
# Tiers:
#   default         : smoke.ps1 tier 1 (offline suites, no browser/model)  -- cheap, always safe
#   -Full           : smoke tier1+tier2, three freeze rounds (19 tasks), one regression batch,
#                     then m2/batch_audit.py checks the pre-registered criteria, verdict to JSON.
#
# Failure semantics we keep from the batches: a round/batch that wrote no report is BLOCKED
# (exit 3), not a pass and not a score.

$Repo = "C:\Users\Administrator\openjev-ultrafast"
$PythonJev = "C:\Users\Administrator\miniconda3\envs\jev\python.exe"
$Stamp = Get-Date -Format "MMdd-HHmm"
$Verdict = "$Repo\reports\ci-$Stamp.json"
$LogDir = "$Repo\logs\ci-$Stamp"
New-Item -ItemType Directory -Force $LogDir | Out-Null

function Die($m, $code) { Write-Host "CI FAIL: $m" -ForegroundColor Red; exit ($(if ($code) { $code } else { 1 })) }
function Log($m) { Write-Host "[ci] $m" -ForegroundColor Cyan }

# ---------- tier 1 ----------
Log "smoke tier 1 (offline suites)"
& "$Repo\scripts\smoke.ps1"
if ($LASTEXITCODE -ne 0) { Die "smoke tier 1 not green" $LASTEXITCODE }

if (-not $Full) {
    Log "tier 1 green. Pass -Full for the freeze + regression ladder."
    exit 0
}

if (-not $TasksFile) {
    $TasksFile = switch ($Tasks) {
        19  { "$Repo\m1\tasks-laya-19.jsonl" }
        50  { "$env:TEMP\tasks_b19_50.jsonl" }
        100 { "$Repo\m2\tasks_real_100.jsonl" }
    }
}
if (-not (Test-Path $TasksFile)) { Die "task file missing: $TasksFile" }

# ---------- tier 2 + freeze x3 + regression batch ----------
Log "smoke tier 2 (live 5-task gate)"
& "$Repo\scripts\smoke.ps1" -Live -SvcPort $SvcPort
if ($LASTEXITCODE -ne 0) { Die "smoke tier 2 not green" $LASTEXITCODE }

for ($r = 1; $r -le 3; $r++) {
    Log "freeze round $r / 3"
    & "$Repo\scripts\start_owned_chrome.ps1" | Out-Null
    & "$Repo\scripts\startlux_serve.ps1" -SkipEnsure > "$LogDir\stack-r$r.log" 2>&1
    & "$Repo\run_baseline_19.ps1" -NoService -SvcPort $SvcPort > "$LogDir\freeze-r$r.log" 2>&1
    $rep = Get-ChildItem "$Repo\reports\m1-baseline-*.json" | Sort-Object LastWriteTime | Select-Object -Last 1
    if (-not $rep) { Die "freeze round $r wrote no report (blocked)" 3 }
    $v = (Get-Content $rep.FullName -Raw -Encoding UTF8 | ConvertFrom-Json)
    $pass = @($v.results | Where-Object { $_.result.result -eq "PASS" }).Count
    $fp = @($v.results | Where-Object { $_.result.quadrant -eq "false_positive" }).Count
    Log ("  round {0}: {1}/19 PASS, fp={2}  ({3})" -f $r, $pass, $fp, $rep.Name)
    if ($fp -ne 0) { Die "round $r produced a false_positive (hard line fp=0)" }
}

Log "regression batch ($Tasks tasks)"
& "$Repo\scripts\start_owned_chrome.ps1" | Out-Null
& "$Repo\scripts\startlux_serve.ps1" -SkipEnsure > "$LogDir\stack-batch.log" 2>&1
$Tag = "ci-$Stamp"
& "$Repo\scripts\run_one.ps1" -TasksFile $TasksFile -Tag $Tag -SvcPort $SvcPort > "$LogDir\batch.log" 2>&1
$breport = Get-ChildItem "$Repo\reports\$Tag-*.json" -EA SilentlyContinue | Sort-Object LastWriteTime | Select-Object -Last 1
if (-not $breport) { Die "batch wrote no report (blocked)" 3 }

$b = Get-Content $breport.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
$pass = @($b.results | Where-Object { $_.result.result -eq "PASS" }).Count
$fp = @($b.results | Where-Object { $_.result.quadrant -eq "false_positive" }).Count
$err = @($b.results | Where-Object { $_.error -or $_.result.error }).Count
$logdir = "$Repo\logs\$($breport.BaseName)"
$wall = 0
if (Test-Path $logdir) {
    $f = Get-ChildItem $logdir -Filter *.jsonl
    if ($f.Count -gt 1) {
        $wall = ((($f | Sort-Object LastWriteTime | Select-Object -Last 1).LastWriteTime - `
                 ($f | Sort-Object LastWriteTime | Select-Object -First 1).LastWriteTime)).TotalMinutes
    }
}

# ---------- verdict ----------
$v = [ordered]@{
    stamp = $Stamp; tasks = $Tasks; report = $breport.Name
    pass = $pass; false_positive = $fp; error_rows = $err
    wall_minutes = [math]::Round($wall, 1)
    thresholds = @{ min_pass = $MinPass; max_wall_minutes = $MaxWallMinutes; fp = 0; error_rows = 0 }
    passed = ($pass -ge $MinPass -and $fp -eq 0 -and $err -eq 0 -and $wall -le $MaxWallMinutes)
}
$v | ConvertTo-Json | Set-Content -Path $Verdict -Encoding UTF8
Log ("verdict -> {0}  pass={1}/{2} fp={3} error={4} wall={5} min" -f `
    $Verdict, $pass, $Tasks, $fp, $err, [math]::Round($wall, 1))
if (-not $v.passed) { Die "regression below thresholds (see $Verdict)" }
Log "CI green"
