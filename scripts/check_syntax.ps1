$tokens = $null; $errors = $null
[System.Management.Automation.Language.Parser]::ParseFile(
    'C:\Users\Administrator\openjev-ultrafast\run_baseline_19.ps1', [ref]$tokens, [ref]$errors) | Out-Null
if ($errors.Count) { $errors | ForEach-Object { Write-Host $_.Message } ; exit 1 }
Write-Host 'syntax OK'
