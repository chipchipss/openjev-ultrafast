"""Sample Extractor. M2 #4b：从 logs/*.jsonl 抽四类训练样本（C 类为核心）。

关联硬约束：
  C1  benchmark 域 ≠ 训练域——benchmark 域样本跳过。BENCHMARK_DOMAINS 默认取
      --tasks 文件的全部域（当前 M1 任务集即 benchmark）；M2 混合任务集时用
      --benchmark-domains 显式传清单。TRAINING_DOMAINS 缺省 = 允许所有非
      benchmark 域（先标 domain，M2 结束按域分布再决定白名单）。
  C3  双份存储——candidates_structured = actions_snapshot 经 action_space 重建；
      candidates_rendered = 重放 decider/choose_2b 的 prompt 渲染函数（与线上同源，
      防止渲染漂移）。
  C4  来源标记——C 类 pair 携带 source=teacher / api_model / api_confidence。
  E5  失败四维——manifest 汇总 failure_mode 分布与每任务 fp_rate。

库接口（#5 调用契约）：
  extract_all(log_dir, samples_dir, *, tasks, benchmark_domains,
              training_domains=None) -> manifest dict
    tasks             list[dict] 或已索引 dict——pair 的 goal/domain/category 只在
                      任务表里（日志不携带），必传
    benchmark_domains 任意形态集合（含 www. 前缀/裸域）——入口统一 _host 归一，
                      防止调用方清单格式与域门比较口径错位
    返回的 manifest 含 contamination_check.violations（输出行域 ∈ benchmark = 违规，
    供 #5 验收第3条读取）

CLI：python3 -m m2.sample_extractor --logs ... --tasks ... [--benchmark-domains ...]
     [--training-domains ...] --out samples/

输出：
  c_pairs.jsonl     分歧且 teacher 有效 → chosen=teacher, rejected=local（DPO pair）
  a_positive.jsonl  agree=true 且任务最终 true_success（teacher 背书的本地正确，
                    行含 decision=被背书动作 [缺陷#7]）
  b_reject.jsonl    step.pre_execute.validator.code != "ok"
  manifest.json     计数 + 域分布 + fp_rate + high_variance_task + 污染检查

监测约束（M2 记档，纯统计不碰执行路径）：
  fp_rate = fp 出现次数 / 任务轮次（Logger 为 append 模式，同任务多轮在同一 jsonl）
  fp_rate > HIGH_VARIANCE_FP_RATE(0.30) → pair 打 high_variance: true（仍进集）、
  manifest 标 high_variance_task，M6 优先处理（域调整 or 语义验证）。

设计决策（记档）：
  - a_positive 映射 = agree ∧ task true_success：唯一同时满足 A 类定义
    （2B+Validator PASS+Task PASS）且带 actions_snapshot 可重建 candidates 的来源。
  - b_reject 桶接线就位但当前预期为 0：M1 路径 local validator 拒绝走 StalePage、
    pre 被清、不落 step——该缺口已记档（需 decision 级采集扩展才能真正产出 B 类）。
    b_reject 行 candidates 缺失时带 candidates_missing: true。
  - teacher 无效（invalid/failed/budget_exhausted）不进任何数据集，仅计入 manifest
    的 shadow_status 分布（这些状态记录在 step.pre_execute.shadow 里）。
  - 两遍扫描：pass1 收 events / fp_stats / final_quadrant，pass2 处理 shadows。

架构洞察（记档）：确定性 2B = 数据飞轮死锁；方差 = 数据飞轮的生命线——
分歧产生 C 类 pair，本脚本只做统计门与抽样，不做方差抑制。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:  # 平铺（主仓）
    from decider.action_space import action_space  # noqa: E402
    # 与线上 prompt 同源（C3 rendered 的防漂移保证）——跨模块私有引用，改渲染必同步
    from decider.choose_2b import _render_elements, _render_operations  # noqa: E402
except ImportError:  # fork：decider 在 jev_ultrafast 包内
    from jev_ultrafast.decider.action_space import action_space  # noqa: E402
    from jev_ultrafast.decider.choose_2b import (  # noqa: E402
        _render_elements, _render_operations,
    )

HIGH_VARIANCE_FP_RATE = 0.30


def _host(domain: str) -> str:
    s = (domain or "").strip()
    if not s:
        return ""
    if "://" in s:
        try:
            h = urlparse(s).hostname or ""
        except ValueError:
            return ""
    else:
        h = s.split("/", 1)[0].split(":", 1)[0]
    return h.removeprefix("www.")


def _load_lines(path: Path) -> set[str]:
    out = set()
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#"):
            h = _host(ln)
            if h:
                out.add(h)
    return out


def _index_specs(specs: list[dict]) -> dict:
    idx = {}
    for spec in specs:
        idx[spec["task_id"]] = {
            "domain":  spec.get("domain", ""),
            "host":    _host(spec.get("domain", "")),
            "goal":    spec.get("goal", ""),
            "category": spec.get("category", ""),
        }
    return idx


def _load_tasks(path: Path) -> list[dict]:
    specs = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            specs.append(json.loads(line))
    return specs


def _rendered(elements: list, targets: dict, controls: dict) -> str:
    return (_render_elements(elements)
            + "\n\nOperations:\n" + _render_operations(targets, controls))


def _domain_gate(host: str, raw_domain: str, bench: set, train: set | None) -> tuple[str, dict]:
    """返回 (action, extra)：keep / skip_bench / skip_not_training。"""
    if "<" in raw_domain or ">" in raw_domain:
        return "keep", {"domain_unverified": True, "domain_placeholder": True}
    if host and host in bench:
        return "skip_bench", {}
    if train is not None and host not in train:
        return "skip_not_training", {}
    if not host:
        return "keep", {"domain_unverified": True}
    return "keep", {}


# ---------------------------------------------------------------------------
# 库接口（#5 调用契约）
# ---------------------------------------------------------------------------

def extract_all(
    log_dir: Path,
    samples_dir: Path,
    *,
    tasks,
    benchmark_domains,
    training_domains=None,
) -> dict:
    """扫描 log_dir/**/*.jsonl（含轮次子目录 rN/）→ 写三份样本到 samples_dir → 返回 manifest dict。

    tasks:            list[dict]（任务表行）或 _load_tasks 已索引的 dict。
    benchmark_domains/training_domains: 任意形态（原始行或归一 host）——
      此处统一 _host 归一，消除调用方格式与域门口径的错位。
    """
    log_dir = Path(log_dir)
    samples_dir = Path(samples_dir)
    if isinstance(tasks, dict):
        task_idx = tasks
    else:
        task_idx = _index_specs(list(tasks))
    bench = {_host(x) for x in (benchmark_domains or set()) if _host(x)}
    train = ({_host(x) for x in training_domains if _host(x)}
             if training_domains is not None else None)

    c_pairs: list[dict] = []
    a_positive: list[dict] = []
    b_reject: list[dict] = []
    counts = {
        "teacher_shadow_events": 0,
        "skipped_benchmark": 0,
        "skipped_not_training": 0,
        "consistent_but_not_success": 0,
        "b_reject_skipped": 0,
    }
    shadow_status: dict[str, int] = {}
    fp_stats: dict[str, dict] = {}
    final_quadrant: dict[str, str | None] = {}
    shadows: list = []  # pass2 处理（fp_stats / final_quadrant 就绪后）

    # 缺陷#6：必须递归——m2 runner 落盘在轮次子目录 logs/m2/rN/（#5 约定），
    # 平层 glob 会一个文件都读不到 → 全部计数归0（实况：725 条影子全没进数据集、
    # c_pairs=0、manifest teacher_shadow_events=0）。
    for p in sorted(log_dir.rglob("*.jsonl")):
        tid = p.stem
        # 文件名可能带 _r{N} 轮次后缀（#5 约定）→ 还原任务 id
        base_tid = tid.rsplit("_r", 1)[0] if "_r" in tid and tid.rsplit("_r", 1)[1].isdigit() else tid
        rounds = 0
        fps = 0
        for ln in p.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            ev = json.loads(ln)
            et = ev.get("event")

            if et == "task_result":
                rounds += 1
                res = ev.get("result") or {}
                final_quadrant[base_tid] = res.get("quadrant")
                if res.get("quadrant") == "false_positive":
                    fps += 1

            elif et == "step":
                pre = ev.get("pre_execute") or {}
                sh = pre.get("shadow")
                if isinstance(sh, dict):
                    st = sh.get("status", "unknown")
                    shadow_status[st] = shadow_status.get(st, 0) + 1
                val = pre.get("validator") or {}
                if val.get("code") not in (None, "ok"):
                    info = task_idx.get(base_tid, {})
                    action, _extra = _domain_gate(info.get("host", ""),
                                                  info.get("domain", ""), bench, train)
                    if action != "keep":
                        counts["skipped_benchmark" if action == "skip_bench"
                               else "skipped_not_training"] += 1
                        counts["b_reject_skipped"] += 1
                    else:
                        b_reject.append({
                            "task_id": base_tid, "step": ev.get("step"),
                            "goal": info.get("goal", ""),
                            "category": info.get("category", ""),
                            "domain": info.get("host", ""),
                            "choice": ev.get("choice"),
                            "operation": ev.get("operation"),
                            "target": ev.get("target"),
                            "failure_code": val.get("code"),
                            "candidates_missing": True,
                        })

            elif et == "teacher_shadow":
                shadows.append((base_tid, ev))

        if rounds:
            fp_stats[base_tid] = {
                "fp": fps, "rounds": rounds,
                "rate": round(fps / rounds, 4),
                "high_variance": (fps / rounds) > HIGH_VARIANCE_FP_RATE,
            }

    # --- pass 2：处理 teacher_shadow（此时 fp_stats / final_quadrant 已完整） ---
    for tid, ev in shadows:
        counts["teacher_shadow_events"] += 1
        info = task_idx.get(tid, {"domain": "", "host": "", "goal": "", "category": ""})
        action, extra = _domain_gate(info["host"], info["domain"], bench, train)
        if action == "skip_bench":
            counts["skipped_benchmark"] += 1
            continue
        if action == "skip_not_training":
            counts["skipped_not_training"] += 1
            continue

        snap = ev.get("actions_snapshot") or []
        elements, targets, controls = action_space(snap)
        structured = {"elements": elements, "targets": targets,
                      "controls": controls}
        rendered = _rendered(elements, targets, controls)
        rate = fp_stats.get(tid, {}).get("rate", 0.0)
        base = {
            "task_id": tid,
            "step":    ev.get("step"),
            "goal":    info.get("goal"),
            "category": info.get("category"),
            "domain":  info.get("host") or None,
            **extra,
            "candidates_structured": structured,
            "candidates_rendered":   rendered,
            "high_variance": rate > HIGH_VARIANCE_FP_RATE,
        }

        teacher = ev.get("teacher") or {}
        if ev.get("agree"):
            if final_quadrant.get(tid) == "true_success":
                # 缺陷#7：a_positive 必须携带教师背书的本地决策——行内原只有 state
                # 侧字段，无监督目标不可 SFT（M4a 数据准备时发现）。
                local = ev.get("local") or {}
                a_positive.append({
                    **base,
                    "decision": {
                        "operation": local.get("operation"),
                        "target":    local.get("target"),
                        "operation_confidence": local.get("operation_confidence"),
                        "target_confidence":    local.get("target_confidence"),
                    },
                })
            else:
                counts["consistent_but_not_success"] += 1
        else:
            local = ev.get("local") or {}
            c_pairs.append({
                **base,
                "chosen":   {"operation": teacher.get("operation"),
                             "target":    teacher.get("target")},
                "rejected": {"operation": local.get("operation"),
                             "target":    local.get("target")},
                "source":         teacher.get("source", "api"),
                "api_model":      teacher.get("api_model"),
                "api_confidence": teacher.get("api_confidence"),
            })

    # --- write ---
    samples_dir.mkdir(parents=True, exist_ok=True)

    def _dump(name: str, rows: list[dict]) -> None:
        with (samples_dir / name).open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    _dump("c_pairs.jsonl", c_pairs)
    _dump("a_positive.jsonl", a_positive)
    _dump("b_reject.jsonl", b_reject)

    # --- 污染检查（#5 验收第3条读取）：任何输出行域 ∈ benchmark = 违规 ---
    all_rows = c_pairs + a_positive + b_reject
    violations = [r for r in all_rows if r.get("domain") and r["domain"] in bench]

    hv_tasks = sorted(t for t, s in fp_stats.items() if s["high_variance"])
    host_dist: dict[str, int] = {}
    for row in c_pairs + a_positive:
        h = row.get("domain") or "<unverified>"
        host_dist[h] = host_dist.get(h, 0) + 1

    manifest = {
        "generated_at": time.time(),
        "logs":         str(log_dir),
        "counts":       {**counts, "c_pairs": len(c_pairs),
                         "a_positive": len(a_positive),
                         "b_reject": len(b_reject)},
        "shadow_status": shadow_status,
        "fp_rates":      fp_stats,
        "high_variance_tasks": hv_tasks,
        "domain_distribution": host_dist,
        "contamination_check": {
            "violations":   len(violations),
            "checked_rows": len(all_rows),
            "benchmark_hosts": sorted(bench),
        },
        "pollution": {
            "benchmark_hosts": sorted(bench),
            "training_hosts":  sorted(train) if train is not None else "all-non-benchmark",
            "unverified_domains": sorted(
                {r["task_id"] for r in all_rows if r.get("domain_unverified")}
            ),
        },
        "notes": [
            "b_reject 预期为 0：local validator 拒绝走 StalePage 不落 step（已记档 gap）",
            "teacher invalid/failed/budget_exhausted 不进数据集，见 shadow_status",
            f"high_variance 标准: fp_rate > {HIGH_VARIANCE_FP_RATE}（仍进集，M6 优先处理）",
        ],
    }
    (samples_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", type=Path, required=True)
    ap.add_argument("--tasks", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("samples"))
    ap.add_argument("--benchmark-domains", type=Path, default=None,
                    help="one per line; default = domains of --tasks")
    ap.add_argument("--training-domains", type=Path, default=None,
                    help="one per line; default = allow all non-benchmark hosts")
    args = ap.parse_args()

    specs = _load_tasks(args.tasks)
    bench = (_load_lines(args.benchmark_domains) if args.benchmark_domains
             else {_host(s.get("domain", "")) for s in specs if _host(s.get("domain", ""))})
    train = _load_lines(args.training_domains) if args.training_domains else None

    manifest = extract_all(args.logs, args.out, tasks=specs,
                           benchmark_domains=bench, training_domains=train)

    counts = manifest["counts"]
    print(f"teacher_shadow_events={counts['teacher_shadow_events']} "
          f"c_pairs={counts['c_pairs']} a_positive={counts['a_positive']} "
          f"b_reject={counts['b_reject']}")
    print(f"skipped: benchmark={counts['skipped_benchmark']} "
          f"not_training={counts['skipped_not_training']}")
    print(f"shadow_status={manifest['shadow_status']}")
    print(f"high_variance_tasks={manifest['high_variance_tasks']}")
    print(f"contamination violations={manifest['contamination_check']['violations']}")
    print(f"→ {args.out}/manifest.json")
    print("EXTRACT_OK")
    return 0


# ---------------------------------------------------------------------------
# Smoke（tmp 目录合成日志，验证 C3 重建 / C1 门 / fp_rate 监测全链路）
# ---------------------------------------------------------------------------

def _smoke() -> None:
    import contextlib
    import io
    import tempfile

    passed = 0
    total = 0

    def check(name, cond):
        nonlocal passed, total
        total += 1
        if cond:
            passed += 1
        else:
            print(f"FAIL: {name}")

    def shadow(tid, step, agree):
        local = {"choice": "e1", "operation": "CLICK", "target": "1",
                 "operation_confidence": 0.8, "target_confidence": 0.8}
        teacher = {"choice": "e2", "operation": "CLICK", "target": "2",
                   "operation_confidence": 0.9, "target_confidence": 0.9,
                   "source": "api", "api_model": "mock-t", "api_confidence": 0.9}
        return {"event": "teacher_shadow", "task_id": tid, "step": step,
                "local": local, "teacher": teacher, "agree": agree,
                "operation_match": True, "target_match": not agree,
                "latency_ms": 100, "usage": {},
                "actions_snapshot": [
                    {"id": "e1", "kind": "click", "node": 12, "role": "button", "label": "A"},
                    {"id": "e2", "kind": "fill", "node": 42, "role": "textbox", "label": "B"},
                    {"id": "scroll_down", "kind": "scroll", "label": "S", "delta": 10},
                ]}

    def step_ev(tid, code="ok", shadow_status=None):
        pre = {"validator": {"valid": code == "ok", "code": code}}
        if shadow_status:
            pre["shadow"] = {"status": shadow_status}
        return {"event": "step", "task_id": tid, "step": 0, "pre_execute": pre}

    def result(tid, quadrant):
        return {"event": "task_result", "task_id": tid,
                "result": {"result": "PASS" if quadrant == "true_success" else "FAIL",
                           "quadrant": quadrant}}

    def w(p, rows):
        p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        logs = root / "logs"
        logs.mkdir()
        tasks = root / "tasks.jsonl"
        tasks.write_text("\n".join([
            json.dumps({"task_id": "tB", "domain": "bench.example.com",
                        "category": "search", "goal": "gb", "budget": {"steps": 5},
                        "success_assertion": {"type": "text_contains", "value": "x"}}),
            json.dumps({"task_id": "tT", "domain": "train.example.org",
                        "category": "list", "goal": "gt", "budget": {"steps": 5},
                        "success_assertion": {"type": "text_contains", "value": "x"}}),
            json.dumps({"task_id": "tP", "domain": "<REPLACE_DOMAIN_PER_C1>",
                        "category": "form", "goal": "gp", "budget": {"steps": 5},
                        "success_assertion": {"type": "text_contains", "value": "x"}}),
        ]) + "\n", encoding="utf-8")

        # tB：benchmark 域 → 跳过；带 invalid shadow 统计 + b_reject(也跳过)
        w(logs / "tB.jsonl", [
            shadow("tB", 0, False), step_ev("tB", shadow_status="invalid"),
            step_ev("tB", code="choice_mismatch"), result("tB", "true_success"),
        ])
        # tT：训练域 → 保留；2 轮 1 fp → fp_rate 0.5 → high_variance
        w(logs / "tT.jsonl", [
            shadow("tT", 0, False), result("tT", "false_positive"),
            shadow("tT", 0, True), result("tT", "true_success"),
        ])
        # tP：占位域 → keep + domain_unverified
        w(logs / "tP.jsonl", [
            shadow("tP", 0, False), result("tP", "false_positive"),
        ])
        # 轮次后缀文件名（#5 约定 tX_r0）→ tid 还原
        w(logs / "tT_r0.jsonl", [
            shadow("tT", 0, False), shadow("tT", 0, True),
            result("tT", "true_success"),
        ])
        (logs / "tT.jsonl").unlink()  # 用轮次版文件名替代（#5 的实际落盘格式）

        out = root / "samples"
        bf0 = root / "bench0.txt"
        bf0.write_text("www.bench.example.com\n", encoding="utf-8")  # 带 www. 测归一
        old_argv = sys.argv
        sys.argv = ["sample_extractor", "--logs", str(logs), "--tasks", str(tasks),
                    "--out", str(out), "--benchmark-domains", str(bf0)]
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                rc = main()
        finally:
            sys.argv = old_argv
        check("main exit 0", rc == 0)

        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        c_rows = [json.loads(x) for x in
                  (out / "c_pairs.jsonl").read_text(encoding="utf-8").splitlines() if x]
        a_rows = [json.loads(x) for x in
                  (out / "a_positive.jsonl").read_text(encoding="utf-8").splitlines() if x]
        b_rows = [json.loads(x) for x in
                  (out / "b_reject.jsonl").read_text(encoding="utf-8").splitlines() if x]

        check("tB benchmark skipped (含 r 后缀 tid 还原)",
              manifest["counts"]["skipped_benchmark"] == 2)
        # tT 现在只剩 _r0 文件：1 disagree + 1 agree → c=1 / a=1；fp 文件被删 → rounds 仅 _r0
        check("c_pairs = tT_r disagree + tP", len(c_rows) == 2)
        check("a_positive agree+success", len(a_rows) == 1)
        check("缺陷#7: a_positive 携带被背书的 decision",
              a_rows[0].get("decision", {}).get("target") == "1")
        check("b_reject bench-skipped", len(b_rows) == 0
              and manifest["counts"]["b_reject_skipped"] == 1)
        check("shadow invalid counted", manifest["shadow_status"].get("invalid") == 1)

        tt = [r for r in c_rows if r["task_id"] == "tT"][0]
        check("tid suffix restored", tt["task_id"] == "tT")
        check("c_pairs not high_variance（tT_r0 单轮全 PASS）",
              tt["high_variance"] is False
              and "tT" not in manifest["high_variance_tasks"])
        check("C3 structured rebuilt", "CLICK" in tt["candidates_structured"]["targets"])
        check("C3 rendered element line", "[1] A [CLICK]" in tt["candidates_rendered"]
              and "[2] B [TYPE_TEXT]" in tt["candidates_rendered"])
        check("C3 rendered has ops block", "CLICK:" in tt["candidates_rendered"])
        check("chosen=teacher rejected=local",
              tt["chosen"]["target"] == "2" and tt["rejected"]["target"] == "1")
        check("C4 fields", tt["source"] == "api" and tt["api_model"] == "mock-t")
        check("contamination clean", manifest["contamination_check"]["violations"] == 0
              and manifest["contamination_check"]["checked_rows"] == 3)

        tpp = [r for r in c_rows if r["task_id"] == "tP"][0]
        check("placeholder → unverified", tpp.get("domain_unverified") is True
              and tpp.get("domain_placeholder") is True)
        check("tP fp_rate 1.0 → high_variance", tpp["high_variance"] is True)
        check("high_variance_tasks", manifest["high_variance_tasks"] == ["tP"])
        check("domain distribution counts c+a rows",
              manifest["domain_distribution"].get("train.example.org") == 2)

        # 库接口（#5 契约）：tasks=list + 原始形态域集合（带 www.）直接可用
        specs = _load_tasks(tasks)
        out2 = root / "samples2"
        m2 = extract_all(logs, out2, tasks=specs,
                         benchmark_domains={"www.bench.example.com"},
                         training_domains={"other.example.net"})
        check("extract_all contract: returns manifest counts",
              m2["counts"]["c_pairs"] == 1  # 占位域按设计 keep（unverified 可见优于静默跳过）
              and m2["counts"]["skipped_not_training"] >= 2)
        check("extract_all normalization: www benchmark caught",
              m2["counts"]["skipped_benchmark"] >= 1)

        # 缺陷#6 回归（隔离块，不共享上面的期望值）：轮次子目录 logs/…/rN/ 必须
        # 被扫到——平层 glob 曾漏读全部影子（实况 c_pairs=0 vs 日志 725 条影子）。
        with tempfile.TemporaryDirectory() as tmp2:
            r2 = Path(tmp2)
            sub = r2 / "logs" / "r7"
            sub.mkdir(parents=True)
            rtasks = r2 / "tasks.jsonl"
            rtasks.write_text(json.dumps(
                {"task_id": "rT", "domain": "http://localhost/", "category": "list",
                 "goal": "rg", "budget": {"steps": 5},
                 "success_assertion": {"type": "url_matches", "pattern": "."}}) + "\n",
                encoding="utf-8")
            w(sub / "rT_r7.jsonl", [shadow("rT", 0, False)])
            rm = extract_all(r2 / "logs", r2 / "samples",
                             tasks=_load_tasks(rtasks),
                             benchmark_domains={"bench.example.com"},
                             training_domains={"localhost"})
            check("缺陷#6: 轮次子目录被扫到且分歧对成对",
                  rm["counts"]["teacher_shadow_events"] == 1
                  and rm["counts"]["c_pairs"] == 1)

    print(f"SMOKE OK: {passed}/{total}")


if __name__ == "__main__":
    if "--smoke" in sys.argv:
        _smoke()
    else:
        sys.exit(main())
