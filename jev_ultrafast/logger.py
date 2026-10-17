"""Logger.

只读式抽取 agent 运行事件，落盘为 JSONL。

关联硬约束：
  A9  事件格式是 Runtime 的产物，由本模块离线抽取
  C4  训练样本必须携带来源（decider/helper 的 model 字段）
  E5  事件是四维失败（result / quadrant / failure_class / failure_mode）的输入源

设计要点：
  - 只读 agent.state / agent.step_budget，绝不修改
  - 游标式：每次 observe() 只输出新增事件
  - 事件类型：step / decision / text_call / budget_transition / task_result /
    teacher_shadow / **swallow**（静默降级，见 record_swallow）
  - 一个 task 一个 JSONL
  - 不 import agent，用鸭子类型

已知边界（Step 9 观察 #2）：
  终态（DONE/BLOCKED）分支 state.pop("pre_execute") 后早返回，不写 history。
  因此终态的预算快照不会出现在 step 事件里。
  Logger 用 task_result.final_budget 补偿。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Optional


EVENT_STEP              = "step"
EVENT_DECISION          = "decision"
EVENT_TEXT_CALL         = "text_call"
EVENT_BUDGET_TRANSITION = "budget_transition"
EVENT_TASK_RESULT       = "task_result"
EVENT_TEACHER_SHADOW    = "teacher_shadow"
#: 静默降级事件。它必须**独立于 step 事件**：宽 except 的那些点（装防御、settle 判据、
#: 归属探针）发生在"拍与拍之间"，没有对应的 history 条目可挂；硬塞进 step 白名单就得
#: 给 history 造一条假条目——那是把仪器塞进数据结构的老坑。
#: 落 `logs/<tag>/<id>.jsonl`，与其余事件同一份文件 ⇒ 批里 grep "swallow" 数得到。
EVENT_SWALLOW           = "swallow"


# ---------------------------------------------------------------------------
# 序列化
# ---------------------------------------------------------------------------

def dbg(site: str, detail: str = "") -> None:
    """`JEV_DEBUG` 才出声的一行留痕（#68）。默认零输出，批日志与报告格式一字不变。

    存在的理由：仓库里有 29 处宽 `except Exception`，其中少数几处**会改变解释**——
    `skills.route()` 把技能异常吞成 `d = None`，行为正确（回落模型），但没人知道是哪个技能抛了什么；
    #59 那一轮"技能明明能判达却被读成模型能力问题"就是这个形状。留痕不改控制流：
    降级照旧降级，只是出事时能在 stderr 看到一行。
    """
    if not (os.environ.get("JEV_DEBUG") or "").strip():
        return
    sys.stderr.write(f"[dbg] {site}: {detail}" + chr(10))


# ---------------------------------------------------------------------------
# 静默降级留痕（#68 的第二半）
# ---------------------------------------------------------------------------

#: 单一收口。所有"宽 except 之后必须留痕"的点都调它，好处是**每一处只有一条通道**：
#: 将来要换缓冲区、要加上限、要把摘要写进报告，只改这里一处，不用动任何一个调用点。
#: 模块级而不是 Logger 实例上：logger 是 runner 建的，而 swallow 发生在 Browser/Agent
#: 生命周期的任何时刻（很多早于第一次 observe）——把计数器挂在实例上等于把前几步的
#: 降级丢在磁盘外（#67 那一族的老形状）。
#:
#: 两份状态，两种用途，缺一不可：
#:   _SWALLOWED       待搬进 jsonl 的队列，被 Logger._drain_swallows() 抽干；
#:   _SWALLOW_TOTALS  进程级累计，永不被抽干。汇总要的是"这一进程里发生过什么"，
#:                    而队列在第一次 observe 后就空了（降级常发生在 logger 存在之前）。
#:                    只写队列的那一版会让 summary 恒为 []，而它是 reports/*.json 的唯一来源。
_SWALLOWED: list[dict] = []
_SWALLOW_TOTALS: dict[str, dict] = {}


def exc_diag(e: BaseException) -> str:
    """异常的**有界**诊断串：类型名 + str 截断。

    两件事是刻意的：

    1. **不吞类型名**。#59 的形状是"不知道哪个技能抛了什么"，所以 `ValueError` 这三个字
       本身就是要留下的第一信息；
    2. **截断而不是全文**。异常串里可能带第三方页面内容（URL、查询串）——#79 的纪律是
       第三方内容不进可分享工件，超长 traceback 还会把一行 jsonl 撑爆。
    """
    try:
        return f"{type(e).__name__}: {str(e)[:120]}"
    except Exception:                                     # noqa: BLE001
        # 只可能是 str(e) 自己炸的怪对象。摘要已经退到类型名（信息只剩这一件），
        # 再往下追一层就是"诊断器自己的异常没人管"——那比它要报的事故更糟。
        return type(e).__name__


def record_swallow(site: str, detail: str = "") -> None:
    r"""静默降级的**工件级**留痕（t9：把 #68 的 dbg 从"看不见"变成"数得到"）。

    病灶不是没有痕迹，是痕迹长在**一个批里从来不开的开关后面**：`dbg()` 只在
    `JEV_DEBUG` 设置时写 stderr，而仓库里没有任何 runner 设它（ci_local.ps1 / run_one.ps1 /
    m1/run_tasks.py / scripts/smoke.ps1 全数过）。于是 11 处 `dbg` 站点在每一批的每一个
    工件里都是零输出——包括 `browser.py` 那 11 处宽 except：**browser.py 至今一条 print
    诊断都没有**。

    这个函数同时满足三条纪律：

    1. **不走开关**。默认就记账，`JEV_DEBUG` 只决定**是否**额外往 stderr 喊一嗓子；
    2. **不改控制流**。它只读异常、写自己的缓冲区，调用点的 return/raise/降级一字不动；
    3. **有界**。异常类型 + 120 字符摘要，第三方正文不带进去（#79/#75 同族）。

    产物怎么到复核者手上：`Logger.observe()` 每次把缓冲区抽干，写成
    `"event": "swallow"` 的 JSONL 行——`logs/` 是批里就地可查的权威工件；
    `swallow_summary()` 的站点汇总由 `evaluator._meta` 白名单带进 `reports/*.json`。
