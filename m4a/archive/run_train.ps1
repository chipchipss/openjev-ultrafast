$ErrorActionPreference = 'Continue'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
Set-Location 'C:\Users\Administrator\openjev-ultrafast\m4a'
& 'C:\Users\Administrator\miniconda3\envs\m4a\python.exe' train.py
