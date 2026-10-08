# Browser-ownership guard (P0, 2026-10-08).
#
# Every runner used to clear the field with a bare `Get-Process chrome | Stop-Process
# -Force`, which kills the user's own browser along with ours. Same hard line as the
# connect side (jev_ultrafast/browser.py::_assert_owned_browser): only processes whose
# command line carries one of OUR profile directories may be touched.
#
# Dot-source it:  . "$Repo\scripts\chrome_guard.ps1"
# Markers must stay in sync with OWNED_PROFILE_MARKERS in jev_ultrafast/browser.py.

$OwnedChromeProfiles = @("chrome-cdp-test", "chrome-jev-profile")
$OwnedChromePattern  = ($OwnedChromeProfiles -join "|")
$BrowserNames         = @("chrome.exe", "msedge.exe", "chromium.exe")

function Get-OwnedChrome {
    Get-CimInstance Win32_Process -EA SilentlyContinue |
        Where-Object { $BrowserNames -contains $_.Name -and $_.CommandLine -match $OwnedChromePattern }
}

function Stop-OwnedChrome {
    Get-OwnedChrome | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -EA SilentlyContinue }
}

# How many browsers are NOT ours -- the number a run must leave untouched.
function Get-ForeignBrowserCount {
    $ownedIds = @(Get-OwnedChrome | ForEach-Object { $_.ProcessId })
    @(Get-CimInstance Win32_Process -EA SilentlyContinue |
        Where-Object { $BrowserNames -contains $_.Name -and $ownedIds -notcontains $_.ProcessId }).Count
}
