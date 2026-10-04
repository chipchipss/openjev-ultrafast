# Run the 20-task suite (m1/tasks.jsonl) on our stack, with the same env the
# flights runner uses. Skills stay on (M16_SKILLS=1) unless the caller overrides.
param(
    [string]$Report = "reports/m1-skills.json",
    [string]$Tasks  = "m1/tasks.jsonl",
    [double]$Delay  = 0
)
Set-Location C:\Users\Administrator\openjev-ultrafast
if (-not $env:DECIDER_MODE) { $env:DECIDER_MODE = "typesafe" }
$env:TYPESAFE_BASE_URL      = "http://127.0.0.1:8000/v1/systemone"
$env:TEXT_HELPER_BASE_URL   = "https://api.groq.com/openai/v1"
$env:TEXT_HELPER_MODEL      = "openai/gpt-oss-120b"
$env:TEXT_HELPER_API_KEY    = $env:GROQ_API_KEY
$env:TEXT_HELPER_MAX_TOKENS = "256"
$env:PYTHONUTF8             = "1"
& "C:\Users\Administrator\miniconda3\envs\jev\python.exe" -m m1.run_tasks `
    --tasks $Tasks --log-dir logs --report $Report --task-delay $Delay
