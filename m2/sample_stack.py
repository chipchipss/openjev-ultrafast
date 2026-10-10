r"""#58 的量：批跑到第 42 行崩之前，栈里到底在累积什么（旁路采样，不参与跑批）。

为什么要它：b22/b23 两批都在**同一行、同一位置（第 42/50）**以同一签名崩
（`browser_harness/_ipc.py:103 request → c.recv → TimeoutError`，act 之后的 observe），
而 r142 单发 PASS/5 步。"每任务重启"挡不住它，说明累积发生在**比 Chrome 更上层**的地方
——daemon 进程、它的 socket、或者模型那侧。不先看清是哪一层就动手改，等于又赌一刀。

采样口径（每 5 s 一行 CSV，只读，绝不杀进程/不碰浏览器）：
  epoch, 空闲物理MB, llama-server RSS, daemon 进程 RSS 之和, python 进程数,
  自有 chrome 进程数, :9222 上的 TCP 连接数, 当前在跑的行(日志目录里最新的 jsonl)
把 CSV 与崩溃时间戳对齐，就能回答"崩之前那一分钟哪一项在异常增长"。

用法：python m2/sample_stack.py <logs/批目录> <out.csv> [秒数]
"""
from __future__ import annotations

import csv
import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wt.DWORD), ("dwMemoryLoad", wt.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def free_mb():
    m = MEMORYSTATUSEX()
    m.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return m.ullAvailPhys // 1048576


PS = (r"$ErrorActionPreference='SilentlyContinue';"
      # 口径说明：第一版用 Get-CimInstance 取 CommandLine 来区分 daemon，实测那三列
      # 在批跑起来的高负载窗口全回 0（同一命令里 Get-Process 与 Get-NetTCPConnection 正常）——
      # 仪器坏就不许拿它下结论，改成纯 Get-Process 口径：按进程名给 RSS 之和与条数。
      "$py=@(Get-Process python -EA SilentlyContinue);"
      "$pysum=0; foreach($p in $py){$pysum+=$p.WorkingSet64};"
      "$ll=@(Get-Process llama-server -EA SilentlyContinue);$llsum=0;"
      "foreach($p in $ll){$llsum+=$p.WorkingSet64};"
      "$ch=@(Get-Process chrome -EA SilentlyContinue).Count;"
      "$h=@(Get-Process -EA SilentlyContinue|Where-Object{$_.ProcessName -match 'node|browser_harness'}).Count;"
      "$t=@(Get-NetTCPConnection -State Established -EA SilentlyContinue|"
      "Where-Object{$_.RemotePort -eq 9222 -or $_.LocalPort -eq 9222}).Count;"
      "$tw=@(Get-NetTCPConnection -State TimeWait -EA SilentlyContinue|"
      "Where-Object{$_.RemotePort -eq 9222 -or $_.LocalPort -eq 9222}).Count;"
      "Write-Output (\"{0}|{1}|{2}|{3}|{4}|{5}|{6}\" -f [long]$pysum,[long]$llsum,$py.Count,$ch,$h,$t,$tw)")


def run_ps():
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", PS],
                           capture_output=True, timeout=20)
        line = r.stdout.decode("utf-8", "replace").strip().splitlines()
        for l in reversed(line):
            if "|" in l:
                return l.split("|")
    except Exception:
        pass
    return [""] * 7


def current_row(log_dir):
    try:
        files = [os.path.join(log_dir, f) for f in os.listdir(log_dir) if f.endswith(".jsonl")]
        if not files:
            return ""
        return os.path.basename(max(files, key=os.path.getmtime))[:-6]
    except OSError:
        return ""


def main():
    log_dir = sys.argv[1]
    out = sys.argv[2]
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 2400
    new = not os.path.exists(out)
    fh = open(out, "a", newline="", encoding="utf-8")
    w = csv.writer(fh)
    if new:
        w.writerow(["epoch", "t", "free_mb", "python_rss_mb", "llama_rss_mb", "python_procs",
                    "chrome_procs", "harness_procs", "cdp_tcp_est", "cdp_tcp_timewait",
                    "current_row"])
    t0 = time.time()
    while time.time() - t0 < limit:
        ps = run_ps()
        w.writerow([int(time.time()), time.strftime("%H:%M:%S"), free_mb(),
                    round(int(ps[0] or 0) / 1048576), round(int(ps[1] or 0) / 1048576),
                    ps[2], ps[3], ps[4], ps[5], ps[6], current_row(log_dir)])
        fh.flush()
        time.sleep(5)
    fh.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
