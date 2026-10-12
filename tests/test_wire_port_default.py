r"""决策线的默认端口全仓只能有一个值：:8090（StartLux gguf_server 的 wire）。

2026-10-12 普查（#69 第 3 条）里唯一还没收的就是这个。`scripts/run_one.ps1:8`、
`scripts/smoke.ps1:4`、`scripts/ci_local.ps1:21`、`run_demo.ps1:4` 的默认都是 **8090**，
只有 `run_baseline_19.ps1:16` 的默认是 **8000**——那是已关闭的 M4 线 `decider.serve` 的端口。

为什么"默认值"这件事必须有闸门，而不是"记得传 `-SvcPort 8090`"：
`run_baseline_19.ps1` 忘记传参时**不会报错**。它会在 Step 3 自己起 uvicorn `decider.serve:app`
（一个和 StartLux 不同的 2B 权重），然后把 `TYPESAFE_BASE_URL` 指过去，冻结与真实批照样出
19/19 或 65/100 这种看着合理的形状。连错端口 = 连错模型，而读数看不出来——这正是 A0 那条
"零云端/底座唯一"要靠调用方记性来维持的入口。

三条检查（都只读源码，离线闸门能在任何机器上跑）：

1. 活 runner 的默认决策端口必须全等于同一个值；
2. `:8000` 只许出现在**已关闭的 M4/M1 线**里（显式白名单），新脚本引入就红；
3. `run_baseline_19.ps1` 那条"自己起退役服务"的分支必须在动任何东西之前拒绝——
   默认端口换成 8090 之后，"不传 -NoService 又指望别的端口"是个自相矛盾的调用，
   守卫把它变成响亮的失败，而不是让脚本去起一个和 $SvcPort 不一致的服务。

第 3 条在改之前**没有**任何东西执行这个拒绝，所以它改前必红；改后的实跑见证写在 `m2/real-log.md`。

运行：python tests/test_wire_port_default.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

WIRE_PORT = 8090          # StartLux gguf_server
RETIRED_PORT = 8000       # 已关闭的 M4 decider.serve

# 会真的驱动浏览器/出读数的入口，默认必须落在现役线上
LIVE_RUNNERS = ("run_baseline_19.ps1", "run_demo.ps1",
                "scripts/run_one.ps1", "scripts/smoke.ps1", "scripts/ci_local.ps1")

# 退役线：整条 M4 自训 / M1 老 suite——它们自己起 `decider.serve`(:8000) 并一致地指着它，
# 端口和它们要起的模型是一对，所以不是"连错端口"，而是"这条线已经关了"。
# 白名单不是豁免，是记账：#71 归档那件把它们整体搬走之后，这份清单应该变短。
CLOSED_LINES = ("run_m1.ps1", "run_m4b_collect.ps1", "run_adapter_m4b.ps1",
                "run_s004_history_test.ps1", "m1/run_suite.ps1")
CLOSED_PREFIXES = ("m4a/",)

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


def default_wire_port(src: str) -> int | None:
    """param 块里决策线端口的默认值。只认 $SvcPort（活 runner 用它指 TYPESAFE_BASE_URL）。"""
    m = re.search(r"\[int\]\$SvcPort\s*=\s*(\d+)", src)
    return int(m.group(1)) if m else None


@case(f"活 runner 的默认决策端口必须都 = {WIRE_PORT}（一个概念一张表，端口也一样）")
def t_live_runners_agree_on_wire_port():
    seen, wrong = {}, []
    for rel in LIVE_RUNNERS:
        p = REPO / rel
        assert p.exists(), f"{rel} 不见了——本文件的清单要跟着改"
        port = default_wire_port(p.read_text(encoding="utf-8", errors="replace"))
        if port is None:
            continue                      # 没有 $SvcPort 这个概念的脚本不算
        seen[rel] = port
        if port != WIRE_PORT:
            wrong.append(f"{rel} 默认 $SvcPort = {port}")
    assert not wrong, (
        "默认值落到没人听的线上时脚本不会报错，它会自己起一个退役模型，读数照样像话。"
        f"现役端口 = {WIRE_PORT}：\n  " + "\n  ".join(wrong))
    assert len(seen) >= 4, f"清单失效了，只读到 {len(seen)} 个默认端口"


_DEFAULT_FORMS = (
    # 默认值本身落在退役线上——没有例外，起退役服务的分支由第 3 案的守卫管
    (r"\[int\]\$SvcPort\s*=\s*" + str(RETIRED_PORT), ()),
    # 无条件把决策后端注入到退役线（已关闭的 M4/M1 线除外，它们整条都没现役调用方）
    (r'TYPESAFE_BASE_URL"?\s*=\s*"http://127\.0\.0\.1:' + str(RETIRED_PORT), CLOSED_LINES),
)


def _is_closed(rel: str) -> bool:
    return rel in CLOSED_LINES or rel.startswith(CLOSED_PREFIXES)


@case(f":{RETIRED_PORT} 不许是任何脚本的默认决策线（白名单外的默认一律红）")
def t_retired_port_does_not_spread():
    hits = []
    for p in sorted(REPO.rglob("*.ps1")):
        rel = str(p.relative_to(REPO)).replace("\\", "/")
        src = p.read_text(encoding="utf-8", errors="replace")
        lines = src.splitlines()
        for pat, _allowed in _DEFAULT_FORMS:
            if _is_closed(rel):
                continue
            for m in re.finditer(pat, src):
                line = src[:m.start()].count("\n")
                hits.append(f"{rel}:{line + 1}  {lines[line].strip()[:80]}")
    assert not hits, (
        "退役端口以默认值的形式复活了——脚本不会报错，它会指着另一个模型跑出像样的读数。"
        "若这条线真的要重启，先把它加进本文件的白名单并说明理由：\n  "
        + "\n  ".join(hits))


@case("run_baseline_19 的『自己起退役服务』分支必须在动任何东西之前拒绝不一致的端口")
def t_closed_service_branch_refuses():
    src = (REPO / "run_baseline_19.ps1").read_text(encoding="utf-8", errors="replace")
    # 守卫只能 exit，不能用脚本里的 Die()——Die 定义在后面，param 块之后还没绑定
    guard = re.search(r"if\s*\(\s*-not\s+\$NoService\s*-and\s*\$SvcPort\s*-ne\s*"
                      + str(RETIRED_PORT) + r"\s*\)\s*\{[^}]*(?:Die|Write-Host)",
                      src, re.S)
    first_side_effect = min(
        src.index(x) for x in ("Get-CimInstance", "Start-Process") if x in src)
    assert guard is not None, (
        "没有早退守卫：不传 -NoService 时脚本会自己去起退役的 decider.serve(:8000)，"
        "而 TYPESAFE_BASE_URL 用的是 $SvcPort——默认端口一旦换成 8090，这两者就再也不一致。")
    assert src.index("param(") < guard.start() < first_side_effect, (
        f"守卫存在但位置不对（第一个副作用在 {first_side_effect}，守卫在 {guard.start()}）："
        "它必须最先触发，否则拒绝之前已经动了模型或浏览器。")
    body = src[guard.start():guard.start() + 700]
    assert "SvcPort" in body and str(RETIRED_PORT) in body and str(WIRE_PORT) in body \
            and re.search(r"\bexit\s+1\b", body), (
        "守卫必须 exit 1 并把两个端口和 $SvcPort 都点名，否则下次读到它的人不知道该怎么显式传入")


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
