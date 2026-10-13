r"""L3-B 的第二类核实：**驱动一次真实交互**再记结果页（零模型）。

`m2/probe_task_candidates.py` 只能核"看得见链/控件"的题；搜索族与表单族的证据不长那样：
- 搜索题的"短语"是**查询词**，起点页上没有它也没关系，要核的是"填进去、提交之后，
  结果页的 URL 形状与页面上有没有那个词"；
- 登录/表单题要核的是"字段存在 → 填值 → 点提交 → 落地页说了什么"。

不能拿 agent 自己的落点当标准答案（那是循环论证，会把分数刷出来）。所以这里用**产品自己的
积木**驱动一遍：字段解析用 `skills._fill_pairs`，搜索框识别用 `skills._searchbox`，
提交用页面上标签命中 search/submit/login/create 的控件；填值/点击之后读真实 URL 与正文。
断言的 pattern 与 text 只从这次读到的东西里抄。

只在没有批次在跑时用（自有 headless Chrome `:9222`）。
"""
import io
import json
import os
import re
import sys
import time
from urllib.parse import urljoin

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\Administrator\openjev-ultrafast")
os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:2080")
os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:2080")
os.environ.setdefault("BU_CDP_URL", "http://127.0.0.1:9222")

from jev_ultrafast import skills as S                         # noqa: E402
from jev_ultrafast.browser import Browser, StalePage         # noqa: E402

CANDS = r"C:\Users\Administrator\openjev-ultrafast\m2\tasks_l3_candidates.jsonl"
OUT = r"C:\Users\Administrator\openjev-ultrafast\m2\tasks_l3_driven.jsonl"
SUBMIT_WORDS = {"search", "submit", "login", "log in", "create order", "go"}


def observe_settled(b, tries=8):
    p = None
    for _ in range(tries):
        try:
            p = b.observe(screenshot=False)
            if str((p or {}).get("title") or "").strip():
                return p
        except StalePage:
            pass
        time.sleep(0.5)
    return p


def acts(page):
    return list(S.indexed_actions(page.get("actions") or []))


def submit_control(page):
    for _i, a in acts(page):
        if a.get("kind") != "click":
            continue
        lab = str(a.get("label") or "").strip().lower()
        if any(w in lab for w in SUBMIT_WORDS):
            return a
    return None


def fill_pairs_for(goal, page):
    """字段→值：优先 goal 里的 `fill X with 'v'` 形状；再兜「搜索框 + 查询词」。"""
    out = []
    for field, value in S._fill_pairs(goal) or []:
        hit = next((a for _i, a in acts(page)
                    if a.get("kind") == "fill" and
                    S._goal_overlap(a, {t for t in S._tokens(field)})), None)
        if hit:
            out.append((hit, value))
    if not out:
        box = next((a for _i, a in acts(page) if a.get("kind") == "fill" and S._searchbox(a)),
                   None)
        q = S._goal_query(goal)
        if box and q:
            out.append((box, q))
    return out


def drive(c):
    rec = {"cid": c["cid"], "goal": c["goal"], "family": c["family"],
           "start_url": c["start_url"]}
    b = Browser(c["start_url"])
    try:
        page = observe_settled(b)
        pairs = fill_pairs_for(c["goal"], page)
        rec["fields"] = [str(a.get("label") or "")[:40] for a, _v in pairs]
        if not pairs:
            rec.update(ok=False, err="no-fillable-field-or-searchbox")
            return rec
        for a, v in pairs:
            b.act(a, page, text=v)
            page = observe_settled(b)
        sub = submit_control(page)
        rec["submit"] = str((sub or {}).get("label") or "")[:40]
        if sub is None:
            # 没有提交控件也允许：填完就跳转的搜索框（form submit）由页面自己处理
            rec["submit"] = "(none: submit-by-enter unsupported here)"
        else:
            b.act(sub, page)
            page = observe_settled(b)
        url = str(page.get("url") or "")
        txt = str(page.get("text") or "")
        rec["land_url"] = url[:120]
        rec["land_title"] = str(page.get("title") or "")[:70]
        rec["land_text_head"] = txt[:220]
        # ok 必须是**有后果**：换页了，或者填进去的值在页面上回显出来。
        # （第一版这里写的是 `bool(url) and bool(txt)`——三行 python 文档搜索没提交成功、
        # 停在起点页也算"通过"，是仪器读快了，不是产品行。）
        values = [v for _a, v in pairs]
        echoed = any(str(v).lower() in txt.lower() for v in values if str(v).strip())
        rec["moved"] = url.rstrip("/") != c["start_url"].rstrip("/")
        rec["echoed"] = echoed
        rec["ok"] = bool(rec["moved"] or echoed)
        if not rec["ok"]:
            rec["err"] = "no-effect: stayed on start page and value not echoed"
        return rec
    except Exception as e:
        rec.update(ok=False, err="%s:%s" % (type(e).__name__, str(e)[:90]))
        return rec
    finally:
        b.close()


def main():
    cands = [json.loads(l) for l in open(CANDS, encoding="utf-8") if l.strip()]
    want = {"search", "form", "login", "select", "multi_hop", "pagination", "read_value"}
    picked = [c for c in cands if c["family"] in want]
    fh = open(OUT, "w", encoding="utf-8")
    ok = 0
    for c in picked:
        rec = drive(c)
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        fh.flush()
        ok += 1 if rec.get("ok") else 0
        print("  %-4s %-10s %s %s -> %s" % (
            c["cid"], c["family"], "✓" if rec.get("ok") else "✗",
            str(rec.get("fields") or rec.get("err"))[:38], str(rec.get("land_url"))[:60]))
        time.sleep(0.8)
    fh.close()
    print("\n驱动核实通过 %d / %d（证据在 %s）" % (ok, len(picked), os.path.basename(OUT)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
