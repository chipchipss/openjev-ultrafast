# M1 20-task eval on the NATIVE-format fine-tuned decider, served by decider.serve.
# This is the SAME path as the 13/20 baseline (reports/m1-decider2b-v0927-m15c.json):
#   agent -> DECIDER_MODE=typesafe -> POST /v1/systemone -> decider serve.
# Prereq: decider serve already running on :8000 with DECIDER_MODEL=<merged native model>.
param(
    [string]$Tag = "m1-native-r1",
    [string]$Tasks = "m1\tasks.jsonl"
)
$ErrorActionPreference = 'Continue'
Set-Location C:\Users\Administrator\openjev-ultrafast

$env:DECIDER_MODE        = "typesafe"
$env:TYPESAFE_BASE_URL   = "http://127.0.0.1:8000/v1/systemone"
$env:TYPESAFE_API_KEY    = "local"

$env:TEXT_HELPER_BASE_URL = "https://api.groq.com/openai/v1"
$env:TEXT_HELPER_MODEL    = "openai/gpt-oss-120b"
$env:TEXT_HELPER_API_KEY  = $env:GROQ_API_KEY

$env:HF_HUB_OFFLINE       = "1"
$env:TRANSFORMERS_OFFLINE = "1"
$env:PYTHONUTF8           = "1"
$env:HTTPX_PROXY          = "http://127.0.0.1:2080"
$env:M15_ALL_KIND_STALE   = "1"
$env:M15_CYCLE_CUT        = "1"

& "C:\Users\Administrator\miniconda3\envs\jev\python.exe" -m m1.run_tasks `
    --tasks $Tasks `
    --log-dir "logs\$Tag" `
    --report "reports\$Tag.json" `
    --task-delay 3
