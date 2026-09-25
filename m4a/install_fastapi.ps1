$ErrorActionPreference = 'Continue'
$env:HTTP_PROXY = 'http://127.0.0.1:2080'
$env:HTTPS_PROXY = 'http://127.0.0.1:2080'
$py = 'C:/Users/Administrator/miniconda3/envs/m4a/python.exe'
& $py -m pip install -q fastapi uvicorn
if ($LASTEXITCODE -ne 0) { Write-Error "fastapi/uvicorn install failed"; exit 1 }
& $py -c "import fastapi, uvicorn; print('fastapi', fastapi.__version__, 'uvicorn', uvicorn.__version__)"
