# M1 20-task eval: M4b adapter vs baseline 13/20 (reports/m1-decider2b-v0927-m15c.json)
# Prereq: m4a/serve_m4b.py already serving on :8000 (M4B_MODEL_ID must match -ModelId).
param(
    [string]$Tag = "m4b-r1",
    [string]$ModelId = "decider-2b-m4b"
)
$ErrorActionPreference = 'Continue'
Set-Location C:\Users\Administrator\openjev-ultrafast

# Decision = local adapter (OpenAI-compatible)
$env:DECIDER_MODE        = "openai"
$env:DECIDER_2B_BASE_URL = "http://127.0.0.1:8000/v1"
$env:DECIDER_2B_MODEL    = $ModelId
$env:DECIDER_2B_API_KEY  = "local"
$env:DECIDER_MAX_TOKENS  = "256"

# Text helper = Groq (TYPE_TEXT values; adapter was not trained for it)
$env:TEXT_HELPER_BASE_URL = "https://api.groq.com/openai/v1"
$env:TEXT_HELPER_MODEL    = "openai/gpt-oss-120b"
$env:TEXT_HELPER_API_KEY  = $env:GROQ_API_KEY

$env:HF_HUB_OFFLINE   = "1"
$env:TRANSFORMERS_OFFLINE = "1"
$env:PYTHONUTF8       = "1"
$env:HTTPX_PROXY      = "http://127.0.0.1:2080"

& "C:\Users\Administrator\miniconda3\envs\jev\python.exe" -m m1.run_tasks `
    --tasks m1\tasks.jsonl `
    --log-dir "logs\m1-$Tag" `
    --report "reports\m1-$Tag.json" `
    --task-delay 3
