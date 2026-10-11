r"""L3-C 的瓶颈定位（第二版；第一版的 B 组是坏仪器，读数作废）：并发不涨，是 llama-server 还是 shim？

第一版的错：B 组我用手搓的 `/v1/systemone` 请求体，26 发全是 HTTPError，"750 次/秒"是**错误
吞吐**（今早已为同类错记过档：仪器没验就先读结论）。A 组也偏——一句话 prompt 量到 29.6 次/秒，
那不是决策载荷的尺寸。

这一版两路都用真东西：
  A) llama-server :8081 `/completion`，prompt = `m4a/_last_typesafe_body.json` 截到 16 KB
     （`model.choose_typesafe` 实际发出去的那一份，含 action space 与 recent_actions）；
  B) 产品原路 `model.choose_typesafe` 打 :8090（一次决策 = shim 打后端若干次）。
并发 1/2/4，比"加速比"：A 涨 B 不涨 ⇒ 瓶颈在 shim 的 HTTP 层（换多线程服务器就能吃满 4 槽）；
A 也不涨 ⇒ 后端到此为止，300 题那一档不做并行，L3 以 100 题 ≤30 分钟收口。
不碰浏览器、不碰代理。
"""
import concurrent.futures as cf
import json
import os
import statistics
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\Administrator\openjev-ultrafast")
os.environ.setdefault("TYPESAFE_BASE_URL", "http://127.0.0.1:8090")
os.environ.setdefault("TYPESAFE_API_KEY", "local")

REPO = r"C:\Users\Administrator\openjev-ultrafast"
REAL = json.dumps(json.load(open(REPO + r"\m4a\_last_typesafe_body.json",
                                 encoding="utf-8")), ensure_ascii=False)[:16000]
PAGE = json.load(open(REPO + r"\m2\fixtures\r126_arrival.json", encoding="utf-8"))
GOAL = "From the SQLite home page, open the 'SQL Syntax' page."


def llama_hit(_i=None):
    body = json.dumps({"prompt": REAL, "n_predict": 4, "temperature": 0.0,
                       "cache_prompt": False}).encode()
    req = urllib.request.Request("http://127.0.0.1:8081/completion", data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=180) as r:
        r.read()
    return time.monotonic() - t0


def wire_hit(_i=None):
    from jev_ultrafast import model as M
    t0 = time.monotonic()
    try:
        d = M.choose_typesafe(PAGE, GOAL, [])
        return time.monotonic() - t0, bool(isinstance(d, dict) and d.get("choice"))
    except Exception as e:
        return time.monotonic() - t0, "ERR:%s" % type(e).__name__


def sweep(fn, reps, label):
    print("  并发  次数   总耗时   中位延迟   吞吐(次/秒)  失败")
    out = []
    for w in sorted(reps):
        t0 = time.monotonic()
        with cf.ThreadPoolExecutor(max_workers=w) as ex:
            lat = list(ex.map(fn, range(reps[w])))
        span = max(time.monotonic() - t0, 1e-6)
        bad = sum(1 for x in lat if isinstance(x, tuple) and x[1] is not True)
        secs = [x[0] if isinstance(x, tuple) else x for x in lat]
        out.append((w, reps[w], span, statistics.median(secs), reps[w] / span, bad))
        print("  %4d  %4d   %6.2fs   %6.2fs   %8.2f  %d" % out[-1])
    print("  %s 加速比 %.2fx（并发 1 → %d）" % (label, out[-1][4] / out[0][4], out[-1][0]))
    return out


def main():
    warm = wire_hit()
    print("预热一发原路决策：%.2fs ok=%s" % (warm[0], warm[1]))
    if warm[1] is not True:
        raise SystemExit("原路没打通（%s），两组的对照都不作数" % warm[1])
    print("== B) 产品原路 :8090（一次决策，含 shim 的多次后端调用）==")
    b = sweep(wire_hit, {1: 4, 2: 6, 4: 8}, "B")
    print("\n== A) llama-server :8081，真实尺寸 prompt（16 KB，n_predict=4）==")
    a = sweep(llama_hit, {1: 6, 2: 8, 4: 12}, "A")
    print("\n判读：A 涨而 B 不涨 ⇒ 瓶颈在 shim 的 HTTP 层（多线程服务器可吃满 4 槽）；")
    print("      A 也不涨 ⇒ 后端到此为止，300 题不做并行，L3 以 100 题 ≤30 分钟收口。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
