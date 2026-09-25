$ErrorActionPreference = 'Continue'
$env:HTTP_PROXY = 'http://127.0.0.1:2080'
$env:HTTPS_PROXY = 'http://127.0.0.1:2080'
& 'C:\Users\Administrator\miniconda3\Scripts\conda.exe' create -n jev python=3.12 -y 2>&1 | Select-Object -Last 3
