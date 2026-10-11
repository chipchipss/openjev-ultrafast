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


def find_link(page, phrases):
    """起点页动作表里，标签与某个目的地短语互相包含的第一条 click 动作。"""
    for _idx, a in S._indexed(page.get("actions") or []):
        if a.get("kind") != "click":
            continue
        lab = str(a.get("label") or "").strip()
        if not lab:
            continue
        for ph in phrases:
            t1 = S._phrase_token_set(lab)
            t2 = S._phrase_token_set(ph)
            if t1 and t2 and (t1 <= t2 or t2 <= t1):
                return a, ph
    return None, None


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
            phrases = S._destination_phrases(c["goal"],
                                             {m.group(1) for m in re.finditer(
                                                 r"['\"]([^'\"]{2,60})['\"]", c["goal"])})
            link, matched = find_link(page, phrases)
            rec["phrases"] = phrases
            if link is None:
                rec.update(ok=False, err="no-link-on-start-page")
                print("  %-4s 起点页上没有那条链（短语=%s）" % (c["cid"], phrases))
            else:
                rec["label"] = str(link.get("label") or "")[:60]
                rec["matched"] = matched
                href = str(link.get("href") or link.get("url") or "")
                dest = urljoin(c["start_url"], href) if href else ""
                rec["href"] = href[:90]
                if dest.startswith("http") and urlsplit(dest).netloc:
                    b2 = Browser(dest)
                    try:
                        p2 = observe_settled(b2)
                        rec["land_url"] = str(p2.get("url") or dest)[:110]
                        rec["land_title"] = str(p2.get("title") or "")[:70]
                        txt = str(p2.get("text") or "")
                        rec["text_head"] = txt[:160]
                        rec["n_actions"] = len(p2.get("actions") or [])
                        rec["ok"] = True
                        print("  %-4s ✓ %-28s -> %s" % (c["cid"], rec["label"][:28],
                                                        rec["land_url"][:66]))
                    finally:
                        b2.close()
                else:
                    rec.update(ok=False, err="link-not-a-url")
                    print("  %-4s 链不是可跳的 URL（href=%r）" % (c["cid"], href[:40]))
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
