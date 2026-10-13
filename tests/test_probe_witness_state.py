"""#74：见证探针不许在浏览器缺席时静默重写题集结论。

起因不是假想事故，是 10-12 那次的实况（`m2/real-log.md` 「一次我自己造出来的破坏」一节）：
`m2/probe_task_assertions.py` 没有 argparse，`--help` 被当成"照跑不误"，于是它在**自有 Chrome
还没起回来**的状态下把 82 行候选全跑了一遍，再按 `main()` 的原逻辑**就地重写**
`m2/tasks_l3_verified.jsonl`：`witness_ok` 全被刷成 `false`、两个见证字段清空。
题面（`start_url` / `goal` / `success_assertion`）一处没动，被污染的是"哪些行已被真页面证明过"
这份结论 —— 而它正是 `m2/make_tasks_100.py` 的输入。

那节留下的三条要求，这里逐条钉住：

1. `main()` 开头先验自有 Chrome 在 :9222 上活着（复用 `browser._assert_owned_browser`，
   也就是 runner 一直在用的"端口归谁"判据），不活着就**一个字节都不写**。
2. `witness_ok` 需要 **unknown 态**：`no-browser:` / 连不上 / 整页没读到 ⇒ `None`，
   而不是冒充"评测器说这条断言不成立"。评测器真说不过，才记 `False`。
3. 默认**不落盘**，要 `--write` 才写；写的时候**不许把已经是 `true` 的行降级**。

判据的形状：这四条在改前都该红，而"评测器说不过 ⇒ False"与"断言成立 ⇒ True"两案
改前改后都绿 —— 它们是对照，钉的是"这次改动没有把探针的判据放宽"。

运行：python tests/test_probe_witness_state.py
"""
from __future__ import annotations

import importlib.util
import io
import json
import contextlib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys_path_guard = __import__("sys").path.insert(0, str(REPO))

SPEC = importlib.util.spec_from_file_location(
    "probe_task_assertions", REPO / "m2" / "probe_task_assertions.py")
P = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(P)

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


# ---------------------------------------------------------------- 测试夹具

ROWS = [
    {"cid": "c01", "slug": "s1", "start_url": "https://example.com/",
     "goal": "Open 'Alpha'", "family": "nav",
     "success_assertion": {"type": "all_of", "clauses":
         [{"type": "text_contains", "value": "Alpha", "case_sensitive": False}]},
     "witness_url": "https://example.com/alpha"},
    {"cid": "c02", "slug": "s2", "start_url": "https://example.com/",
     "goal": "Open 'Beta'", "family": "nav",
     "success_assertion": {"type": "all_of", "clauses":
         [{"type": "text_contains", "value": "Beta", "case_sensitive": False}]},
     "witness_url": "https://example.com/beta"},
]


@case("前提自检：夹具的断言形状是真形状，成立页 ⇒ 评测器本人说 PASS")
def t_fixture_assertion_shape_is_real():
    from jev_ultrafast import evaluator as E
    spec = {"task_id": "s1", "success_assertion": ROWS[0]["success_assertion"],
            "category": "positive", "extensions": {}}
    page = {"url": ROWS[0]["witness_url"], "title": "Alpha page", "text": "Alpha here"}
    v = E.evaluate(spec, page, [], "done")
    assert str(getattr(v, "result", "")) == "PASS", (
        f"夹具的断言写错了形状，评测器给的是 {v.result}/{getattr(v, 'failure_mode', None)}")


def _paths(tmp, existing=None):
    """把探针的三个模块级路径指到临时目录；`existing` 是已存在的结论文件内容。"""
    cands = tmp / "cands.jsonl"
    out = tmp / "verified.jsonl"
    cands.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in ROWS) + "\n",
                     encoding="utf-8")
    if existing is not None:
        out.write_text(existing, encoding="utf-8")
    P.CANDS = str(cands)
    P.OUT = str(out)
    P.LOG = str(tmp / "out.txt")
    return out


class FakeBrowser:
    """`raises` 为 None 时给一个能读到的页；否则构造即失败（= 浏览器不在这台端口上）。"""

    raises = None
    pages = {}

    def __init__(self, url):
        if FakeBrowser.raises:
            raise RuntimeError(FakeBrowser.raises)
        self.url = url

    def observe(self, screenshot=True):
        return FakeBrowser.pages.get(self.url)

    def close(self):
        pass


def _run(argv, *, raises=None, pages=None, existing=None, tmp=None):
    FakeBrowser.raises = raises
    FakeBrowser.pages = pages or {}
    out = _paths(tmp, existing)
    P.Browser = FakeBrowser
    P._assert_owned_browser = (lambda: None) if raises is None else (
        lambda: (_ for _ in ()).throw(RuntimeError("no-browser: nothing listens on :9222")))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = P.main(list(argv))
    return rc, out, buf.getvalue()


# ---------------------------------------------------------------- 该红的四条

