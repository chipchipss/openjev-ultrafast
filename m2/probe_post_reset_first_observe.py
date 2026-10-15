r"""#89 的形状量测：复位之后第一次起点观测，到底死在哪一行。

为什么是这个形状：`r139` 连续两批同一签名
`agent_init_failed_after_cdp_reset: StalePage: Document is navigating`
（`reports/ci-1014-2119-1014-214129.json` / `reports/ci-1014-2225-1014-224810.json`），
traceback 都停在 `jev_ultrafast/agent.py:281`，而 `Agent.__init__` 已经付了
**2 次完整起点**（每次里面 6 次退避、合计 6.0 s）⇒ 抛穿就是两半都耗尽。
#57 当年想用 `m2/probe_init_latency.py` 复现同一个窗口，**没复现**（8 页全好，最慢 3.05 s）。

这个探针不测"页面慢不慢"，测**两种形状的分界**（判据写在 `m2/real-log.md` 的 #89 一节，跑之前钉的）：
1. 读不通（`readyState` 不 complete / 落在校级错误页）⇒ 出口那一族，改的是"复位后再读一次 + 带上 `ERR_*`"；
2. 读得通但每拍被 `Document changed during evaluation` 打断 ⇒ 抖动那一族，加宽 6 秒预算无效。
抛出点的行号就是分界：`browser.py:600` "Document is navigating"、`:228` "Document changed during evaluation"、
`:282` "Page did not settle"。

零模型：不碰 :8090、不产生任何决策调用；浏览器与复位**复用产品自己的** `m1.run_tasks::_reset_cdp`
与 `Agent.__init__`，不另造导航语义（一次复位实测 23.6 秒，出处是 `m1/run_tasks.py:115` 的注释）。
浏览器缺席时**不写结论**（#74 那条老规矩）：先验 `_cdp_healthy()`，不健康就停，不把"读不到"写成"页面不行"。

跑法（jev 环境的 python，PATH 上的 python 没有 browser_harness）：
    C:/Users/Administrator/miniconda3/envs/jev/python.exe -X utf8 m2/probe_post_reset_first_observe.py
    同上加 --trials 8 --arms internet,python  可加臂
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from m1.run_tasks import _cdp_healthy, _reset_cdp            # noqa: E402
from jev_ultrafast.agent import Agent                        # noqa: E402
from jev_ultrafast.browser import Browser, StalePage         # noqa: E402
from jev_ultrafast.logger import page_digest                 # noqa: E402

ARMS = {
    "internet": "https://the-internet.herokuapp.com/",
    "python": "https://docs.python.org/3/",
}

RAISE_SITES = {
    600: "Document is navigating（navigate 后没归静）",
    228: "Document changed during evaluation（读取途中页面变了）",
    282: "Page did not settle（settle 预算内没静下来）",
}


def _load_task(url: str) -> dict | None:
    """取起点域匹配的那一行真实题（r139 / n001），让 Agent 拿到与批内一致的 task_spec。"""
    for line in (REPO / "m2" / "tasks_real_50.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        spec = json.loads(line)
        dom = (spec.get("start_url") or spec.get("domain") or "").rstrip("/")
        if url.rstrip("/").endswith(dom.replace("https://", "").replace("http://", "").rstrip("/")):
            return spec
    return None


def _raise_sites(tb: str) -> list[str]:
    out = []
    for m in re.finditer(r'browser\.py", line (\d+)', tb):
        n = int(m.group(1))
        out.append(f"{n}:{RAISE_SITES.get(n, '?')}")
    return out or ["(no browser.py frame)"]


def diagnose(url: str) -> str:
    """失败之后另起一次观测，只看事实：readyState、落地 URL、标题、正文长度、错误码。"""
    try:
        b = Browser(url)
        page = b.observe(screenshot=False)
        d = page_digest(page)
        b.close()
        return (f"ready={b.evaluate('document.readyState')} url={d.get('url')} "
                f"title={d.get('title')!r} text_len={d.get('text_len')} err={d.get('err')}")
    except Exception as e:                                    # noqa: BLE001
        return f"diagnose_failed: {type(e).__name__}: {e}"


def one_trial(url: str, goal: str, spec: dict | None) -> dict:
    _reset_cdp()
    healthy = _cdp_healthy()
    t0 = time.perf_counter()
    rec = {"cdp_healthy_before": healthy, "elapsed_ms": None, "ok": None,
           "sites": [], "diag": ""}
    agent = None
    try:
        if not healthy:
            rec["ok"] = "skipped-unhealthy"
            return rec
        agent = Agent(url=url, goals=goal, task_spec=spec, screenshots=False)
        rec["ok"] = True
        rec["elapsed_ms"] = round((time.perf_counter() - t0) * 1000)
        rec["diag"] = diagnose_off_the_live_page(agent)
        return rec
    except StalePage as e:
        rec["ok"] = False
        rec["elapsed_ms"] = round((time.perf_counter() - t0) * 1000)
        rec["sites"] = _raise_sites(traceback.format_exc())
        rec["error"] = str(e)
        rec["diag"] = diagnose(url)
        return rec
    except Exception as e:                                    # noqa: BLE001
        rec["ok"] = False
        rec["elapsed_ms"] = round((time.perf_counter() - t0) * 1000)
        rec["error"] = f"{type(e).__name__}: {e}"
        rec["sites"] = _raise_sites(traceback.format_exc())
        rec["diag"] = diagnose(url)
        return rec
    finally:
        if agent is not None:
            try:
                agent.close()
            except Exception:                                 # noqa: BLE001
                pass


def diagnose_off_the_live_page(agent: Agent) -> str:
    """成功那一支也要留下页面事实，否则"过"字没有内容可读。"""
    try:
        d = page_digest(agent.state["page"])
        return (f"url={d.get('url')} title={d.get('title')!r} "
                f"text_len={d.get('text_len')} actions="
                f"{len(agent.state['page'].get('actions') or [])}")
    except Exception as e:                                    # noqa: BLE001
        return f"(diag failed: {e})"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=6)
    ap.add_argument("--arms", default="internet,python")
    args = ap.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                                     # noqa: BLE001
            pass

    for arm in [a.strip() for a in args.arms.split(",") if a.strip()]:
        url = ARMS[arm]
        spec = _load_task(url)
        goal = "\n".join(spec["goal"]) if isinstance(spec.get("goal"), list) else (spec.get("goal") or "")
        print(f"\n=== arm={arm}  url={url}  task_id={spec.get('task_id') if spec else '(none)'} "
              f"trials={args.trials} ===")
        results = []
        for i in range(1, args.trials + 1):
            r = one_trial(url, goal, spec)
            results.append(r)
            sites = ",".join(r["sites"]) if r["sites"] else "-"
            print(f"  trial {i}: ok={r['ok']}  healthy={r['cdp_healthy_before']}  "
                  f"{r['elapsed_ms']} ms  sites=[{sites}]")
            print(f"           {r['diag']}")
        oks = [r for r in results if r["ok"] is True]
        bads = [r for r in results if r["ok"] is False]
        skipped = [r for r in results if r["ok"] == "skipped-unhealthy"]
        site_count: dict[str, int] = {}
        for r in bads:
            for s in r["sites"]:
                site_count[s] = site_count.get(s, 0) + 1
        ms = [r["elapsed_ms"] for r in oks if r["elapsed_ms"]]
        print(f"  -> ok={len(oks)}/{args.trials}  fail={len(bads)}  skipped={len(skipped)}"
              f"  中位耗时={statistics.median(ms) if ms else 'n/a'} ms  抛出点={site_count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
