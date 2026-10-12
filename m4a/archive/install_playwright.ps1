$ErrorActionPreference = 'Continue'
$env:HTTP_PROXY = 'http://127.0.0.1:2080'
$env:HTTPS_PROXY = 'http://127.0.0.1:2080'
$py = 'C:/Users/Administrator/miniconda3/envs/jev/python.exe'

Write-Host "=== playwright install chromium ==="
& $py -m pip install -q playwright
if ($LASTEXITCODE -ne 0) { Write-Error "playwright pip failed"; exit 1 }
& $py -m playwright install chromium
if ($LASTEXITCODE -ne 0) { Write-Error "playwright browser install failed"; exit 1 }

Write-Host "=== verify all ==="
& $py -c "import httpx, browser_harness, playwright; print('httpx', httpx.__version__); print('browser_harness OK'); print('playwright', playwright.__version__)"
