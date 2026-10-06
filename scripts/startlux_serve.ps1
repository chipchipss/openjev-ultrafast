# Start one command: llama-server (GGUF backend) + startlux gguf_server (TypeSafe wire).
# Usage: .\scripts\startlux_serve.ps1   (stops both with Ctrl+C or they exit with the shell)
# Logs:  logs\startlux-llama.log / logs\startlux-wire.log

$ErrorActionPreference = "Stop"
$Root      = "D:\openjev-models"
$LlamaDir  = "$Root\llamacpp"
$ModelDir  = "$Root\startlux-decision-2b"
$PkgDir    = "$Root\startlux-decision-pkg"
$VenvPy    = "$Root\decider\.venv\Scripts\python.exe"
$LogDir    = "$PSScriptRoot\..\logs"
New-Item -ItemType Directory -Force $LogDir | Out-Null

# --- clean previous instances -------------------------------------------------
Get-Process | Where-Object { $_.ProcessName -in "llama-server" } -ErrorAction SilentlyContinue |
    Stop-Process -Force -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -like "*gguf_server*" } -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

# --- 1) llama-server: Q8_0 2B, GPU offload, 16k ctx --------------------------
# -lm none (no mmap): with mmap the whole 2GB file lands in the process working
# set and on this 16GB box that read "6.7GB RAM in use" and tripped the runner's
# 3GB free-memory gate. All 99 layers go to VRAM anyway; the KV cache (16k ctx,
# 4 parallel slots) stays in RAM at a few hundred MB.
$llama = Start-Process -FilePath "$LlamaDir\llama-server.exe" -ArgumentList @(
    "-m", "$ModelDir\StartLux-Decision-2B-Q8_0.gguf",
    "-ngl", "99", "-c", "16384", "--parallel", "4", "--port", "8081",
    "--host", "127.0.0.1", "-lm", "none"
) -WindowStyle Hidden -PassThru -RedirectStandardOutput "$LogDir\startlux-llama.log" -RedirectStandardError "$LogDir\startlux-llama.err.log"
Write-Host "llama-server pid=$($llama.Id) on :8081"

# wait for /health
$ok = $false
foreach ($i in 1..60) {
    Start-Sleep -Seconds 2
    try {
        $r = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:8081/health" -TimeoutSec 3
        if ($r.StatusCode -eq 200) { $ok = $true; break }
    } catch { }
}
if (-not $ok) { Write-Host "llama-server did not become healthy; see $LogDir\startlux-llama.err.log"; exit 1 }
Write-Host "llama-server healthy"

# --- 2) startlux gguf_server: /v1/systemone wire on :8090 --------------------
# The GGUF repo ships the startlux_decision package next to the .gguf file;
# run python from the model dir so `-m startlux_decision.gguf_server` resolves.
$wire = Start-Process -FilePath $VenvPy -ArgumentList @(
    "-m", "startlux_decision.gguf_server",
    "--model-dir", $ModelDir,
    "--llama", "http://127.0.0.1:8081",
    "--port", "8090"
) -WindowStyle Hidden -PassThru -WorkingDirectory $ModelDir `
  -RedirectStandardOutput "$LogDir\startlux-wire.log" -RedirectStandardError "$LogDir\startlux-wire.err.log"
Write-Host "gguf_server pid=$($wire.Id) on :8090"

foreach ($i in 1..30) {
    Start-Sleep -Seconds 1
    try {
        $r = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:8090/health" -TimeoutSec 3
        if ($r.StatusCode -eq 200) { Write-Host "wire server healthy"; exit 0 }
    } catch { }
}
Write-Host "wire server not healthy yet; see $LogDir\startlux-wire.err.log"
Write-Host "(it may still be loading the tokenizer; retry health manually)"
exit 0
