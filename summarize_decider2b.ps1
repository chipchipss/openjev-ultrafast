$r = Get-Content "C:\Users\Administrator\openjev-ultrafast\reports\m1-decider2b.json" | ConvertFrom-Json
$lines = @()
$lines += "M1 decider2b 20-task run summary (COMPILE=0 FP8=0, model.py timeout=90, PYTHONUTF8=1)"
$lines += "Total=$($r.summary.total)  Pass=$($r.summary.pass)  Fail=$($r.summary.fail)  Unknown=$($r.summary.unknown)  Error=$($r.summary.error)"
$lines += "Quadrants: $(($r.summary.quadrants | ConvertTo-Json -Compress))"
$lines += "FailureModes: $(($r.summary.failure_modes | ConvertTo-Json -Compress))"
$lines += "Acceptance: $((($r.acceptance.passed)))"
$lines += "AcceptanceNotes: $(($r.acceptance.notes -join ' ; '))"
$lines += ""
$lines += "Per-task:"
foreach ($t in $r.results) {
    if ($t.error) {
        $lines += ("{0,-6} ERROR: {1}" -f $t.task_id, $t.error)
    } else {
        $lines += ("{0,-6} result={1} quadrant={2} mode={3}" -f $t.task_id, $t.result.result, $t.result.quadrant, $t.result.failure_mode)
    }
}
$out = "C:\Users\Administrator\openjev-ultrafast\m4a\_decider2b_run.log"
$lines | Set-Content -Path $out -Encoding utf8
Write-Output ("Wrote " + $lines.Count + " lines to " + $out)
