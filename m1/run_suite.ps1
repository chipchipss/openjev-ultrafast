# Run the 20-task suite (m1/tasks.jsonl) on our stack, with the same env the
# flights runner uses. Skills stay on (M16_SKILLS=1) unless the caller overrides.
param(
    [string]$Report = "reports/m1-skills.json",
    [string]$Tasks  = "m1/tasks.jsonl",
    [double]$Delay  = 0,
    # startlux = the llama-server that already serves the decisions, so the run
    # keeps exactly one resident model and zero cloud. groq/deepseek are opt-in
    # only -- this file used to hard-code groq as the default, which made every
    # suite run leak the text values to the cloud.
    [string]$TextHelper = "startlux",
    [int]$LlamaPort = 8081
)
Set-Location C:\Users\Administrator\openjev-ultrafast
if (-not $env:DECIDER_MODE) { $env:DECIDER_MODE = "typesafe" }
$env:TYPESAFE_BASE_URL      = "http://127.0.0.1:8000/v1/systemone"
# Helper endpoints live in one file (scripts/text_helper.ps1); a cloud choice is
# only reachable by naming it, and an unreachable helper stops the run instead of
# measuring a silently crippled agent (steps=0 + status=blocked is what a dead
# helper looks like in a report).
$Repo = "C:\Users\Administrator\openjev-ultrafast"
. "$Repo\scripts\text_helper.ps1"
$helper = Resolve-TextHelper -Choice $TextHelper -LlamaPort $LlamaPort
Assert-TextHelper $helper
$env:TEXT_HELPER_BASE_URL   = $helper.Url
$env:TEXT_HELPER_MODEL      = $helper.Model
$env:TEXT_HELPER_API_KEY    = $helper.Key
$env:TEXT_HELPER_MAX_TOKENS = "128"
$env:TEXT_HELPER_MAX_RETRIES = "2"
# Pin the harness to an owned CDP Chrome on 9222; without it browser_harness scans
# Chrome's default profile first and drives the user's own browser when that one
# allows remote debugging. Start it first (scripts/run_one.ps1 does), or the run
# fails closed with no-browser instead of silently using a foreign window.
$env:BU_CDP_URL = "http://127.0.0.1:9222"
$env:PYTHONUTF8             = "1"
& "C:\Users\Administrator\miniconda3\envs\jev\python.exe" -m m1.run_tasks `
    --tasks $Tasks --log-dir logs --report $Report --task-delay $Delay
