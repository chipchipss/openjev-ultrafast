param(
    # Live mini-batch also runs (needs the owned Chrome + the :8090 wire). Default: offline only.
    [switch]$Live,
    [int]$SvcPort = 8090,
    [string]$ProxyUrl = "http://127.0.0.1:2080"
)
$ErrorActionPreference = "Stop"
# ASCII only: PowerShell 5.1 reads .ps1 as ANSI (GBK) without a BOM.
#
# Plan doc 2.3 owed this gate: "any decision-layer / skills change must pass smoke before commit".
# It exists because of the drift incidents the project already logged (docs claiming numbers that
# no reports/*.json could back). Two tiers, deliberately different costs:
#
#   tier 1 (always, ~2 min, no browser, no model): every tests/test_*.py must report N/N.
#          A suite that prints anything other than "k/k passed" fails the gate -- including a
#          suite that crashes. Post-commit "no pre-fix counterpart" cases print a skip line and
#          still report k/k, so they do not weaken it.
#   tier 2 (-Live): 5 representative tasks, one per family that historically broke:
#          s005 floor-only navigation | n004 settle detection (SPA late render)
#          x001 + x002 safety (must stay true_success / correct_abandon, never false_positive)
#          r142 #59 arrival-stop + #60 modal guard (the row that used to burn 124 s)
#          Gate: every row PASS and false_positive = 0. Wall clock is NOT a criterion here.
#
# Ownership: refuses to start if a batch already holds the browser or the wire is down, so smoke
# can never run against someone else's Chrome or half a stack.

$Repo = "C:\Users\Administrator\openjev-ultrafast"
$PythonJev = "C:\Users\Administrator\miniconda3\envs\jev\python.exe"
$Stamp = Get-Date -Format "MMdd-HHmmss"

function Die($m) { Write-Host "  FAIL $m" -ForegroundColor Red; exit 1 }
function Log($m) { Write-Host $m -ForegroundColor Cyan }

# ---------- preflight: never piggyback on a run that owns the browser ----------
$busy = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" -EA SilentlyContinue |
    Where-Object { $_.CommandLine -like "*m1.run_tasks*" -or $_.CommandLine -like "*run_tasks.py*" })
if ($busy.Count -gt 0) {
    Die "a batch is already running (m1/run_tasks). One run owns the browser + :$SvcPort."
}

# ---------- tier 1: offline suites ----------
Log "== tier 1: offline suites (no browser, no model) =="
$bad = @()
Get-ChildItem -Path "$Repo\tests" -Filter "test_*.py" | Sort-Object Name | ForEach-Object {
    # A suite may write diagnostics to stderr (test_runner_egress_gate prints the preflight
    # message it is testing). With 2>&1 and ErrorActionPreference=Stop, PowerShell turns each
    # native stderr line into a terminating error and kills the whole tier mid-list, and a plain
    # "last line" would pick up that diagnostic instead of the verdict. So: let the suite own its
    # streams, then take the last line that IS a verdict. No verdict line = FAIL (crash included).
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $all = @(& $PythonJev -X utf8 $_.FullName 2>&1 | ForEach-Object { "$_" })
    $ErrorActionPreference = $prevEap
    $tail = ($all | Where-Object { $_ -match '^(\d+)/(\d+) passed$' } | Select-Object -Last 1)
    if (-not $tail) { $tail = "$($all | Select-Object -Last 1)" }
    $ok = $false
    if ($tail -match '^(\d+)/(\d+) passed$') { $ok = ([int]$Matches[1] -eq [int]$Matches[2]) }
    if (-not $ok) { $bad += "$($_.Name) -> $tail" }
    if ($ok) { Log ("  ok   {0,-36} {1}" -f $_.Name, $tail) } else { Log ("  FAIL {0,-36} {1}" -f $_.Name, $tail) }
}
if ($bad.Count -gt 0) { Die ("offline suites not green:`n  " + ($bad -join "`n  ")) }

if (-not $Live) {
    Log "== smoke: tier 1 green (pass -Live to also run the 5-task mini-batch) =="
    exit 0
}

# ---------- tier 2: live mini-batch ----------
try { Invoke-RestMethod "http://127.0.0.1:$SvcPort/health" -TimeoutSec 3 | Out-Null }
catch { Die "wire :$SvcPort is not listening -- run scripts\startlux_serve.ps1 first" }

$TaskFile = Join-Path $env:TEMP "smoke_$Stamp.jsonl"
$ids = @("s005", "n004", "x001", "x002", "r142")
# run_one.ps1 does the same search itself; we build the file here so a single report covers all 5.
$found = @{}
Get-ChildItem -Path @("$Repo\m1", "$Repo\m2") -Filter "tasks*.jsonl" -EA SilentlyContinue |
    ForEach-Object {
        Get-Content $_.FullName -Encoding UTF8 | ForEach-Object {
            $line = $_
            foreach ($id in $ids) {
                if (-not $found.ContainsKey($id) -and $line -match "`"task_id`"\s*:\s*`"$id`"") {
                    $found[$id] = $line
                }
            }
        }
    }
foreach ($id in $ids) {
    if (-not $found.ContainsKey($id)) { Die "task $id not found in m1/m2 task files (smoke list drifted from the corpus)" }
}
Set-Content -Path $TaskFile -Value ($ids | ForEach-Object { $found[$_] }) -Encoding UTF8

Log "== tier 2: live mini-batch ($($ids -join ' ')) =="
& "$Repo\scripts\run_one.ps1" -TasksFile $TaskFile -Tag "smoke-$Stamp" -SvcPort $SvcPort
$report = Get-ChildItem "$Repo\reports\smoke-$Stamp-*.json" | Sort-Object LastWriteTime | Select-Object -Last 1
if (-not $report) { Die "smoke produced no report (blocked, not a pass)" }

# The verdict is read from the report by the same audit script every batch uses -- not by
# re-parsing console text (rule: one measurement path, so smoke and a real batch cannot disagree).
& $PythonJev -X utf8 "$Repo\m2\smoke_gate.py" $report.FullName
if ($LASTEXITCODE -ne 0) { Die "smoke live gate: $LASTEXITCODE" }
Log "== smoke: both tiers green =="
