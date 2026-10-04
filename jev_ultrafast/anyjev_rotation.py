"""L0 位置偏差消解 + 自适应旋转预算。

移植自 AnyJev（Apache-2.0，nokia-applied-research/AnyJev）：
  - `anyjev/calibrate/stopping.py`（log-odds margin / Clopper-Pearson / 阈值选择）
  - README 与 docs/rotation_budget.md 描述的 L0 语义（每个选项轮流占据每个位置一次）

为什么接这里：我们的 Decider 把候选动作按 `action_space()` 的顺序编号成 1..N 交给模型，
**选项的先后本身会影响答案**（AnyJev 在 Qwen3-8B/BANKING77 上实测 raw 的顺序翻转率
0.230）。把同一个问题按候选的**循环移位**各问一遍，让每个候选在每位上出现一次，
位置偏置就被精确抵消；再用"与全 K 轮答案的一致率"作为证书提前停（证书不需要标签，
参照答案就是全 K 轮自己给出的答案）。

与上游的差异：上游读的是 next-token 的 label marginal，我们是生成式 decider，每轮只给出
一个点答案 → 边际就是各候选的**得票率**，log-odds margin 作用在得票率上。`cp_upper`
等统计函数原样保留。
"""
from __future__ import annotations

from math import lgamma
from typing import Callable, Optional, Sequence

import numpy as np

EPS = 1e-12

#: 上游在四个 (model, task) 单元、K=18-20 上认证过的默认阈值：全 K 答案一致率 ≥99% 的最小
#: log-odds margin。我们的 K（候选数）与题型都不同，未经验证 —— 用它做**起点**，不要当保证。
DEFAULT_LOG_MARGIN = 8.5


def log_margin(marginal: Sequence[float]) -> float:
    """边际 top-1 与 top-2 的 log 差。对归一化不变（两边同除一个总数不影响 log 差），
    因此可以直接作用在未归一化的得票数上。"""
    p = np.sort(np.asarray(marginal, dtype=np.float64))[::-1]
    if p.size < 2:
        return float("inf")
    if p[0] <= EPS:
        return 0.0
    return float(np.log(max(p[0], EPS)) - np.log(max(p[1], EPS)))


def binom_cdf(k: int, n: int, p: float) -> float:
    """P[X <= k]，X ~ Binomial(n, p)，log 空间求和（只用标准库 + numpy）。"""
    if n <= 0 or p <= 0.0:
        return 1.0
    if p >= 1.0:
        return 1.0 if k >= n else 0.0
    k = min(k, n)
    ks = np.arange(0, k + 1)
    log_choose = np.asarray([lgamma(n + 1) - lgamma(int(i) + 1) - lgamma(n - int(i) + 1)
                             for i in ks])
    terms = log_choose + ks * np.log(p) + (n - ks) * np.log1p(-p)
    top = float(terms.max())
    return float(np.exp(top) * np.exp(terms - top).sum())


def cp_upper(k: int, n: int, delta: float = 0.05, iters: int = 60) -> float:
    """失败率的 Clopper-Pearson 上置信界：n 次里观测到 k 次失败时，置信度 1-delta 下
    仍然相容的最大失败率。用点估计选阈值不能保住留出集（上游实测 0.013-0.025 对 1%
    目标），上界才是证书（同条件下 0.000-0.008）。"""
    if n <= 0 or k >= n:
        return 1.0
    lo, hi = k / n, 1.0
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        if binom_cdf(k, n, mid) > delta:
            lo = mid
        else:
            hi = mid
    return float(hi)


def stop_step(margins: Sequence[float], threshold: float, min_shifts: int) -> int:
    """该阈值下会读几轮。`margins[p]` 是读到第 p+1 轮时的 log-odds margin。
    返回 1..len(margins)；等于 len 表示从未提前停。"""
    m = np.asarray(margins, dtype=np.float64)
    ok = m >= threshold
    ok[: max(0, min_shifts - 1)] = False
    return int(np.argmax(ok) + 1) if bool(ok.any()) else int(m.size)


