r"""#70 Tier 3 的语料探针：零模型，逐题打开起点页，把**整页快照**落 `m2/corpus/pages.jsonl`。

存在的理由：真实站的 trace 里没有整页 `actions`（#67 只把 `page_fp_before / outcome / url_from`
加进步事件），所以**无法**从日志重放 `skills.route()`。而"零行为变更重构"要的恰恰是
逐字节的重放对照 —— 没有可重放的输入，判据就只能退成"再跑一批看分数抖不抖"，
那玩意在同 build 下本来就有 6/100 的噪声，抓不住一次静默的行为漂移。

规矩（写死在这里，别靠记忆）：
- **零模型**：只 navigate + observe，不调 `choose()`，因此不花模型预算、也不产生云端调用。
- **独占**：有批次在跑就拒绝（纪律⑥：一次运行独占浏览器与 :8090）。
- **归属**：`BU_CDP_URL` 钉死 `:9222`，且 `browser.py` 的 `_assert_owned_browser` 会拒绝非自有浏览器。
- **不入库**：`m2/corpus/` 在 `.gitignore` 里。这里存的是**第三方站点的正文**，
  入库就等于把别人页面的文字抄进发布产物（#79 的同一条线）。

运行：python m2/probe_tier3_corpus.py [--tasks m2/tasks_real_100.jsonl] [--out m2/corpus/pages.jsonl]
"""
from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:2080")
os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:2080")
#: 归属钉死：不 pin 就会去驱动操作者自己的 Chrome（10-12 的 P0 事故）。
os.environ.setdefault("BU_CDP_URL", "http://127.0.0.1:9222")

from jev_ultrafast.browser import Browser, StalePage                # noqa: E402


def batch_in_flight() -> list[str]:
    """有没有批次占着浏览器（与 scripts/smoke.ps1 的 preflight 同一判据）。"""
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
          "Where-Object { $_.CommandLine -like '*m1\\run_tasks*' -or $_.CommandLine -like '*run_tasks.py*' } | "
          "Select-Object -ExpandProperty ProcessId")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                             capture_output=True, text=True, timeout=30)
    except Exception:                                              # noqa: BLE001
        return ["<probe failed to check>"]
    return [x.strip() for x in (out.stdout or "").splitlines() if x.strip()]


def observe_settled(b: Browser, tries: int = 8):
    """初始拍之后仍然可能读到空标题（重页面），所以照抄探针族里那条已验证的循环。"""
    p = None
    for _ in range(tries):
        try:
            p = b.observe(screenshot=False)
        except StalePage:
            p = None
        if str((p or {}).get("title") or "").strip():
            return p
        time.sleep(0.5)
    return p


def start_url(spec: dict) -> str:
    """与 runner 同一个函数，不许另抄一份（抄一份就会漂）。"""
    from m1.run_tasks import _resolve_start_url
    return _resolve_start_url(spec, None)


def acts(page):
    """页面上可点的条目。**kind 用的是快照自己的词表**（click/fill/scroll/reload/wait），
    不是操作名（CLICK/TYPE_TEXT…）—— 第一版按 `("link","button","input","select")` 过滤，
    结果 pass2 落了 **0 页**（`m2/corpus/pages-hop.jsonl` 空文件就是那次事故留下的现场）：
    尺子读错，不是"起点页没有站内链接"。"""
    return [a for a in (page.get("actions") or []) if a.get("kind") == "click"]


def next_hop(page, goal):
    """自己数一遍：把 goal 分词，给每个候选链接打分（label+href 命中几个词），取最高分的**站内**链接。

    返回 `(abs_url, label, href_from)` —— **label 必须一起落盘**：
    `link_followed_arrival` 读的正是"历史里那一次 click 的 action 标签 == goal 的目的地短语"，
    只存 URL 不存标签，golden 里那一族就永远弃权（第一版正是这样：186 页 772 例，
    `link_followed_arrival` 非弃权 **0 例**）。不借用 `skills.explicit_target` 来挑：
    那会让语料形状依赖被测代码，重构改了行为时对照物自己也会动。
    """
    from urllib.parse import urljoin, urlsplit
    here = str(page.get("url") or "")
    host = urlsplit(here).netloc
    toks = [t for t in goal.lower().replace("'", " ").replace('"', " ").split()
            if len(t) > 2 and t not in ("the", "and", "for", "with", "open", "page", "from")]
    best = None
    best_score = 0
    for a in acts(page):
        href = str(a.get("href") or "")
        if not href or href.startswith(("javascript:", "#", "mailto:")):
            continue
        absu = urljoin(here, href)
        if urlsplit(absu).netloc != host:
            continue
        if urlsplit(absu).path == urlsplit(here).path:
            continue
        label = str(a.get("label") or a.get("text") or "").strip()
        hay = (label + " " + absu).lower()
        score = sum(1 for t in toks if t in hay)
        if score > best_score:
            best, best_score = (absu, label, here), score
    return best if best_score >= 1 else None


