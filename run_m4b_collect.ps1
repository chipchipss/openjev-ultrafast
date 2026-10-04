# M4b 采集轮 1 一键脚本（Windows）。
# 设计：
#   - 决策 = 本地 decider-2B（:8000）
#   - Teacher shadow = buddy 网关 glm-5.3-flash（TEACHER_SHADOW=1, stall-gated）
#   - 文本 helper = Groq（走 Swell 代理）
#   - 任务集 = m2/tasks_extra_8766.jsonl（localhost:8766 测试站，30 任务 × N 轮，
#     非 benchmark 域 → C1 合规可进训练集；benchmark 域 20 任务不采集）
#   - 采集目标：Logger v2 样本（page/history 快照齐全）
param(
    [int]$Rounds = 12,          # 过夜目标：30 任务 × 12 轮 ≈ 360 任务轮
    [int]$TaskDelaySec = 2,
    [string]$Tag = "m4b-r1"     # 输出目录/报告标签（轮 2 传 -Tag m4b-r2）
)
 $ErrorActionPreference = "Continue"
$py = "C:\Users\Administrator\miniconda3\envs\jev\python.exe"
$root = "C:\Users\Administrator\openjev-ultrafast"
Set-Location $root

# ---- 环境统一（与 run_s004_history_test.ps1 同源）----
$env:DECIDER_MODEL   = "Mapika/decider-2b"
$env:HF_HOME         = "D:\openjev-models\hf"   # 权重统在 D 盘（用户级 env 未必传到子进程，显式设）
$env:HF_HUB_OFFLINE  = "1"
$env:USE_TF          = "0"
$env:DECIDER_COMPILE = "0"
$env:DECIDER_FP8     = "0"
$env:DECIDER_MODE    = "typesafe"
$env:TYPESAFE_BASE_URL = "http://127.0.0.1:8000/v1/systemone"
$env:TYPESAFE_API_KEY  = "local"
$env:TEACHER_BASE_URL  = "https://buddy.chips.us.ci/v1"
$env:TEACHER_MODEL     = "glm-5.3-flash"
$env:TEACHER_API_KEY   = "wbg-6c6280e2b0413e5e70bb5b20d06fdf1804a4"
$env:TEACHER_SHADOW    = "1"
$env:TEACHER_SHADOW_EVERY = "1"   # M4b 采集：每决策都 shadow（stall-gated 只在
                                  # 失败点采样，正常 PASS 任务零样本 → a_positive
                                  # 桶空）。M2 实测 shadow ~3.4s/次，30 任务可接受。
$env:TEACHER_LIMIT     = "24"      # 每任务 shadow 上限
$env:TEXT_HELPER_BASE_URL = "https://api.groq.com/openai/v1"
$env:TEXT_HELPER_MODEL    = "openai/gpt-oss-120b"
$env:TEXT_HELPER_API_KEY  = $env:GROQ_API_KEY
$env:HTTPX_PROXY          = "http://127.0.0.1:2080"
$env:PYTHONUTF8           = "1"
$env:M15_ALL_KIND_STALE   = "1"
$env:M15_CYCLE_CUT        = "1"

function Log($m)  { Write-Host "[$(Get-Date -Format 'HH:mm:ss')] $m" }
function Fail($m) { Write-Host "[$(Get-Date -Format 'HH:mm:ss')] FAIL: $m" -ForegroundColor Red }

# ---- 1. decider 起服务 ----
Log "starting decider-2B on :8000"
$decider = Start-Process -FilePath "D:\openjev-models\decider\.venv\Scripts\python.exe" `
    -ArgumentList "-m","uvicorn","decider.serve:app","--host","0.0.0.0","--port","8000" `
    -WorkingDirectory "D:\openjev-models\decider" `
    -WindowStyle Hidden -PassThru
$ready = $false
foreach ($i in 1..60) {
    try { Invoke-RestMethod "http://127.0.0.1:8000/health" -TimeoutSec 2 | Out-Null; $ready = $true; break }
    catch { Start-Sleep 3 }
}
if (-not $ready) { Fail "decider not ready"; if ($decider) { Stop-Process -Id $decider.Id -Force -EA SilentlyContinue }; exit 1 }
Log "decider ready"

# ---- 2. 测试站起服务（:8766）----
Log "starting test-site on :8766"
$site = Start-Process -FilePath $py `
    -ArgumentList "m2/test-site/serve.py","--port","8766" `
    -WorkingDirectory $root -WindowStyle Hidden -PassThru
Start-Sleep 3

# ---- 3. 轮次采集 ----
$stamp = Get-Date -Format "yyyyMMdd-HHmm"
for ($r = 1; $r -le $Rounds; $r++) {
    $logDir = "logs/$Tag/r$r"
    Log "=== round $r/$Rounds -> $logDir ==="
    & $py -m m1.run_tasks --tasks m2/tasks_extra_8766.jsonl --log-dir $logDir `
        --report "reports/$Tag-round$r.json" 2>&1 | Select-Object -Last 6
    # CDP 健康复位（每轮之间杀 chrome 重启，防会话累积劣化）
    Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -EA SilentlyContinue }
    Start-Sleep $TaskDelaySec
}

# ---- 4. 抽样 + 晨报 ----
Log "extracting samples (Logger v2 fields)..."
& $py -m m2.sample_extractor --logs logs/$Tag --tasks m2/tasks_extra_8766.jsonl --out "samples/$Tag" --benchmark-domains config/no_benchmark_domains.txt 2>&1 | Select-Object -Last 10
Log "=== DONE. samples/$Tag/manifest.json is the morning report ==="

# ---- 清理 ----
if ($decider) { Stop-Process -Id $decider.Id -Force -EA SilentlyContinue }
if ($site)    { Stop-Process -Id $site.Id -Force -EA SilentlyContinue }
Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -EA SilentlyContinue }
Log "cleanup done"
