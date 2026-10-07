# Start one command: llama-server (GGUF backend) + startlux gguf_server (TypeSafe wire).
# Usage: .\scripts\startlux_serve.ps1 [-ProxyUrl http://127.0.0.1:2080] [-SkipEnsure]
# Missing artifacts (llama.cpp binaries, CUDA runtime DLLs, StartLux GGUF repo) are
# downloaded on demand; -SkipEnsure keeps the old behaviour for provisioned boxes.
# Logs:  logs\startlux-llama.log / logs\startlux-wire.log

param(
    [string]$ProxyUrl = "http://127.0.0.1:2080",
    [switch]$SkipEnsure
)

$ErrorActionPreference = "Stop"
$Root      = "D:\openjev-models"
$LlamaDir  = "$Root\llamacpp"
$ModelDir  = "$Root\startlux-decision-2b"
$PkgDir    = "$Root\startlux-decision-pkg"
$VenvPy    = "$Root\decider\.venv\Scripts\python.exe"
$LogDir    = "$PSScriptRoot\..\logs"
New-Item -ItemType Directory -Force $LogDir | Out-Null

# --- clean previous instances (BEFORE provisioning: a running llama-server
# holds file locks on the DLLs Copy-Item must overwrite) ----------------------
Get-Process | Where-Object { $_.ProcessName -in "llama-server" } -ErrorAction SilentlyContinue |
    Stop-Process -Force -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -like "*gguf_server*" } -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2

$GgufName  = "StartLux-Decision-2B-Q8_0.gguf"
$LlamaZip  = "https://github.com/ggml-org/llama.cpp/releases/download/b11433/llama-b11433-bin-win-cuda-12.4-x64.zip"
$CudartZip = "https://github.com/ggml-org/llama.cpp/releases/download/b11433/cudart-llama-bin-win-cuda-12.4-x64.zip"

# --- 0) ensure artifacts -------------------------------------------------------
# Cold-box bootstrap for the one-command entry point (L6). The HF repo ships the
# .gguf plus the startlux_decision package and tokenizer files, so one snapshot
# fills $ModelDir. GitHub releases ship the llama.cpp CUDA build and the CUDA
# runtime DLL bundle that build needs.
function Download-Url($url, $out) {
    foreach ($px in @($ProxyUrl, "")) {
        try {
            Write-Host "  GET $url (proxy='$px')"
            if ($px) { Invoke-WebRequest -Uri $url -OutFile $out -Proxy $px -UseBasicParsing }
            else     { Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing }
            return
        } catch { Write-Host "  failed via proxy '$px': $($_.Exception.Message)" }
    }
    throw "could not download $url (proxy down and direct blocked?)"
}

if (-not $SkipEnsure) {
    if (-not (Test-Path "$LlamaDir\llama-server.exe")) {
        New-Item -ItemType Directory -Force $LlamaDir | Out-Null
        $tmp = "$env:TEMP\jev-llama.zip"; $ext = "$env:TEMP\jev-llama-ext"
        Download-Url $LlamaZip $tmp
        Remove-Item -Recurse -Force $ext -EA SilentlyContinue
        Expand-Archive $tmp -DestinationPath $ext -Force
        $src = if (Test-Path "$ext\bin\llama-server.exe") { "$ext\bin" } else { $ext }
        Copy-Item "$src\*" $LlamaDir -Force
        Remove-Item -Recurse -Force $ext, $tmp -EA SilentlyContinue
        Write-Host "llama.cpp installed to $LlamaDir"
    }
    if (-not (Test-Path "$LlamaDir\cublas64_12.dll")) {
        # the CUDA build needs cudart/cublas/cublasLt present next to the exe
        $tmp = "$env:TEMP\jev-cudart.zip"; $ext = "$env:TEMP\jev-cudart-ext"
        Download-Url $CudartZip $tmp
        Remove-Item -Recurse -Force $ext -EA SilentlyContinue
        Expand-Archive $tmp -DestinationPath $ext -Force
        Get-ChildItem $ext -Recurse -Filter *.dll | Copy-Item -Destination $LlamaDir -Force
        Remove-Item -Recurse -Force $ext, $tmp -EA SilentlyContinue
        Write-Host "CUDA runtime DLLs installed to $LlamaDir"
    }
    if (-not (Test-Path "$ModelDir\$GgufName")) {
        if (-not (Test-Path $VenvPy)) { throw "wire python missing: $VenvPy (model download needs its huggingface_hub)" }
        New-Item -ItemType Directory -Force $ModelDir | Out-Null
        $env:HTTP_PROXY = $ProxyUrl; $env:HTTPS_PROXY = $ProxyUrl; $env:HF_HUB_OFFLINE = "0"
        Write-Host "downloading startlux-models/StartLux-Decision-2B-Q8_0-GGUF (~2.1GB)..."
        & $VenvPy -c "from huggingface_hub import snapshot_download; snapshot_download('startlux-models/StartLux-Decision-2B-Q8_0-GGUF', local_dir=r'$ModelDir')"
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path "$ModelDir\$GgufName")) {
            throw "GGUF download incomplete (exit $LASTEXITCODE); rerun to resume"
        }
    }
    foreach ($p in @("$LlamaDir\llama-server.exe", "$ModelDir\$GgufName",
                     "$ModelDir\startlux_decision", $VenvPy)) {
        if (-not (Test-Path $p)) { throw "artifact missing and not provisioned: $p" }
    }
}

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
