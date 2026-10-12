# Start ONLY our own headless CDP Chrome (profile chrome-cdp-test) for zero-model probes.
# Same flags as scripts/run_one.ps1; refuses if :9222 belongs to a browser we didn't start.
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\chrome_guard.ps1"   # browser ownership is answered in ONE file
Stop-OwnedChrome
Start-Sleep 2
Start-Process "C:\Program Files\Google\Chrome\Application\chrome.exe" `
    "--headless=new --remote-debugging-port=9222 --user-data-dir=C:\chrome-cdp-test --no-first-run --no-default-browser-check --proxy-server=http://127.0.0.1:2080"
foreach ($i in 1..30) {
    Start-Sleep 1
    try { Invoke-RestMethod "http://127.0.0.1:9222/json/version" -TimeoutSec 2 | Out-Null; break } catch {}
}
# This one stays deliberately narrow: it asks "did the profile THIS script just launch come up",
# not "is it ours". Using the guard's marker list here would make the check nod along while a
# different owned profile holds :9222 -- that is the connect-side shape of the P0 incident.
$mine = @(Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" -EA SilentlyContinue |
            Where-Object { $_.CommandLine -like "*chrome-cdp-test*" })
if ($mine.Count -eq 0) { Write-Host "CDP chrome (chrome-cdp-test) is NOT running"; exit 1 }
Write-Host "owned cdp chrome up: $($mine.Count) procs on :9222"
