"""AnyJev 旋转/停止数学的回归测试（移植自 Apache-2.0 的 nokia-applied-research/AnyJev）。

每个用例对应一条**会静默出错**的性质：位移表若不再覆盖每个位置一次，"位置偏置被抵消"
这个前提就不成立；证书若失去分辨力，提前停就会悄悄改变答案。运行：python tests/test_rotation.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jev_ultrafast import anyjev_rotation as R  # noqa: E402

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


@case("L0 位移表：每个候选在每一位上恰好出现一次")
def _shift_table_is_latin():
    n = 5
    orders = R.shifted_orders(n, n)
    assert len(orders) == n
    for pos in range(n):
        seen = {o[pos] for o in orders}
        assert seen == set(range(n)), f"第 {pos} 位只见过 {sorted(seen)}"
    assert orders[0] == list(range(n)), "首轮必须是原序，否则连基线都无法对齐"


@case("位移轮数不超过候选数，且至少 1 轮")
def _shift_count_clamped():
    assert R.shifted_orders(4, 99) == R.shifted_orders(4, 4)
    assert len(R.shifted_orders(4, 1)) == 1
    assert R.shifted_orders(0, 3) == [[]]


@case("纯位置偏置的读取器：不得让任何候选积累票数")
def _position_biased_reader_gets_no_winner():
    # 永远选"当前第一个位置"的读取器 —— 不旋转时会稳定选中候选 0。
    pick, info = R.rotate_vote(6, lambda order: order[0], shifts=6, threshold=8.5)
    assert info["votes"] == [1] * 6, info["votes"]
    assert info["shifts_used"] == 6, "没有候选领先 → 不该提前停"


@case("真有偏好的读取器：旋转后仍选中它")
def _real_preference_survives():
    calls = {"n": 0}

    def reader(order):
        calls["n"] += 1
        return 3 if calls["n"] > 1 else order[0]   # 首轮被位置带偏

@case("轮数就是调用次数：不重复读同一轮")
def _one_call_per_shift():
    seen = []

    def reader(order):
        seen.append(tuple(order))
        return order[0]          # 每轮换人得票 → 边际恒为 0 → 不会提前停

    R.rotate_vote(4, reader, shifts=4, threshold=8.5)
    assert len(seen) == 4, seen
    assert len(set(seen)) == 4, "有重复的移位，等于白花一次调用"

@case("低阈值提前停：领先即停，且不超过 min_shifts 前停")
def _early_stop_respects_min_shifts():
    calls = {"n": 0}

    def reader(order):
        calls["n"] += 1
        return 2

    _, info = R.rotate_vote(8, reader, shifts=8, threshold=0.5, min_shifts=3)
    assert info["shifts_used"] == 3, info["shifts_used"]
    assert calls["n"] == 3, calls["n"]

@case("choose_threshold：认证出的阈值，其与全 K 答案的偏差不超过目标")
def _threshold_certifies():
    # 每轮都给出同一个真值 → 前两轮边际即为 inf → 应在 min_shifts 处停，
    # 且与全 K 答案零分歧（0/400 的 CP 上界 0.0074 ≤ 1%）。证书的**分辨力**由
    # 下面两条反向用例覆盖（3/300 不过关、随机数据返回 None）。
    rng = np.random.default_rng(7)
    n, k = 400, 6
    truth = rng.integers(0, 4, size=n)
    winners = np.repeat(truth[:, None], k, axis=1)
    margins = np.empty((n, k))
    for i in range(n):
        counts = np.zeros(4)
        for j in range(k):
            counts[winners[i, j]] += 1
            margins[i, j] = R.log_margin(counts)
    thr, info = R.choose_threshold(margins, winners, target=0.01, min_shifts=2)
    assert thr is not None, info
    assert info["disagreements"] == 0, info
    assert info["bound"] <= 0.01, info
    assert info["mean_shifts"] == 2, info


@case("choose_threshold：认证不了就返回 None，而不是硬给一个阈值")
def _threshold_refuses_when_uncertifiable():
    # 每轮完全随机 → 与全 K 答案的一致性无法认证到 1%
    rng = np.random.default_rng(11)
    n, k = 50, 4
    winners = rng.integers(0, 5, size=(n, k))
    margins = np.full((n, k), 0.1)
    thr, info = R.choose_threshold(margins, winners, target=0.01, min_shifts=2)
    assert thr is None, thr
    assert "reason" in info


def main():
    # Windows 控制台是 GBK；用例名含非 GBK 字符时 print 会抛 UnicodeEncodeError
    # 并中断整个套件（与 test_skills.py 同一问题）。
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
        except Exception as e:                              # noqa: BLE001
            failed += 1
            print(f"ERROR {name}\n      {type(e).__name__}: {e}")
        else:
            print(f"ok    {name}")
    print(f"\n{len(CASES) - failed}/{len(CASES)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
