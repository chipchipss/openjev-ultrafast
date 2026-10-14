param(
    [switch]$Full,                 # per-change tier: smoke(tier1) + 3 freeze rounds + one regression batch
    # Two tiers, because one command cannot serve both jobs (L3 re-scope; m2/real-log.md):
    #   perchange : the ladder a human waits on -- freeze x3 + ONE 100-row batch, <= 30 min
    #   nightly   : the ladder nobody waits on -- the SAME 100-row corpus over N rounds, thresholds
    #               per round. "300 rows" on this box means 3 x 100, not a 300-task corpus: there is
    #               none, and inventing 200 unverified tasks would be a fake reading waiting to happen.
    [ValidateSet('perchange', 'nightly')][string]$Tier = 'perchange',
    [int]$Rounds = 3,              # nightly only
    # Thresholds derived, not chosen. Four readings on m2/tasks_real_100.jsonl:
    # b33=59, b34=61, b35=68, b36=65 (min 59, median 63, max 68); wall 20.7/20.5/19.4/18.1 min.
    # A floor ABOVE the observed minimum would fail a build that is not broken -- b33 IS 59.
    # A floor BELOW it makes the line meaningless. So the floor is the observed MIN.
    # The +/-1 rule from the 19-task freeze set does NOT transfer to real sites (spread 9).
    [int]$MinPassPerRound = 59,
    [double]$MaxRoundMinutes = 30,   # the L3 criterion itself (not measured here): observed worst 20.7
    [double]$MaxTotalMinutes = 95,   # 3 x observed worst + stack resets; a budget, judged at the end
    [ValidateSet(19, 50, 100)][int]$Tasks = 50,
    # Same class of bug as the wall budget: one number cannot serve both ladders.
    # 43 is the 50-row floor (b24/b26 = 45/44, b25/b27 = 43/44); the 100-row observed minimum is 59
    # (b33=59, b34=61, b35=68, b36=65) -- applying 43 to a 100-row batch would let a broken build pass.
    # 0 = "pick by -Tasks".
    [int]$MinPass = 0,
    # Wall budget follows the TASK COUNT, it is not one number for both ladders:
    # 14 min is the 50-row reading (b27 = 9.5); a 100-row batch on the same box measured
    # 18.1-24.1 min (b33-b41 + the nightly bank), so the same 14 would fail a healthy build.
    # 0 = "pick by -Tasks" (100 -> 30 = the L3 per-change criterion itself; 50 -> 14).
    [double]$MaxWallMinutes = 0,
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

function Write-JsonNoBom($path, $obj) {
    # PS 5.1's `Set-Content -Encoding UTF8` always emits a BOM, and a BOM'd .json breaks
    # `json.load(open(p, encoding='utf-8'))` -- the same trap that already cost this repo a
    # batch (m1/run_tasks.py had to start reading tasks with utf-8-sig). The verdict file is
    # machine-read, so it gets written without one.
    [IO.File]::WriteAllText($path, $obj, (New-Object Text.UTF8Encoding($false)))
}

function Die($m, $code) { Write-Host "CI FAIL: $m" -ForegroundColor Red; exit ($(if ($code) { $code } else { 1 })) }
function Log($m) { Write-Host "[ci] $m" -ForegroundColor Cyan }
# #88: the freeze stage's completeness rule lives in its own file so a stored report can be
# fed back as a witness (scripts/ci_freeze_gate.ps1) and the offline suite reads the same thing.
. "$Repo\scripts\ci_freeze_gate.ps1"

# ---------- tier 1 ----------
Log "smoke tier 1 (offline suites)"
& "$Repo\scripts\smoke.ps1"
if ($LASTEXITCODE -ne 0) { Die "smoke tier 1 not green" $LASTEXITCODE }

if ($MinPass -eq 0) {
    $MinPass = $(if ($Tasks -ge 100) { 59 } else { 43 })
}
if ($MaxWallMinutes -eq 0) {
    # The threshold follows the task count; one number for both ladders measures 100 rows with a 50-row ruler.
    $MaxWallMinutes = $(if ($Tasks -ge 100) { 30 } else { 14 })
}

if ($Tier -eq 'nightly') {
    # ---------- nightly tier: N rounds of the SAME corpus, thresholds per round ----------
    # What it looks for is drift and the floor, not a new score: four readings on this corpus already
    # span 9 points, so a single nightly number means nothing on its own (m2/real-log.md, calibration).
    if (-not $TasksFile) { $TasksFile = "$Repo\m2\tasks_real_100.jsonl" }
    if (-not (Test-Path $TasksFile)) { Die "task file missing: $TasksFile" }
    $t0 = Get-Date
    $readings = @()        # NOT $rounds: PowerShell names are case-insensitive, and $rounds would
                            # collide with the [int]$Rounds parameter (array -> Int32 conversion error)
    for ($r = 1; $r -le $Rounds; $r++) {
        & "$Repo\scripts\start_owned_chrome.ps1" | Out-Null
        $Tag = "nightly-$Stamp-r$r"
        & "$Repo\scripts\run_one.ps1" -TasksFile $TasksFile -Tag $Tag -SvcPort $SvcPort > "$LogDir\round-r$r.log" 2>&1
        $rep = Get-ChildItem "$Repo\reports\$Tag-*.json" -EA SilentlyContinue | Sort-Object LastWriteTime | Select-Object -Last 1
        if (-not $rep) { Die "nightly round $r wrote no report -- blocked, not a pass and not a fail" 3 }
        $b = Get-Content $rep.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
        $pass = @($b.results | Where-Object { $_.result.result -eq 'PASS' }).Count
        $fp = @($b.results | Where-Object { $_.result.quadrant -eq 'false_positive' }).Count
        $err = @($b.results | Where-Object { $_.error -or $_.result.error }).Count
        $wall = 0
        $fs = @(Get-ChildItem "$Repo\logs\$($rep.BaseName)" -Filter *.jsonl -EA SilentlyContinue)
        if ($fs.Count -gt 1) {
            $wall = [math]::Round((($fs | Sort-Object LastWriteTime | Select-Object -Last 1).LastWriteTime - `
                                  ($fs | Sort-Object LastWriteTime | Select-Object -First 1).LastWriteTime).TotalMinutes, 1)
        }
        $readings += [ordered]@{ round = $r; report = $rep.Name; pass = $pass; false_positive = $fp
                               error_rows = $err; wall_minutes = $wall }
        Log ("  nightly round {0}: pass={1} fp={2} error={3} wall={4} min  ({5})" -f $r, $pass, $fp, $err, $wall, $rep.Name)
        if ($fp -ne 0) { Die ("nightly round {0}: false_positive>0 (hard line fp=0)" -f $r) }
        if ($err -ne 0) { Die ("nightly round {0}: error>0" -f $r) }
        if ($pass -lt $MinPassPerRound) { Die ("nightly round {0}: pass={1} below the observed-min floor {2}" -f $r, $pass, $MinPassPerRound) }
        if ($wall -gt $MaxRoundMinutes) { Log ("  round {0} exceeded {1} min -- recorded as a reading; slowness is a link shape, not a verdict" -f $r, $MaxRoundMinutes) }
    }
    $total = [math]::Round(((Get-Date) - $t0).TotalMinutes, 1)
    $v = [ordered]@{ tier = 'nightly'; stamp = $Stamp; corpus = $TasksFile; rounds = $Rounds
                     thresholds = @{ min_pass_per_round = $MinPassPerRound; max_round_minutes = $MaxRoundMinutes
                                     max_total_minutes = $MaxTotalMinutes; false_positive = 0; error_rows = 0 }
                     total_minutes = $total; readings = $readings
                     passed = ($total -le $MaxTotalMinutes) }
    Write-JsonNoBom $Verdict ($v | ConvertTo-Json -Depth 5)
    Log ("nightly verdict -> {0}: {1} round(s), total {2} min (budget {3})" -f $Verdict, $Rounds, $total, $MaxTotalMinutes)
    if (-not $v.passed) { Die ("nightly exceeded its total budget: {0} min > {1}" -f $total, $MaxTotalMinutes) }
    Log "nightly green"
    exit 0
}

if (-not $Full) {
    Log "tier 1 green. -Full = per-change ladder; -Tier nightly = the same corpus over N rounds."
    exit 0
}

if (-not $TasksFile) {
    # The 50-row set used to be "$env:TEMP\tasks_b19_50.jsonl" (created 10-10 15:31, never
    # committed) -- every 44/50 and 43/50 reading in real-log cited that file, so a temp clean
    # would have made them unreproducible. Pinned as m2/tasks_real_50.jsonl (sha1 457dea2e...):
    # byte-identical copy, 50 ids, and object-for-object the first 50 rows of tasks_real_100.
    $TasksFile = switch ($Tasks) {
        19  { "$Repo\m1\tasks-laya-19.jsonl" }
        50  { "$Repo\m2\tasks_real_50.jsonl" }
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

    # #88: a round that wrote FEWER ROWS than the task set is BLOCKED (exit 3) -- not a pass,
    # not a score. Before this the stage only died on "no report at all" and on fp != 0, so the
    # 17-row round of 2026-10-14 21:19 (two rows refused by the egress preflight) ran on as green.
    # A present-but-FAIL row is deliberately NOT handled here: that is a score red and must stay
    # readable as one (m2/real-log.md, #16/#78/#84a are the reason the two endings stay apart).
    $part = "$Repo\reports\" + ($rep.BaseName -replace '^m1-', '')
    $gap = Get-FreezeRowGap -ReportPath $rep.FullName -TaskSetPath "$Repo\m1\tasks-laya-19.jsonl" -PartDir $part
    if ($gap) {
        $blocked = [ordered]@{
            stamp = $Stamp; stage = 'freeze'; round = $r
            rows = $gap.rows; expected = $gap.expected
            missing_ids = $gap.missing_ids; missing_causes = $gap.missing_causes
            passed = $false
            reason = 'freeze round wrote fewer rows than the task set -- BLOCKED, not a pass and not a score'
        }
        Write-JsonNoBom $Verdict ($blocked | ConvertTo-Json -Depth 6)
        $why = ($gap.missing_causes.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join ','
        $msg = "freeze round {0}: {1}/{2} rows written; missing {3} ({4}) -- BLOCKED (verdict: {5})" -f `
               $r, $gap.rows, $gap.expected, ($gap.missing_ids -join ','), $why, $Verdict
        Die $msg 3
    }
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
Write-JsonNoBom $Verdict ($v | ConvertTo-Json)
Log ("verdict -> {0}  pass={1}/{2} fp={3} error={4} wall={5} min" -f `
    $Verdict, $pass, $Tasks, $fp, $err, [math]::Round($wall, 1))
if (-not $v.passed) { Die "regression below thresholds (see $Verdict)" }
Log "CI green"
