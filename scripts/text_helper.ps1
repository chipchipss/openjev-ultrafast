# Text Helper resolution (zero-cloud hard line, 2026-10-08).
#
# The Text Helper supplies the value a TYPE_TEXT decision types, so an
# accidentally-cloud default leaks page content into a cloud model -- and the
# reports' api_calls counter never sees it, because that counter only counts the
# teacher path. That is how 56 step-level cloud calls hid behind api_calls=0.
#
# Dot-source it:  . "$Repo\scripts\text_helper.ps1"
# The runners that use this predate the StartLux stack and some of them load
# their own model onto the GPU, so there is no safe default: the endpoint has to
# be named on the command line.
# Cloud choices live in ONE place: the switch below. tests/test_runner_zero_cloud.py reads
# those branch lines to prove {startlux, local} stay loopback and {groq, deepseek} stay cloud,
# so the URLs are spelled exactly once. Resolve-CloudEndpoint (used by the #80 cloud-decider
# runner) reads that same table instead of growing a second copy -- and a runner may not spell
# out a cloud URL at all (tests/test_runner_safety.py whitelists only this file).
function Resolve-CloudEndpoint {
    param([string]$Choice)
    $h = Resolve-TextHelper -Choice $Choice
    if (-not $h.Cloud) { throw "'$Choice' is not a cloud choice -- refusing to treat it as a cloud decider" }
    return @{ Url = $h.Url; Key = $h.Key; Cloud = $true }
}

function Resolve-TextHelper {
    param([string]$Choice, [int]$LlamaPort = 8081, [int]$OllamaPort = 11434)
    $out = @{ Url = ""; Model = ""; Key = ""; Cloud = $false; Health = "" }
    if (-not $Choice) {
        throw "no text helper named -- set -TextHelper (or JEV_TEXT_HELPER) to startlux (local llama :$LlamaPort, zero cloud) | local (ollama) | none | groq | deepseek (the last two are CLOUD and break the zero-cloud rule)"
    }
    switch ($Choice) {
        "startlux" { $out.Url = "http://127.0.0.1:$LlamaPort/v1"; $out.Model = "startlux-decision-2b"; $out.Key = "local"; $out.Health = "http://127.0.0.1:$LlamaPort/health" }
        "local"    { $out.Url = "http://127.0.0.1:$OllamaPort/v1"; $out.Model = "gemma4:latest"; $out.Key = "local"; $out.Health = "http://127.0.0.1:$OllamaPort/api/tags" }
        "none"     { }
        "groq"     { $out.Url = "https://api.groq.com/openai/v1"; $out.Model = "openai/gpt-oss-120b"; $out.Key = $env:GROQ_API_KEY; $out.Cloud = $true }
        "deepseek" { $out.Url = "https://api.deepseek.com/v1"; $out.Model = "deepseek-chat"; $out.Key = $env:DEEPSEEK_API_KEY; $out.Cloud = $true }
        default    { throw "unknown -TextHelper '$Choice' (startlux | local | none | groq | deepseek)" }
    }
    # Fail closed instead of firing unauthenticated calls at a cloud endpoint.
    if ($out.Cloud -and -not $out.Key) {
        throw "-TextHelper $Choice is a CLOUD endpoint but its API key is unset -- refusing to call it"
    }
    return $out
}

# Cloud = loud warning. A named LOCAL endpoint that is not up = stop the run: an
# unreachable helper reads exactly like an agent failure (steps=0, status=blocked
# after three helper_fail_run decisions), and measuring that is worse than not
# measuring.
function Assert-TextHelper {
    param($H)
    if ($H.Cloud) {
        Write-Warning "-TextHelper $($H.Url) ($($H.Model)) is a CLOUD endpoint -- violates the zero-cloud hard line"
    }
    if ($H.Health) {
        try { Invoke-RestMethod $H.Health -TimeoutSec 3 | Out-Null }
        catch { throw "text helper not reachable ($($H.Health)) -- start it first (scripts/startlux_serve.ps1 for startlux), or name another -TextHelper" }
    }
}