@case("① 没有 argparse ⇒ `--help` 会被当成「照跑不误」（10-12 那次的入口）")
def t_help_does_not_run_the_probe(tmp_path=None):
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    try:
        # 改前：`--help` 一路走到 main 的循环（当时的实况是整套候选被重跑并重写文件）。
        # 改后：argparse 处理完就 SystemExit，且不碰文件。
        with contextlib.suppress(SystemExit):
            _run(["--help"], tmp=tmp)
        assert not (tmp / "verified.jsonl").exists(), (
            "跑 `--help` 就写出了结论文件——那正是把 82 行刷成 false 的那条入口")
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


@case("② 自有 Chrome 不在 :9222 ⇒ 拒跑并返回非零，一个字节都不写")
def t_refuses_when_owned_browser_absent():
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    try:
        prior = json.dumps({**ROWS[0], "witness_ok": True, "witness_title": "Alpha page"}) + "\n"
        rc, out, txt = _run(["--write"],
                            raises="no-browser: nothing listens on :9222",
                            existing=prior, tmp=tmp)
        assert rc != 0, "浏览器不在却返回 0（= 这一轮被当成正常跑完）"
        assert out.read_text(encoding="utf-8") == prior, (
            "环境不可用却重写了结论文件——82 行刷 false 的那次就是这个形状")
        assert "no-browser" in txt, f"没把拒跑原因打出来：{txt[:200]}"
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


@case("③ 行级失败分类：连不上/整页没读到 ⇒ unknown（None），不许冒充「断言不成立」")
def t_env_failure_is_unknown_not_false():
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    try:
        # 预检过了，但第一行的页根本没读到（observe 回 None）；第二行正常成立。
        pages = {ROWS[1]["witness_url"]: {"url": ROWS[1]["witness_url"],
                                          "title": "Beta page", "text": "Beta here"}}
        rc, out, txt = _run(["--write"], pages=pages, tmp=tmp)
        recs = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines() if l.strip()]
        by = {r["cid"]: r.get("witness_ok") for r in recs}
        assert by["c01"] is None, (
            f"整页没读到却记成 `{by['c01']}`：unknown 必须区别于「评测器说这条不成立」")
        assert by["c02"] is True, f"能读到的那行应当成立，实际 {by['c02']}"
        assert "未证" in txt or "unknown" in txt, f"汇总里没数环境性失败：{txt[-260:]}"
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


@case("④ 默认不落盘：没有 `--write` 时结论文件不许被改")
def t_dry_run_is_the_default():
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    try:
        prior = json.dumps({**ROWS[0], "witness_ok": False}) + "\n"
        pages = {r["witness_url"]: {"url": r["witness_url"], "title": "T", "text": "Alpha Beta"}
                 for r in ROWS}
        rc, out, txt = _run([], pages=pages, existing=prior, tmp=tmp)
        assert rc == 0, f"演练应当成功返回 0，实际 {rc}"
        assert out.read_text(encoding="utf-8") == prior, (
            "不带 `--write` 也写了盘——这条把「探针可以不动，但它不许静默重写」钉成默认安全")
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- 两条对照

@case("对照：评测器真说不过 ⇒ 记 False（这次改动没有把判据放宽成 unknown）")
def t_evaluator_rejection_still_false():
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    try:
        pages = {r["witness_url"]: {"url": r["witness_url"], "title": "Nothing", "text": "zzz"}
                 for r in ROWS}
        rc, out, txt = _run(["--write"], pages=pages, tmp=tmp)
        recs = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert {r.get("witness_ok") for r in recs} == {False}, (
            f"页读到了而断言不满足，必须是 False：{[r.get('witness_ok') for r in recs]}")
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


@case("对照：写盘时不许把已经是 true 的行降级（合并，不是覆盖）")
def t_write_never_downgrades_true():
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    try:
        prior = json.dumps({**ROWS[0], "witness_ok": True, "witness_title": "Alpha page"}) + "\n"
        pages = {r["witness_url"]: {"url": r["witness_url"], "title": "Nothing", "text": "zzz"}
                 for r in ROWS}
        rc, out, txt = _run(["--write"], pages=pages, existing=prior, tmp=tmp)
        recs = {json.loads(l)["cid"]: json.loads(l)
                for l in out.read_text(encoding="utf-8").splitlines() if l.strip()}
        assert recs["c01"].get("witness_ok") is True, (
            "上一轮已证的行被这一轮降级了——题集输入就是这么被静默改写的")
        assert recs["c02"].get("witness_ok") is False, (
            f"新读到的不成立行应当照常记 False：{recs['c02']}")
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    failed = 0
    for name, fn in CASES:
        try:
            fn()
            print("ok    " + name)
        except Exception as e:                                       # noqa: BLE001
            failed += 1
            print("FAIL  " + name)
            print("      " + f"{type(e).__name__}: {str(e)[:300]}")
    print(f"{len(CASES) - failed}/{len(CASES)} passed")
    raise SystemExit(1 if failed else 0)
