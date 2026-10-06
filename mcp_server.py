"""OpenJEV MCP server -- expose the browser agent as Claude Code tools.

Three tools:
  agent_status   -- check the backend stack (Chrome CDP + StartLux wire server + proxy)
  agent_run      -- run ONE natural-language task on ONE page
  demo_flights   -- the verified Google Flights end-to-end demo

Run:  jev-python mcp_server.py          (stdio transport, Claude Code starts it)
"""
from __future__ import annotations

import json
import os
import subprocess
import time

from mcp.server.mcpserver import MCPServer

REPO = r"C:\Users\Administrator\openjev-ultrafast"
PY_JEV = r"C:\Users\Administrator\miniconda3\envs\jev\python.exe"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PROXY = "http://127.0.0.1:2080"

# Decision base: StartLux-Decision-2B gguf_server (:8090, TypeSafe wire).
# scripts\startlux_serve.ps1 owns the full stack (llama-server :8081 + wire :8090).
WIRE_PORT = 8090

mcp = MCPServer("openjev")


# ---------------------------------------------------------------- helpers
def _cdp_alive() -> bool:
    try:
        import httpx

        r = httpx.get("http://127.0.0.1:9222/json/version", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def _decider_alive() -> bool:
    """The StartLux wire server answers /health on :8090."""
    try:
        import httpx

        return httpx.get(f"http://127.0.0.1:{WIRE_PORT}/health",
                         timeout=2).status_code == 200
    except Exception:
        return False


def _start_chrome(proxy: bool = True) -> None:
    subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"], capture_output=True)
    time.sleep(2)
    flags = ["--headless=new", "--remote-debugging-port=9222",
             "--user-data-dir=C:\\chrome-cdp-test", "--no-first-run",
             "--no-default-browser-check"]
    if proxy:
        flags.append(f"--proxy-server={PROXY}")
    subprocess.Popen([CHROME, *flags])
    for _ in range(20):
        if _cdp_alive():
            return
        time.sleep(1)
    raise RuntimeError("Chrome did not come up on :9222")


def _start_decider() -> None:
    """Start the full StartLux stack (llama-server :8081 + wire :8090).

    scripts\\startlux_serve.ps1 owns process cleanup + health polling; run it
    detached and wait for the wire server here.
    """
    subprocess.Popen(
        ["powershell", "-ExecutionPolicy", "Bypass",
         "-File", rf"{REPO}\scripts\startlux_serve.ps1"],
        cwd=rf"{REPO}\scripts",
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW)
    for _ in range(120):
        if _decider_alive():
            return
        time.sleep(2)
    raise RuntimeError("StartLux wire server did not answer /health within 240s "
                       f"on :{WIRE_PORT} (see logs\\startlux-*.err.log)")


def _ensure_stack(proxy: bool = True) -> str:
    """Bring Chrome + decider up as needed. Returns a status note."""
    notes = []
    if not _cdp_alive():
        _start_chrome(proxy)
        notes.append("Chrome started" + (" (with proxy)" if proxy else ""))
    if not _decider_alive():
        _start_decider()
        notes.append("decider loaded (~70s)")
    return "; ".join(notes) if notes else "backend already running"


def _run_in_repo(args: list[str], timeout_s: int = 300,
                 env_extra: dict | None = None) -> tuple[int, str]:
    """Run run_task.py in the repo and return (exit_code, tail_of_output)."""
    env = dict(os.environ, PYTHONUTF8="1")
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        [PY_JEV, "scripts/run_task.py", *args],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=timeout_s, env=env,
    )
    out = (proc.stdout or "") + (("\n[stderr] " + proc.stderr) if proc.stderr.strip() else "")
    lines = out.strip().splitlines()
    return proc.returncode, "\n".join(lines[-40:])


# ---------------------------------------------------------------- tools
@mcp.tool()
def agent_status() -> str:
    """Check the OpenJEV browser-agent backend: Chrome CDP on 9222, the StartLux
    decision wire server on 8090, and whether the egress proxy answers.
    Does not start anything."""
    proxy_ok = False
    try:
        import httpx

        proxy_ok = httpx.get("https://api.groq.com", proxy=PROXY,
                             timeout=5).status_code < 500
    except Exception:
        pass
    return json.dumps({
        "chrome_cdp_9222": _cdp_alive(),
        "startlux_wire_8090": _decider_alive(),
        "proxy_2080": proxy_ok,
        "note": "agent_run will auto-start missing pieces; proxy down means "
                "proxy-only sites (wikipedia) fail while direct-reachable "
                "sites still work",
    }, ensure_ascii=False, indent=1)


@mcp.tool()
def agent_run(url: str, goal: str, expect: str = "", steps: int = 20) -> str:
    """Run one browser task with the local (free, on-GPU) agent.

    Args:
        url: page to start on.
        goal: natural-language instruction. Put explicit targets in it --
              quoted terms ('asyncio'), paths (/forms/post), field names.
              Vague goals make the model wander.
        expect: optional completion evidence -- a substring that must appear
                in the final page URL or text for the run to count as PASS.
        steps: step budget (default 20).
    Returns the step trace, final URL, page text excerpt, and PASS/MISSING.
    """
    args = ["--url", url, "--goal", goal, "--steps", str(steps)]
    if expect:
        args += ["--expect", expect]
    try:
        note = _ensure_stack(proxy=True)
    except Exception as e:
        return f"backend startup failed: {e}"
    code, tail = _run_in_repo(args)
    verdict = "PASS" if code == 0 else ("FAIL" if expect else "done")
    header = f"[openjev] {verdict}   ({note or 'backend running'})\n"
    return header + tail


@mcp.tool()
def demo_flights() -> str:
    """Run the verified Google Flights end-to-end demo (Zurich->London,
    one-way, independently checked 7 ways). Takes about a minute."""
    try:
        note = _ensure_stack(proxy=True)
    except Exception as e:
        return f"backend startup failed: {e}"
    stamp = time.strftime("%m%d-%H%M")
    out = rf"{REPO}\reports\demo-flights-{stamp}.json"
    proc = subprocess.run(
        [PY_JEV, r"m4a\run_flights_ours.py", "--out", out],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=420,
        env=dict(os.environ, PYTHONUTF8="1", DECIDER_MODE="typesafe",
                 TYPESAFE_BASE_URL=f"http://127.0.0.1:{WIRE_PORT}/v1/systemone",
                 TYPESAFE_API_KEY="local", HTTPX_PROXY=PROXY),
    )
    lines = ((proc.stdout or "") + (proc.stderr or "")).strip().splitlines()
    summary = "\n".join(lines[-15:])
    verdict = ""
    try:
        rep = json.load(open(out, encoding="utf-8"))
        verdict = f"\nverification: {'PASSED' if rep['verification']['passed'] else 'FAILED'} {rep['verification']['checks']}"
    except Exception:
        pass
    return f"[openjev demo] ({note or 'backend running'})\n{summary}{verdict}"


if __name__ == "__main__":
    mcp.run()