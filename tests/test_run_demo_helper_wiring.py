r"""体检报告里那条『run_demo.ps1 的 $helperUrl 待核』点验为真：注入的是三个不存在的变量。

`run_demo.ps1` Step 0 用 `Resolve-TextHelper` 拿到一张表 `$helper = @{Url;Model;Key;...}`，
并把三项写进 `$env:`。Step 3 起子进程前又调了一次 `Set-Env`，那里写的却是
`$helperUrl / $helperModel / $helperKey` —— **全文件没有任何地方给这三个名字赋过值**。
PowerShell 里未定义的变量展开成 `$null`，而 `Set-Item env:X -Value $null` 是**删除**该变量：
于是 Step 0 好不容易装好的 Text Helper 地址，在真正跑 demo 的前一行被抹掉。
这不是风格问题：demo 会带着"没有 helper"的形状跑完，读数看着正常，填字段那一路其实没走 helper。

三条检查都只读源码结构，不启动 PowerShell（离线闸门要能在任何机器上跑）：

1. `Set-Env` 里注入的 TEXT_HELPER_* 不许来自未赋值的变量名；
2. 三项必须从 `$helper` 那张表里取，字段名只能是 Url / Model / Key；
3. 跨文件契约：`Resolve-TextHelper` 的 startlux 分支必须回本地地址（零云端这条底线归它管）。

运行：python tests/test_run_demo_helper_wiring.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

RUN_DEMO = REPO / "run_demo.ps1"
TEXT_HELPER = REPO / "scripts" / "text_helper.ps1"

ENV_KEYS = ("TEXT_HELPER_BASE_URL", "TEXT_HELPER_MODEL", "TEXT_HELPER_API_KEY")

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


def assigned_names(src: str) -> set[str]:
    """脚本里所有被赋值过的变量名（param 块、$x =、$script:x =、function 参数、foreach/for）。"""
    out: set[str] = set()
    for m in re.finditer(r"(?m)^\s*\$([A-Za-z_][A-Za-z0-9_:]*)\s*(?:=[^\n]|[^=\n]*\n\s*=[^\n])", src):
        out.add(m.group(1).split(":")[-1])
    for m in re.finditer(r"\$([A-Za-z_][A-Za-z0-9_:]*)\s*=", src):
        out.add(m.group(1).split(":")[-1])
    for m in re.finditer(r"^\s*\[.*?\]\$([A-Za-z_][A-Za-z0-9_]*)", src, re.M):
        out.add(m.group(1))                       # param([string]$Task = ...) 与函数参数
    for m in re.finditer(r"function\s+\S+\s*\(([^)]*)\)", src):
        for pm in re.finditer(r"\$([A-Za-z_][A-Za-z0-9_]*)", m.group(1)):
            out.add(pm.group(1))
    for m in re.finditer(r"foreach\s*\(\s*\$([A-Za-z_][A-Za-z0-9_]*)", src):
        out.add(m.group(1))
    return out


def env_injection(src: str) -> dict[str, str]:
    """取 Set-Env @{...} 里 TEXT_HELPER_* -> 右侧表达式（跨行， hashtable 用 ; 分隔）。"""
    hits: dict[str, str] = {}
    for key in ENV_KEYS:
        m = re.search(r'"' + key + r'"\s*=\s*([^;\n}]+)', src)
        assert m, f"run_demo.ps1 里找不到 {key} 的注入 —— 本文件要跟着脚本重写"
        hits[key] = m.group(1).strip()
    return hits


@case("TEXT_HELPER_* 的注入值必须是已赋值的变量：$helperUrl 这类名字全文件没人赋过")
def t_no_phantom_variables():
    src = RUN_DEMO.read_text(encoding="utf-8")
    defined = assigned_names(src)
    phantom: list[str] = []
    for key, expr in env_injection(src).items():
        for var in re.findall(r"\$([A-Za-z_][A-Za-z0-9_]*)", expr):
            if var not in defined:
                phantom.append(f"{key} -> ${var}")
    assert not phantom, (
        "注入了未赋值的变量：PowerShell 会展开成 $null，Set-Item env:X -Value $null 等于删除，"
        f"Step 0 装好的 helper 地址在此被抹掉。{phantom}")


@case("三项都从 Resolve-TextHelper 的那张表里取，字段只许 Url / Model / Key")
def t_reads_from_the_resolved_table():
    src = RUN_DEMO.read_text(encoding="utf-8")
    exprs = env_injection(src)
    want = {"TEXT_HELPER_BASE_URL": r"\$helper\.Url",
            "TEXT_HELPER_MODEL": r"\$helper\.Model",
            "TEXT_HELPER_API_KEY": r"\$helper\.Key"}
    bad = [f"{k} = {exprs[k]}" for k, pat in want.items()
           if not re.search(pat, exprs[k])]
    assert not bad, "helper 只有一份来源（$helper 表），注入端却读了别处：" + "; ".join(bad)
    # Step 0 必须真的解析过这张表，否则上面三条都是无源之水。
    assert re.search(r"\$helper\s*=\s*Resolve-TextHelper", src), \
        "Step 0 不再调用 Resolve-TextHelper：本文件的契约对象变了"


@case("跨文件契约：Resolve-TextHelper 必须回这三项，且 startlux 分支是本地地址")
def t_resolver_contract_is_local():
    src = TEXT_HELPER.read_text(encoding="utf-8")
    for field in ("Url", "Model", "Key"):
        assert re.search(r"\b" + field + r'\s*=', src), \
            f"Resolve-TextHelper 不再产出 {field}，run_demo 的注入端会拿到 $null"
    m = re.search(r'"startlux"\s*\{([^}\n]*)\}', src)
    assert m, "startlux 分支找不到：默认底座换了要同步改这条检查"
    body = m.group(1)
    assert "127.0.0.1" in body, f"startlux 分支不再是本地地址（零云端底线）：{body}"
    assert "api." not in body, f"默认分支里出现云端主机：{body}"


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                                       # noqa: BLE001
            pass
    failed = 0
    for name, fn in CASES:
        try:
            fn()
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {name}\n      {e}")
        except Exception as e:                                  # noqa: BLE001
            failed += 1
            print(f"ERROR {name}\n      {type(e).__name__}: {e}")
        else:
            print(f"ok    {name}")
    print(f"{len(CASES) - failed}/{len(CASES)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