def choose_threshold(margins: np.ndarray, winners: np.ndarray, target: float = 0.01,
                     min_shifts: int = 2, delta: float = 0.05,
                     grid: Optional[Sequence[float]] = None) -> tuple[Optional[float], dict]:
    """在与"读满 K 轮"的答案一致率能以 `target` 为上限**认证**的前提下，最便宜的阈值。

    margins/winners：[N, K]，第 i 行是第 i 个状态读 1..K 轮的运行值。
    参照答案取 `winners[:, -1]`（全 K 轮自己的答案），全程不需要标签。
    返回 (threshold, info)；无法认证时 threshold 为 None，调用方应读满 K 轮。
    """
    margins = np.asarray(margins, dtype=np.float64)
    winners = np.asarray(winners)
    n, k = margins.shape
    reference = winners[:, -1]
    if grid is None:
        grid = np.arange(0.0, 20.01, 0.25)
    for thr in grid:
        used = np.asarray([stop_step(margins[i], float(thr), min_shifts) for i in range(n)])
        pred = winners[np.arange(n), used - 1]
        bad = int(np.sum(pred != reference))
        bound = cp_upper(bad, n, delta)
        if bound <= target:
            return float(thr), {"n": n, "K": int(k), "target": target, "delta": delta,
                                "disagreements": bad, "bound": bound,
                                "mean_shifts": float(used.mean()),
                                "max_shifts": int(used.max()),
                                "shifts_saved": float(k - used.mean())}
    return None, {"n": n, "K": int(k), "target": target, "delta": delta,
                  "reason": "no threshold in the grid could be certified at this target"}


# ---------------------------------------------------------------------------
# 我们的适配层：生成式 decider 的循环移位读取
# ---------------------------------------------------------------------------

def shifted_orders(n: int, shifts: int) -> list[list[int]]:
    """n 个候选、读 `shifts` 轮时的位置置换表。

    第 r 轮返回一个长度 n 的下标表：候选按它重排后再交给模型。r=0 是原序（保证至少
    有一轮与不旋转时**逐字相同**，否则"旋转版"连基线都无法对齐）。后续每轮整体左移
    1 位 —— n 轮读完，每个候选在每一位上恰好出现一次（L0 的定义）。
    """
    if n <= 0:
        return [[]]
    shifts = max(1, min(int(shifts), n))
    return [list(range(r, n)) + list(range(0, r)) for r in range(shifts)]


def rotate_vote(
    n: int,
    read_one: Callable[[list[int]], Optional[int]],
    *,
    shifts: int = 3,
    threshold: float = DEFAULT_LOG_MARGIN,
    min_shifts: int = 2,
) -> tuple[Optional[int], dict]:
    """按循环移位反复读，累计得票，边际够稳就提前停。

    read_one(order) 拿到的是"候选下标的重排表"，应返回该轮选中的**原候选下标**
    （拿不准就返回 None，该轮弃权）。返回值是 (胜出的原候选下标, 诊断)。
    提前停的判据用 log-odds margin（概率差会饱和：边际一旦尖峰就再携带不了信息，
    而这正是需要判定的区间）。

    关于阈值：`DEFAULT_LOG_MARGIN=8.5` 是上游在 K=18-20、按 next-token **概率**边际标定的。
    我们是生成式 decider，每轮只出一个点答案，边际是 **S 轮得票数**（S=2..6），
    log(2/1)≈0.7 就到顶了 —— 用 8.5 等于**永不提前停**，即读满 `shifts` 轮。这是安全的
    默认（多花调用但不改变答案）；要真正省调用，必须用 `choose_threshold` 在自己的无标签
    数据上重新认证，再经 `DECIDER_ROTATION_MARGIN` 传进来。
    """
    orders = shifted_orders(n, shifts)
    votes = np.zeros(n, dtype=np.float64)
    margins: list[float] = []
    winners: list[int] = []
    chosen: Optional[int] = None
    used = 0
    for order in orders:
        used += 1
        pick = read_one(order)
        if pick is not None and 0 <= pick < n:
            votes[pick] += 1.0
        if votes.sum() <= 0:
            margins.append(0.0)
            winners.append(0)
            continue
        chosen = int(np.argmax(votes))
        winners.append(chosen)
        margins.append(log_margin(votes))
        if used >= min_shifts and margins[-1] >= threshold:
            break
    info = {
        "shifts_used": used,
        "shifts_available": len(orders),
        "votes": votes.astype(int).tolist(),
        "margins": [round(m, 3) for m in margins],
        "threshold": threshold,
    }
    return chosen, info
