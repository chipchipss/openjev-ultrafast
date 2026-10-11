r"""L3-B 的核实器：把候选任务量成**可断言**的任务（curl 只筛，CDP 才算数）。

每条候选要回答三个问题，全部来自现场而不是我的想象：
1. 起点页打得开吗（自有 Chrome + :2080 代理，标题/正文非空）；
2. goal 引号里点名的短语，在起点页上**是不是真有一条链接**（label + href）；
   目的地短语用产品同一把尺子取（`skills._destination_phrases`），不另造规则；
3. 顺着那条链接落地后，**真实 URL 与标题**长什么样 —— 断言的 `url_matches` 模式就从这个
   URL 抄，`text_contains` 从落地页正文里挑一个稳定片段。

没有第 3 步的读数，候选就不许进任务集（`m2/tasks_l3_candidates.jsonl` 里 `verified=false`
就是没核实）。这一条是项目纪律⑤（每个数字能对到工件）在扩题上的具体形态。

**只在没有批次在跑时用**（驱动自有 headless Chrome `:9222`；零模型，不调 :8090）。
"""
import io
import json
import os
import re
import sys
import time
from urllib.parse import urljoin, urlsplit

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\Administrator\openjev-ultrafast")
os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:2080")
os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:2080")
os.environ.setdefault("BU_CDP_URL", "http://127.0.0.1:9222")

from jev_ultrafast import skills as S                          # noqa: E402
from jev_ultrafast.browser import Browser, StalePage           # noqa: E402

CANDS = r"C:\Users\Administrator\openjev-ultrafast\m2\tasks_l3_candidates.jsonl"
OUT = r"C:\Users\Administrator\openjev-ultrafast\m2\tasks_l3_evidence.jsonl"


def observe_settled(b, tries=8):
    for _ in range(tries):
        try:
            p = b.observe(screenshot=False)
            if str((p or {}).get("title") or "").strip():
                return p
        except StalePage:
            pass
        time.sleep(0.5)
    return p


def matched_controls(page, phrases):
    """起点页动作表里与任一短语词面相交的**控件**（click/fill/select 都要）。

    为什么不能只找"终点链接"：第一批核实 29 条里只有 7 条是一跳到达，其余是 select /
    checkbox / form / 翻页族——它们**没有终点链接**，可核实的证据是"控件在不在起点页上、
    页面正文里有什么"。另外 `Key Presses`/`GET` 报了"没有那条链"，其实是链接存在但在
    **视口外**（`snapshot.js` 只收录视口内动作，#40/#59 那张老账），所以还得看正文短语。
    """
    hits = []
    for _idx, a in S._indexed(page.get("actions") or []):
        lab = str(a.get("label") or "").strip()
        if not lab:
            continue
        t1 = S._phrase_token_set(lab)
        if not t1:
            continue
        for ph in phrases:
            t2 = S._phrase_token_set(ph)
            if t2 and (t1 <= t2 or t2 <= t1):
                hits.append({"kind": a.get("kind"), "label": lab[:60],
                             "href": str(a.get("href") or "")[:80], "phrase": ph})
                break
    return hits


def main():
    cands = [json.loads(l) for l in open(CANDS, encoding="utf-8") if l.strip()]
    done = []
    fh = open(OUT, "a", encoding="utf-8")
    for c in cands:
        rec = {"cid": c["cid"], "start_url": c["start_url"], "goal": c["goal"],
               "family": c["family"]}
        try:
            b = Browser(c["start_url"])
        except Exception as e:
            rec.update(ok=False, err="init:%s" % type(e).__name__)
            print("  %-4s 起点打不开 %s" % (c["cid"], rec["err"]))
            done.append(rec)
            continue
        try:
            page = observe_settled(b)
            rec["start_title"] = str(page.get("title") or "")[:70]
            quoted = {m.group(1) for m in re.finditer(r"['\"]([^'\"]{2,60})['\"]", c["goal"])}
            rec["n_actions"] = len(page.get("actions") or [])
            txt = str(page.get("text") or "")
            rec["text_head"] = txt[:200]
            rec["phrases"] = sorted(quoted)
            rec["dest_phrases"] = S._destination_phrases(c["goal"], quoted)
            hay = (txt + " " + rec["start_title"]).lower()
            rec["phrase_in_text"] = {p: hay.count(p.lower()) for p in sorted(quoted)}
            hits = matched_controls(page, sorted(quoted))
            rec["controls"] = hits[:8]
            link = next((h for h in hits if h["kind"] == "click" and h["href"]
                         and h["phrase"] in rec["dest_phrases"]), None)
            if link:
                dest = urljoin(c["start_url"], link["href"])
                if dest.startswith("http") and urlsplit(dest).netloc:
                    rec["label"], rec["href"] = link["label"], link["href"][:90]
                    b2 = Browser(dest)
                    try:
                        p2 = observe_settled(b2)
                        rec["land_url"] = str(p2.get("url") or dest)[:110]
                        rec["land_title"] = str(p2.get("title") or "")[:70]
                        rec["land_text_head"] = str(p2.get("text") or "")[:200]
                        rec["evidence"] = "one-hop-arrival"
                        rec["ok"] = True
                        print("  %-4s ✓ 一跳到达 %-24s -> %s" % (
                            c["cid"], rec["label"][:24], rec["land_url"][:58]))
                    finally:
                        b2.close()
                else:
                    rec.update(ok=False, err="link-not-a-url", href=link["href"][:60])
                    print("  %-4s 链不是可跳的 URL（href=%r）" % (c["cid"], link["href"][:40]))
            else:
                # 没有终点链接 ≠ 不能用：多跳族（select/checkbox/form/翻页）的断言打在
                # **起点页 + 控件 + 正文**上。视口外的链接这里靠正文短语认出来。
                in_text = sum(1 for v in rec["phrase_in_text"].values() if v > 0)
                rec["evidence"] = ("control-on-start-page" if hits else
                                   ("phrase-in-text(below-fold?)" if in_text else "none"))
                rec["ok"] = bool(hits) or in_text > 0
                print("  %-4s %s 控件=%d 短语见文=%d 动作数=%d  [%s]" % (
                    c["cid"], "✓" if rec["ok"] else "✗", len(hits), in_text,
                    rec["n_actions"], rec["evidence"]))
        except Exception as e:
            rec.update(ok=False, err="%s:%s" % (type(e).__name__, str(e)[:70]))
            print("  %-4s 崩 %s" % (c["cid"], rec["err"]))
        finally:
            b.close()
        done.append(rec)
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        fh.flush()
        time.sleep(0.8)
    fh.close()
    ok = sum(1 for r in done if r.get("ok"))
    print("\n核实通过 %d / %d（证据在 %s）" % (ok, len(done), os.path.basename(OUT)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