def snap_one(url):
    """打开一个 URL，归静，返回页字典（读不到就 None）。每次都开新 target、用完关。"""
    b = None
    try:
        b = Browser(url)
        b.await_dom_settle()
        return observe_settled(b)
    except Exception as e:                                          # noqa: BLE001
        print("      snap failed %s: %s" % (type(e).__name__, str(e)[:90]))
        return None
    finally:
        if b is not None:
            try:
                b.close()
            except Exception:                                       # noqa: BLE001
                pass


def pass1(specs, fh):
    written = empty = 0
    for i, spec in enumerate(specs, 1):
        url = start_url(spec)
        page = snap_one(url)
        if not isinstance(page, dict) or not page.get("url"):
            empty += 1
            continue
        fh.write(json.dumps({"task_id": spec["task_id"], "goal": spec["goal"],
                             "start_url": url, "kind": "start",
                             "came_from": "", "page": page}, ensure_ascii=False) + "\n")
        written += 1
        if i % 10 == 0:
            print("  pass1 ... %d/%d" % (i, len(specs)))
    return written, empty


def pass2(specs, start_pages, fh):
    """第二跳：从起点页里**由探针自己的分词打分**挑一个站内链接，落成一页"到站形状"。

    为什么必须有这一族：`link_followed_arrival` / `first_result` 在起点页上永远弃权
    （当前页 URL 就是起点），只测起点页的 golden 对它们等于空转 —— 摘要一样绿，
    但改动它们的回归抓不到。第一版就是这样（实测两个函数 0 例非弃权），所以补这一遍。
    """
    by_tid = {r["task_id"]: r for r in start_pages}
    written = skipped = 0
    for spec in specs:
        rec = by_tid.get(spec["task_id"])
        if not rec:
            continue
        page = rec["page"]
        hop_pick = next_hop(page, spec["goal"])
        if not hop_pick:
            skipped += 1
            continue
        nxt, label, came_from = hop_pick
        hop = snap_one(nxt)
        if not isinstance(hop, dict) or not hop.get("url"):
            skipped += 1
            continue
        fh.write(json.dumps({"task_id": spec["task_id"], "goal": spec["goal"],
                             "start_url": rec["start_url"], "kind": "hop",
                             "came_from": came_from, "via_label": label,
                             "page": hop}, ensure_ascii=False) + "\n")
        written += 1
    print("  pass2：落 %d 页、跳过 %d（起点页里没有命中的站内链接）" % (written, skipped))
    return written


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default=str(REPO / "m2" / "tasks_real_100.jsonl"))
    ap.add_argument("--out", default=str(REPO / "m2" / "corpus" / "pages.jsonl"))
    ap.add_argument("--hop-out", default=str(REPO / "m2" / "corpus" / "pages-hop.jsonl"))
    ap.add_argument("--recapture", action="store_true",
                    help="重采起点页（会让 baseline 漂，必须重记）")
    ap.add_argument("--force", action="store_true",
                    help="即使有批次在跑也继续（默认拒绝）")
    args = ap.parse_args()

    busy = batch_in_flight()
    if busy and not args.force:
        print("REFUSED: 批次占着浏览器（pid %s）。纪律⑥：一次运行只许一个。" % ",".join(busy))
        return 4

    specs = [json.loads(l) for l in io.open(args.tasks, encoding="utf-8") if l.strip()]
    out_path = Path(args.out)
    hop_path = Path(args.hop_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # 语料一旦落盘就是对照物本身：默认**不重采**（重采会让 baseline 漂），
    # 要重采必须显式 --recapture，并且之后必须重记 baseline。
    if out_path.exists() and not args.recapture:
        start_pages = [json.loads(l) for l in io.open(out_path, encoding="utf-8") if l.strip()]
        written = len(start_pages)
        print("pass1 跳过：已有 %s（%d 页）。要重采加 --recapture，然后重记 baseline。"
              % (out_path.name, written))
    else:
        with io.open(out_path, "w", encoding="utf-8", newline="\n") as fh:
            written, empty = pass1(specs, fh)
        print("pass1：%s（%d 页，%d 页没读到）" % (out_path.name, written, empty))
        start_pages = [json.loads(l) for l in io.open(out_path, encoding="utf-8") if l.strip()]
    with io.open(hop_path, "w", encoding="utf-8", newline="\n") as fh:
        hopped = pass2(specs, start_pages, fh)
    size_kb = (out_path.stat().st_size + hop_path.stat().st_size) / 1024.0
    print("语料合计：%d 起点页 + %d 到站页 = %d 页（%.1f MB，m2/corpus/ 不入库）"
          % (written, hopped, written + hopped, size_kb / 1024.0))
    if written < len(specs) * 0.6:
        print("REFUSED-RESULT：起点页读到不足 60%%，这份语料不能当 baseline。")
        return 5
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
