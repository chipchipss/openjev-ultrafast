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
$Repo = "C:\Users\Administrator\openjev-ultrafast"
. "$Repo\scripts\text_helper.ps1"

$env:DECIDER_MODE        = "typesafe"
$env:TYPESAFE_BASE_URL   = "http://127.0.0.1:8000/v1/systemone"
$env:TYPESAFE_API_KEY    = "local"

# Zero-cloud hard line (2026-10-08): this runner used to reach for Groq by
# default, so a bare invocation sent every TYPE_TEXT value to a cloud model
# while the reports kept api_calls=0 -- that counter only counts the teacher
# path. The endpoint has to be named; startlux and local are on-box, groq and
# deepseek are CLOUD and break the rule (see scripts/text_helper.ps1).
$helper = Resolve-TextHelper -Choice $env:JEV_TEXT_HELPER
Assert-TextHelper $helper
$env:TEXT_HELPER_BASE_URL = $helper.Url
$env:TEXT_HELPER_MODEL    = $helper.Model
$env:TEXT_HELPER_API_KEY  = $helper.Key

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
