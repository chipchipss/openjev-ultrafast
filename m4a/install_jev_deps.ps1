$ErrorActionPreference = 'Continue'
$env:HTTP_PROXY = 'http://127.0.0.1:2080'
$env:HTTPS_PROXY = 'http://127.0.0.1:2080'
$py = 'C:/Users/Administrator/miniconda3/envs/jev/python.exe'

Write-Host "=== pip install httpx browser-harness ==="
& $py -m pip install -q "httpx[http2]" "browser-harness==0.1.13"
if ($LASTEXITCODE -ne 0) { Write-Error "pip install failed"; exit 1 }

Write-Host "=== playwright install chromium ==="
& $py -m playwright install chromium
if ($LASTEXITCODE -ne 0) { Write-Error "playwright install failed"; exit 1 }

Write-Host "=== verify ==="
& $py -c "import httpx, browser_harness, playwright; print('httpx', httpx.__version__); print('browser_harness OK'); print('playwright', playwright.__version__)"
