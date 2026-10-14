#Requires -Version 5
# #88: a freeze round that wrote FEWER ROWS than the 19-task set is BLOCKED (exit 3).
#
# Measured defect (m2/real-log.md, "L2 2026-10-14 late night"): ci_local's freeze stage only
# Died on "no report at all" and on fp != 0. Round 1 of the 21:19 ladder merged 17 rows
# (reports/m1-baseline-1014-2122.json, missing n001/n002 -- both refused by the egress
# preflight, which is correct behaviour) and the ladder printed "round 1: 17/19 PASS, fp=0"
# and carried on. Rule 2 of this project's own discipline ("freeze 19/19 x3 on one build
# before a real batch") had no script enforcing it.
#
# Boundary this function does NOT cross: missing ROWS = BLOCKED; a present-but-FAIL row is a
# SCORE red and stays visible as one. Collapsing the two would make "the link ate two rows"
# look identical to "capability lost a point" -- the exact confusion #16/#78/#84a exist to undo.
#
# Kept ASCII on purpose: PowerShell 5.1 reads a BOM-less .ps1 as ANSI, so a non-ASCII byte can
# land as 0x60 (backtick = line continuation) and silently swallow the following line
# (m2/real-log.md, 2026-10-11).
#
# The judgement is a pure function so ci_local.ps1 and tests/test_ci_freeze_gate.py read the
# same thing, and so a stored report can be fed back directly as a witness:
#   . scripts\ci_freeze_gate.ps1
#   Get-FreezeRowGap -ReportPath reports\m1-baseline-1014-2122.json `
#       -TaskSetPath m1\tasks-laya-19.jsonl -PartDir reports\baseline-1014-2122

function Get-FreezeRowGap {
    param(
        [Parameter(Mandatory = $true)][string]$ReportPath,
        [Parameter(Mandatory = $true)][string]$TaskSetPath,
        [string]$PartDir = ""
    )
    if (-not (Test-Path $ReportPath)) { throw "no merged report to judge: $ReportPath" }
    if (-not (Test-Path $TaskSetPath)) { throw "no task set to compare against: $TaskSetPath" }

    $v = Get-Content $ReportPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $rows = @($v.results)

    $ids = @()
    foreach ($line in (Get-Content $TaskSetPath -Encoding UTF8)) {
        if (-not $line.Trim()) { continue }
        $ids += (@($line | ConvertFrom-Json).task_id)
    }

    $done = @($rows | ForEach-Object { $_.task_id })
    $missing = @($ids | Where-Object { $done -notcontains $_ })
    if ($missing.Count -eq 0) { return $null }

    # Classify each missing row instead of writing "rows went missing". The refusal message
    # the egress gate prints lands in the round's failed/ dumps, which are NOT tracked, so
    # this is the only place it can still be read.
    $causes = [ordered]@{}
    foreach ($m in $missing) {
        $label = 'no_dump'
        if ($PartDir) {
            $dump = Join-Path $PartDir ("failed\btask_{0}_err.log" -f $m)
            if (Test-Path $dump) {
                $txt = Get-Content $dump -Raw -Encoding UTF8
                if ($txt -match '\[preflight\]') { $label = 'preflight' } else { $label = 'crash_or_unknown' }
            }
        }
        $causes[$m] = $label
    }

    return [ordered]@{
        rows           = $rows.Count
        expected       = $ids.Count
        missing_ids    = @($missing)
        missing_causes = $causes
    }
}
