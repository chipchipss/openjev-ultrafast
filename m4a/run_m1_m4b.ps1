# M1 20-task eval: M4b adapter vs baseline 13/20 (reports/m1-decider2b-v0927-m15c.json)
# Prereq: m4a/serve_m4b.py already serving on :8000 (M4B_MODEL_ID must match -ModelId).
param(
    [string]$Tag = "m4b-r1",
    [string]$ModelId = "decider-2b-m4b"
)
$ErrorActionPreference = 'Continue'
Set-Location C:\Users\Administrator\openjev-ultrafast
$Repo = "C:\Users\Administrator\openjev-ultrafast"
. "$Repo\scripts\text_helper.ps1"

# Decision = local adapter (OpenAI-compatible)
$env:DECIDER_MODE        = "openai"
$env:DECIDER_2B_BASE_URL = "http://127.0.0.1:8000/v1"
$env:DECIDER_2B_MODEL    = $ModelId
$env:DECIDER_2B_API_KEY  = "local"
$env:DECIDER_MAX_TOKENS  = "256"

# Text helper = Groq (TYPE_TEXT values; adapter was not trained for it)
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

$env:HF_HUB_OFFLINE   = "1"
$env:TRANSFORMERS_OFFLINE = "1"
$env:PYTHONUTF8       = "1"
$env:HTTPX_PROXY      = "http://127.0.0.1:2080"

& "C:\Users\Administrator\miniconda3\envs\jev\python.exe" -m m1.run_tasks `
    --tasks m1\tasks.jsonl `
    --log-dir "logs\m1-$Tag" `
    --report "reports\m1-$Tag.json" `
    --task-delay 3
