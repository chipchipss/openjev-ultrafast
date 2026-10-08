$ErrorActionPreference = 'Stop'
$Repo = 'C:\Users\Administrator\openjev-ultrafast'
$fail = 0
foreach ($name in @('run_baseline_19.ps1', 'run_demo.ps1', 'scripts\run_one.ps1')) {
    $p = Join-Path $Repo $name
    $tokens = $null; $errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($p, [ref]$tokens, [ref]$errors) | Out-Null
    if ($errors.Count) {
        $fail = 1
        Write-Host "SYNTAX FAIL: $name"
        $errors | ForEach-Object { Write-Host ("  line {0}: {1}" -f $_.Extent.StartLineNumber, $_.Message) }
    } else {
        Write-Host "syntax OK: $name"
    }
}
exit $fail
