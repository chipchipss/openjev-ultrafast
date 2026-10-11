"""批路径的出口预检：网络不通时**不许**写报告（b30 的教训）。

现场（`reports/real-1011-b30-100-1011-193627.json`，100 行）：`:2080` 出口代理已经死了
（`Get-NetTCPConnection -LocalPort 2080 -State Listen` 数量 0；走它取 numpy 返回 000），
而自有 Chrome 是用 `--proxy-server=http://127.0.0.1:2080` 起的。结果：
94/100 行 `steps=0`、终点 `chrome-error://chromewebdata/`，评测器照跑、报告照写，
得到一份 **"6/100"** 的读数是**环境阻断**，不是能力读数。
`run_baseline_19.ps1` 早就有 "Step 3.5: preflight reachability of task domains"，
`scripts/run_one.ps1` 这条批路径却没有——所以这一刀补在 `m1/run_tasks.py` 上。

判据取"有没有拿到回应"，不取状态码：**403/404 说明出口是通的**，那是站点的墙
（r101/r104 那种），必须照常跑批；只有连接层失败（超时/拒绝/DNS）才 abort。

运行：python tests/test_runner_egress_gate.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import m1.run_tasks as RT                    # noqa: E402

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


@case("预检存在（当前批路径没有——这条应当在改前失败）")
def t_egress_probe_exists():
    assert hasattr(RT, "_egress_block_reason"), \
        "批路径没有出口预检：b30 那种 6/100 的假读数还会再发生"


@case("预检必须走浏览器，不许走 urllib（b31 现场：urllib 直连成功，Chrome 仍走死代理）")
def t_probe_uses_the_browser_path():
    src = (REPO / "m1" / "run_tasks.py").read_text(encoding="utf-8")
    body = src[src.index("def _egress_block_reason"):]
    body = body[:body.index("\ndef ")]
    assert "Browser(" in body and "location.href" in body, \
        "预检没有真的开一次浏览器去读落地 URL"
    assert "urllib.request.urlopen" not in body, \
        "预检又去用 urllib 了：它和 Chrome 走的不是同一条路（见函数 docstring 的 b31）"


@case("起点页落在 chrome-error:// 时给出阻断理由")
def t_chrome_error_is_blocked():
    orig, BS = RT.__dict__.get("_FakeBrowser"), None

    class FakeBrowser:
        def __init__(self, url):
            self.url = url

        def evaluate(self, expr):
            return "chrome-error://chromewebdata/"

        def close(self):
            pass

    import jev_ultrafast.browser as JB
    saved = JB.Browser
    JB.Browser = FakeBrowser
    try:
        why = RT._egress_block_reason("https://numpy.org/doc/stable/")
        assert why and "chrome-error" in why, f"chrome-error 被判成可跑：{why!r}"

        class OkBrowser(FakeBrowser):
            def evaluate(self, expr):
                return "https://numpy.org/doc/stable/index.html"
        JB.Browser = OkBrowser
        assert RT._egress_block_reason("https://numpy.org/doc/stable/") is None, \
            "正常页面被拦了（会把能跑的批挡死）"

        class DeadBrowser(FakeBrowser):
            def __init__(self, url):
                raise RuntimeError("no-browser: :9222")
        JB.Browser = DeadBrowser
        assert RT._egress_block_reason("https://numpy.org/doc/stable/") is not None, \
            "浏览器都起不来还放行"
    finally:
        JB.Browser = saved


@case("预检不过时 main 必须在不写报告的前提下退出（返回码非 0）")
def t_main_aborts_before_writing_a_report():
    import tempfile

    d = Path(tempfile.mkdtemp()) / "out.json"
    orig = (RT._egress_block_reason, RT._load_tasks, sys.argv)
    RT._egress_block_reason = lambda url: "出口不通（模拟）"
    RT._load_tasks = lambda p: [{"task_id": "r1", "domain": "https://example.com/",
                                 "goal": "g", "success_assertion": {"type": "any_of",
                                                                    "clauses": []}}]
    sys.argv = ["run_tasks", "--tasks", "x.jsonl", "--log-dir", str(d.parent),
                "--report", str(d)]
    try:
        code = RT.main()
    finally:
        RT._egress_block_reason, RT._load_tasks, sys.argv = orig
    assert code != 0, f"出口不通却返回了 {code}"
    assert not d.exists(), f"出口不通还写出了报告文件（{d}）——那份读数会被当成分数引用"


def main() -> int:
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
    print(f"\n{len(CASES) - failed}/{len(CASES)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