"""
    site = str(site)
    detail = str(detail)[:120]
    _SWALLOWED.append({"site": site, "detail": detail})
    total = _SWALLOW_TOTALS.setdefault(site, {"site": site, "count": 0, "kinds": {}})
    total["count"] += 1
    kind = (detail or "").split(":", 1)[0] or "unknown"
    total["kinds"][kind] = total["kinds"].get(kind, 0) + 1
    if (os.environ.get("JEV_DEBUG") or "").strip():
        dbg(site, detail)


def swallow_summary() -> list[dict]:
    """本进程至今的降级汇总（按站点 → 次数 + 本类异常的 repr）。

    runner 把它写进 `meta.swallow`、由 `evaluator._meta` 带进 `reports/*.json`：
    报告是可分享的权威工件，只看报告的复核者不必去 grep jsonl。
    **没发生过的降级一个键都不写**（与 `arrival_relook_ms` / `err` 同一口径），
    否则每一行的 meta 都塞满空结构。
    """
    return sorted((dict(v, kinds=dict(v["kinds"])) for v in _SWALLOW_TOTALS.values()),
                  key=lambda x: x["site"])


def reset_swallows() -> None:
    r"""清空降级记账（测试与 m4a 那种"一个进程拼多个模块"的装载器用）。

    只清状态不动通道：`record_swallow` 本身必须幂等可重入，测试才能反复灌同一条。
    生产路径不调它——一个批一个进程，累计值就是这一批的读数。
    """
    _SWALLOWED.clear()
    _SWALLOW_TOTALS.clear()


def _to_jsonable(obj: Any) -> Any:
    """dataclass / Enum / 嵌套结构 → JSON 可序列化。"""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if is_dataclass(obj):
        return {k: _to_jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    if hasattr(obj, "value"):  # Enum
        return obj.value
    return str(obj)


# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

#: Chrome 自己的网络错误码名（#85）。只提这个 token，本地化文案一概不留进产物。
_ERR_CODE_RE = re.compile(r"ERR_[A-Z][A-Z0-9_]{2,}")


def page_digest(page: Optional[dict]) -> dict:
    """#75：**评测吃的那份正文**的可复核摘要 —— 只有一个来源，runner 与 logger 都从这里取。

    带四件：url / title / 正文长度 / 正文 16 位 sha1；另加**一件稀疏的**：错误页的码名。
    整段正文不入库（体积，以及第三方页面内容没必要跟着报告走）；长度足以认出"这是半帧"
    （docs 族实测 654 → 1454），sha1 足以确认两次读数是不是同一份页。

    `err`（#85）只在正文里出现 Chrome 自己的 `ERR_*` 码名时才写：批里那些
    `chrome-error://` 行以前只有 `text_len=83`，归因只能写成"环境"而写不出**哪一种**环境
    （10-14 的 sqlite 探针第一次把它抓成 `ERR_SSL_PROTOCOL_ERROR` = 本地代理的 TLS 隧道断）。
    提的是码名不是文案 —— 本地化句子不进仓，且健康页不写这个键（与 `arrival_relook_ms` 同一口径）。
    """
    if not isinstance(page, dict):
        return {}
    txt = page.get("text") or ""
    out = {
        "url":   page.get("url"),
        "title": page.get("title"),
        "text_len": len(txt),
        "text_sha16": hashlib.sha1(txt.encode("utf-8", "replace")).hexdigest()[:16],
    }
    m = _ERR_CODE_RE.search(txt)
    if m:
        out["err"] = m.group(0)
    return out


class Logger:
    def __init__(
        self,
        task_id: str,
        log_dir: str | Path,
        *,
        flush_every: int = 32,
    ) -> None:
        if not task_id:
            raise ValueError("task_id required")
        self.task_id = task_id
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.log_dir / f"{task_id}.jsonl"
        self.flush_every = max(1, int(flush_every))

        self._history_cursor = 0
        self._decisions_cursor = 0
        self._text_calls_cursor = 0
        self._transitions_cursor = 0
        self._teacher_cursor = 0
        self._buffer: list[dict] = []
        self._file = None  # lazy open

    # --- 主入口 ---

    def observe(self, state: dict, *, step_budget=None) -> list[dict]:
        """抽取 state 的新增事件。

        state:       agent.state（或等价的 dict）
        step_budget: agent.step_budget（可选，用于 budget_transition）

        返回本次新增事件列表；事件同时进入内部 buffer，达阈值自动 flush。
        """
        if not isinstance(state, dict):
            raise TypeError("state must be a dict")

        now = time.time()
        new_events: list[dict] = []

        # 1. step
        history = state.get("history") or []
        for h in history[self._history_cursor:]:
            new_events.append({
                "event":     EVENT_STEP,
                "task_id":   self.task_id,
                "timestamp": now,
                **self._clean_step(h),
            })
        self._history_cursor = len(history)

        # 2. decision
        decisions = state.get("decisions") or []
        for d in decisions[self._decisions_cursor:]:
            new_events.append({
                "event":     EVENT_DECISION,
                "task_id":   self.task_id,
                "timestamp": now,
                **self._clean_decision(d),
            })
        self._decisions_cursor = len(decisions)

        # 3. text_call
        text_calls = state.get("text_calls") or []
        for t in text_calls[self._text_calls_cursor:]:
            new_events.append({
                "event":     EVENT_TEXT_CALL,
                "task_id":   self.task_id,
                "timestamp": now,
                **self._clean_text_call(t),
            })
        self._text_calls_cursor = len(text_calls)

        # 4b. teacher_shadow（M2）
        teacher_decisions = state.get("teacher_decisions") or []
        for td in teacher_decisions[self._teacher_cursor:]:
            new_events.append({
                "event":     EVENT_TEACHER_SHADOW,
                "task_id":   self.task_id,
                "timestamp": now,
                **self._clean_teacher_decision(td),
            })
        self._teacher_cursor = len(teacher_decisions)

        # 4. budget_transition
        if step_budget is not None:
            transitions = getattr(step_budget, "transitions", None) or []
            for tr in transitions[self._transitions_cursor:]:
                new_events.append({
                    "event":     EVENT_BUDGET_TRANSITION,
                    "task_id":   self.task_id,
                    "timestamp": now,
                    **_to_jsonable(tr),
                })
            self._transitions_cursor = len(transitions)

        # 5. swallow（t9）。**抽干**进程级缓冲区：发生在"拍与拍之间"的宽 except 没有
        # state 可读，只能靠这里把记账搬进 jsonl。放在 self._history_cursor 等游标之后、
        # 返回之前：一次 observe 若既来了 history 又来了降级，两者的先后关系仍然按发生序。
        new_events.extend(self._drain_swallows(now))

        self._buffer.extend(new_events)
        if len(self._buffer) >= self.flush_every:
            self.flush()
        return new_events

    def _drain_swallows(self, now: float) -> list[dict]:
        """把进程级 swallow 缓冲区搬成事件（t9）。抽空，同一条只落盘一次。

        两个刻意的选择：

        - **缓冲进程级、游标实例级**：buffer 属于本 Logger，清空等于认领。多个 task 共用
          一个进程时不会把上一题的降级搬进下一题的 jsonl（游标式的同一纪律）。
        - **`site` 不折叠**：每一条降级都是一次事实，批里要能数到"这一题发生了几次"。
          汇总按站点折叠是 `swallow_summary()` 的事，不进日志。
        """
        emitted: list[dict] = []
        while _SWALLOWED:
            item = _SWALLOWED.pop(0)
            emitted.append(self._swallow_event(item, now))
        return emitted

    def _swallow_event(self, item: dict, now: float) -> dict:
        """一条降级的落盘形状。键名与其余事件一致：event / task_id / timestamp 三件套。

        `site` / `detail` 直接来自 `record_swallow`；`detail` 在记录时就截过 120 字符，
        这里不再加工——**摘要算法只有一处**（与 `page_digest` 同一条纪律）。
        """
        return {
            "event":     EVENT_SWALLOW,
            "task_id":   self.task_id,
            "site":      item.get("site"),
            "detail":    item.get("detail"),
            "timestamp": now,
        }

    def finalize(
        self,
        task_result: Any,
        *,
        step_budget=None,
        final_page: Optional[dict] = None,
        state_paid_ms: Optional[int] = None,
    ) -> dict:
        """写入 task_result 事件并 flush。

        task_result: evaluator.TaskResult（dataclass）或等价 dict
        step_budget: 可选，用于终态预算快照（补偿终态 pre_execute 丢失）
        final_page:  可选，最终页面的 url / title
        """
        if is_dataclass(task_result):
            result_dict = _to_jsonable(task_result)
        elif isinstance(task_result, dict):
            result_dict = _to_jsonable(task_result)
        else:
            raise TypeError("task_result must be dataclass or dict")

        event: dict = {
            "event":     EVENT_TASK_RESULT,
            "task_id":   self.task_id,
            "timestamp": time.time(),
            "result":    result_dict,
        }
        if step_budget is not None:
            event["final_budget"] = self._budget_snapshot(step_budget)
        # #65：这一行在收口前为重看付了多少毫秒（没付就不写这个键）。
        # 批里"这一刀花了多少秒"必须是产物里数得出来的，不靠墙钟差猜。
        _paid = state_paid_ms if state_paid_ms is not None else None
        if _paid:
            event["arrival_relook_ms"] = int(_paid)
        if final_page is not None:
            # #75：评测吃的那份正文必须留下可复核的痕迹。**算法只有一份**（`page_digest`），
            # runner 往 reports/*.json 写的也是它 —— 两处各抄一遍迟早漂。
            event["final_page"] = page_digest(final_page)

        self._buffer.append(event)
        self.flush()
        return event

    # --- IO ---

    def flush(self) -> None:
        if not self._buffer:
            return
        if self._file is None:
            self._file = self.log_path.open("a", encoding="utf-8")
        for ev in self._buffer:
            self._file.write(json.dumps(ev, ensure_ascii=False) + "\n")
        self._file.flush()
        self._buffer.clear()

    def close(self) -> None:
        self.flush()
        if self._file is not None:
            self._file.close()
            self._file = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    # --- 清理 ---

    #: 有意不落的 step 字段。**加了新 history 字段而不登记在这里，`tests/test_logger_step_fields.py`
    #: 会红**——字段静默留在内存、丢在磁盘外，是 #59 那类"读日志读不到依据"的成因。
    STEP_DROP_KEYS = frozenset({"usage"})

    @staticmethod
    def _clean_step(h: dict) -> dict:
        """step 白名单。None 保留（page_changed=None 表示 observe 失败）。

        `outcome` / `url_from` / `page_fp_before` / `skill` 是后补的：前三个是**到达判据在读的字段**
        （`agent.py:605-623` 观测归静后结算出来的 outcome、#59 同主机守卫要的出发页、Fix P 的
        指纹依据），`skill` 记这一拍由哪个地板技能发出。2026-10-11 晚 b33 拆堆时，这四个都不在日志里，
        结果"结果文本何时出现"只能靠重开浏览器复探——诊断仪器不该缺这个。
        """
        keys = (
            "step", "action", "kind", "choice", "operation", "target",
            "confidence", "probability", "latency_ms",
            "text", "text_helper", "text_latency_ms",
            "page_changed", "url", "url_from", "page_fp_before", "outcome", "skill",
            "elapsed_ms", "executed_ms",
        )
        out = {k: h[k] for k in keys if k in h}
        if "pre_execute" in h:
            out["pre_execute"] = _to_jsonable(h["pre_execute"])
        if "outcome" in out:
            out["outcome"] = _to_jsonable(out["outcome"])
        return out

    @staticmethod
    def _clean_decision(d: dict) -> dict:
        keys = (
            "choice", "operation", "target",
            "operation_confidence", "target_confidence", "confidence",
            "model", "latency_ms", "usage",
            "fingerprint", "elapsed_ms", "rejected",
            "skill",                       # M16 技能层：命中时记录技能名（诊断/归因用）
        )
        out = {k: d[k] for k in keys if k in d}
        if "probabilities" in d:
            out["probabilities"] = _to_jsonable(d["probabilities"])
        return out

    @staticmethod
    def _clean_text_call(t: dict) -> dict:
        keys = ("model", "field", "value", "latency_ms", "usage")
        return {k: t[k] for k in keys if k in t}

    @staticmethod
    def _clean_teacher_decision(td: dict) -> dict:
        """白名单。保留 actions_snapshot（供 sample_extractor 重建 candidates）。

        C3 落地：actions_snapshot 是 structured 源；
        rendered 由 sample_extractor 从 actions_snapshot 重放 action_space 得到。
        """
        keys = (
            "step",
            "local", "teacher",
            "agree", "operation_match", "target_match",
            "latency_ms", "usage",
        )
        out = {k: td[k] for k in keys if k in td}
        if "actions_snapshot" in td:
            out["actions_snapshot"] = td["actions_snapshot"]
        # M4b Logger v2：page/history 快照（SFT user prompt 与线上推理同构）
        if "page_snapshot" in td:
            out["page_snapshot"] = td["page_snapshot"]
        if "history_snapshot" in td:
            out["history_snapshot"] = td["history_snapshot"]
        return out

    @staticmethod
    def _budget_snapshot(step_budget) -> dict:
        try:
            return _to_jsonable(step_budget.log_entry())
        except Exception as e:
            # t5 普查标 med：预算快照**静默**变成 {}，而它是"这一题烧了多少预算"的
            # 唯一证据来源 —— 丢掉之后 step_budget 的任何回归都读不出来。
            record_swallow("budget_snapshot_failed", exc_diag(e))
            return {}
