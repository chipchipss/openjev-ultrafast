r"""#75：断言吃的那份正文必须进产物——不然一次翻动只能归因到族，证不到帧。

b37 的 r195 从 FAIL 翻到 PASS，动作序列、落点 URL、标题**逐拍相同**，唯一差别是
`text_contains "python"` 一次 ok=False 一次 ok=True。我想说清"那一次到底读到了什么"，
却发现 trace 里根本没有：`task_result.final_page` 只有 url + title，step 事件的 `text`
是 Text Helper 要**输入**的串（#68 那次误读的就是同一个字段），`page_fp_before` 是不可逆哈希。
⇒ 任何 `text_contains` 的输入事后不可复核。

和 #67 同一类：缺的不是日志行数，是**能区分两种解释的那个字段**。

补的是摘要不是原文：`text_len` 能指出"这是半帧"（docs 族实测 654 → 1454），
`text_sha16` 能让两次读数对得上"是不是同一份页"；整段正文不进 trace（体积，
以及第三方页面内容没必要跟着报告一起入库）。

运行：python tests/test_graded_input_logged.py
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from jev_ultrafast.logger import Logger                        # noqa: E402

CASES = []

SHORT = "Python documentation\n\nSearch Docs\n\nnav shell text " * 12
GROWN = SHORT + "\nResults for enumerate — showing 1-10 of 810\n" + "enumerate entry " * 60


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


def page(text, url="https://docs.python.org/3/search.html?q=enumerate",
         title="Search - Python 3.15.0 documentation"):
    return {"url": url, "title": title, "text": text, "elements": [], "fingerprint": "f"}


def finalize_into(tmp, pg):
    with Logger("t-graded", Path(tmp) / "logs", flush_every=1) as lg:
        ev = lg.finalize({"result": "FAIL", "quadrant": "correct_abandon"}, final_page=pg)
        path = lg.log_path
    lines = [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]
    return ev, [e for e in lines if e.get("event") == "task_result"][-1]


@case("finalize 必须记下断言吃的那份正文：长度 + 16 位摘要")
def t_graded_snapshot_is_recorded():
    with tempfile.TemporaryDirectory() as tmp:
        _ev, disk = finalize_into(tmp, page(SHORT))
        fp = disk.get("final_page") or {}
        assert fp.get("text_len") == len(SHORT), \
            f"final_page 没有可复核的正文长度：{sorted(fp)}"
        want = hashlib.sha1(SHORT.encode("utf-8", "replace")).hexdigest()[:16]
        assert fp.get("text_sha16") == want, \
            f"摘要对不上（{fp.get('text_sha16')} != {want}）——事后无法确认是哪一份页被评了"


@case("记摘要不记原文：整段正文不许进 trace")
def t_raw_text_is_not_logged():
    with tempfile.TemporaryDirectory() as tmp:
        _ev, disk = finalize_into(tmp, page(SHORT))
        blob = json.dumps(disk, ensure_ascii=False)
        assert "nav shell text" not in blob, "整段页面正文被写进报告了（体积 + 第三方内容）"


@case("两次不同帧必须可区分：654 那种半帧 vs 渲染完的那份，长度与摘要都得不同")
def t_two_frames_are_distinguishable():
    with tempfile.TemporaryDirectory() as tmp:
        _e1, one = finalize_into(tmp, page(SHORT))
        _e2, two = finalize_into(tmp, page(GROWN))
        a, b = one["final_page"], two["final_page"]
        assert a.get("text_len") != b.get("text_len"), \
            "早读与晚读在产物里长得一模一样，r195 那种翻动就还是证不到底"
        assert a.get("text_sha16") != b.get("text_sha16")
        assert a["url"] == b["url"], "夹具前提：同一条 URL，只有正文帧不同"


@case("#65 的代价必须进产物：task_result.arrival_relook_ms；没付就不写这个键")
def t_paid_ms_reaches_the_artifact():
    with tempfile.TemporaryDirectory() as tmp:
        with Logger("t-paid", Path(tmp) / "logs", flush_every=1) as lg:
            lg.finalize({"result": "PASS"}, final_page=page(SHORT), state_paid_ms=3438)
            path = lg.log_path
        ev = [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]
        tr = [e for e in ev if e.get("event") == "task_result"][-1]
        assert tr.get("arrival_relook_ms") == 3438, f"付费没进产物：{sorted(tr)}"

        with Logger("t-unpaid", Path(tmp) / "logs2", flush_every=1) as lg2:
            lg2.finalize({"result": "PASS"}, final_page=page(SHORT))
            path2 = lg2.log_path
        ev2 = [json.loads(l) for l in Path(path2).read_text(encoding="utf-8").splitlines() if l.strip()]
        tr2 = [e for e in ev2 if e.get("event") == "task_result"][-1]
        assert "arrival_relook_ms" not in tr2, "没付钱的行也被写了计时，批里就数不出真实付费面"


@case("同一笔钱必须**穿过评测器的 meta 白名单**进到 reports/*.json（#67 的老形状：白名单丢字段）")
def t_paid_ms_survives_evaluator_meta():
    from jev_ultrafast.evaluator import evaluate
    spec = {"task_id": "r154", "category": "positive",
            "success_assertion": {"type": "all_of", "clauses": [
                {"type": "text_contains", "value": "enumerate", "case_sensitive": False}]},
            "extensions": {}}
    pg = page("enumerate — Python documentation " + "x" * 40)
    meta = {"steps": 2, "model_calls": 3, "api_calls": 0, "elapsed_ms": 7803,
            "arrival_relook_ms": 1875}
    res = evaluate(spec, pg, [{"kind": "click", "url": pg["url"]}], "done", meta=meta)
    d = res.to_dict() if hasattr(res, "to_dict") else res
    got = (d.get("meta") or {}) if isinstance(d, dict) else {}
    assert got.get("arrival_relook_ms") == 1875, (
        f"runner 写了钱，评测器的 `_meta` 白名单却只放四件（steps/model_calls/api_calls/elapsed_ms），"
        f"于是 reports/*.json 里数不到它：meta={got}")


@case("同一份正文摘要必须活到 reports/*.json 的 meta（logs/ 不入库，报告才是权威工件）")
def t_digest_reaches_the_report_meta():
    # 2026-10-14 量的现状：`task_result` 事件里有 final_page，但 499 行 reports 的 meta
    # 只有 steps/model_calls/api_calls/elapsed_ms ⇒ 一次 text_contains 翻动在**可分享的工件**里仍不可复核。
    # 这与 #65/#67/#83 是同一族：白名单只放旧的四件，新仪器字段静默被丢。
    from jev_ultrafast.evaluator import evaluate
    from jev_ultrafast.logger import page_digest
    spec = {"task_id": "r195", "category": "positive",
            "success_assertion": {"type": "all_of", "clauses": [
                {"type": "text_contains", "value": "810", "case_sensitive": False}]},
            "extensions": {}}
    pg = page(GROWN)
    meta = {"steps": 3, "model_calls": 4, "api_calls": 0, "elapsed_ms": 900,
            "final_page": page_digest(pg)}
    res = evaluate(spec, pg, [{"kind": "click", "url": pg["url"]}], "done", meta=meta)
    got = res.meta or {}
    fp = got.get("final_page") or {}
    assert fp.get("text_len") == len(GROWN), f"报告里没有正文长度，翻动还是证不到帧：meta={sorted(got)}"
    assert fp.get("text_sha16") == hashlib.sha1(GROWN.encode("utf-8", "replace")).hexdigest()[:16]
    blob = json.dumps(fp, ensure_ascii=False)
    assert "nav shell text" not in blob and "enumerate entry" not in blob, \
        "白名单把整段正文放进了报告（只许过 url/title/长度/摘要四件）"


@case("摘要只有一个来源：logger 与 runner 不许各抄一份算法")
def t_single_source_for_the_digest():
    from jev_ultrafast.logger import page_digest
    pg = page(SHORT)
    d = page_digest(pg)
    assert set(d) == {"url", "title", "text_len", "text_sha16"}, d
    assert d["text_len"] == len(SHORT)
    with tempfile.TemporaryDirectory() as tmp:
        _ev, disk = finalize_into(tmp, pg)
        assert disk["final_page"] == d, \
            "task_result 里的摘要与 page_digest() 算出来的不是一份 ⇒ 两份算法迟早漂"
    assert page_digest(None) == {}, "没有页时不许造一个假摘要"


@case("错误页要把**错误码**带进摘要：批里那 83 字符的 chrome-error 页今天只有长度，没有码")
def t_error_page_carries_the_code_not_the_body():
    # 现场：10-14 的 sqlite 探针抓到失败帧正文是
    #   此网站无法提供安全连接 / www.sqlite.org 发送的响应无效。 / ERR_SSL_PROTOCOL_ERROR / 重新加载
    # 批工件里它一直是 `text_len=83` —— 归因写成了"环境"，但**哪种环境**没有字段可读。
    from jev_ultrafast.logger import page_digest
    err_txt = ("此网站无法提供安全连接\nwww.sqlite.org 发送的响应无效。\n"
               "尝试运行 Windows 网络诊断。\nERR_SSL_PROTOCOL_ERROR\n重新加载")
    pg = {"url": "chrome-error://chromewebdata/", "title": "www.sqlite.org",
          "text": err_txt, "elements": [], "fingerprint": "e"}
    d = page_digest(pg)
    assert d.get("err") == "ERR_SSL_PROTOCOL_ERROR", (
        f"错误码没进摘要，egress 行还是只能写成'环境'而不能写成哪一种环境：{d}")
    blob = json.dumps(d, ensure_ascii=False)
    assert "无法提供安全连接" not in blob and "响应无效" not in blob, \
        "错误页正文整段进了产物 —— 只许提码名（Chrome 自己的字符串），本地化文案不进仓"


@case("码名只在真有码时出现，且必须穿过 _meta 白名单到 reports/*.json")
def t_err_key_is_sparse_and_whitelisted():
    from jev_ultrafast.evaluator import evaluate
    from jev_ultrafast.logger import page_digest
    healthy = page_digest(page(SHORT))
    assert "err" not in healthy, f"健康页也被写了 err 键，批里就数不出真实错误面：{healthy}"

    err_pg = {"url": "chrome-error://chromewebdata/", "title": "example.invalid",
              "text": "This site can’t be reached\nERR_NAME_NOT_RESOLVED", "fingerprint": "e"}
    spec = {"task_id": "x001", "category": "negative",
            "success_assertion": {"type": "all_of", "clauses": [
                {"type": "url_matches", "pattern": "example\\.invalid"}]},
            "extensions": {}}
    meta = {"steps": 0, "model_calls": 1, "api_calls": 0, "elapsed_ms": 1200,
            "final_page": page_digest(err_pg)}
    res = evaluate(spec, err_pg, [], "blocked", meta=meta)
    fp = (res.meta or {}).get("final_page") or {}
    assert fp.get("err") == "ERR_NAME_NOT_RESOLVED", (
        f"runner 写了码，报告白名单只放四件 ⇒ 又是 #67/#65/#83 那一族：meta.final_page={fp}")


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
