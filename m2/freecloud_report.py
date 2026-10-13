r"""#80 的读数器：一份 freecloud 报告 + 它的 trace ⇒ 分数、延迟、非法决策、安全线。

为什么不现场拍脑袋：目标那句话("免费小模型即可达到近似水平")要的是**同一把题集上的对照数**，
而本地底座的锚是 `reports/m1-baseline-1013-1746.json` 那一类：19/19、单轮 5.3 min、
单决策中位 0.64 s。两边的口径必须一致，所以这里只读**产物**（report + 每行 trace 的 step 事件），
不重复实现任何评测。

延迟的取法：step 事件里的 `latency_ms` 是 agent 记的**那一次模型调用的墙钟**（含出口代理），
`decisions` 里被拒收（非法 operation / 越界 target）的记录带 `rejected` 字段 ——
这两个数就是"云端当决策层"到底贵在哪、以及小模型最常崩在哪一格的直接读数。

运行：python m2/freecloud_report.py reports/freecloud-19-*.json
"""
import glob
import io
import json
import os
import statistics
import sys


def load(p):
    return json.load(io.open(p, encoding='utf-8'))


def main():
    pats = sys.argv[1:] or sorted(glob.glob('reports/freecloud-19-*.json'))
    for path in pats:
        d = load(path)
        s = d.get('summary') or {}
        rows = d.get('results') or []
        logdir = 'logs/' + os.path.basename(path).replace('.json', '')
        lat, rejected, retries, helper = [], [], 0, []
        # 延迟与拒收都在 **decision 事件**里（`event == "decision"`），不在 step 里：
        # step 的 latency_ms 是"那一步的模型延迟"，而地板/技能决策不发模型调用，
        # 它记的是 0 —— b41 实测本地底座"中位 0 ms"就是这个原因（332 条里技能决策占多数）。
        # 所以只统计**真的打了模型**的那些：skill 为空且 latency_ms>0，
        # 以及带 `rejected` 字段的（被拒收=非法 operation / 越界 target，缺陷#5 的入账口）。
        if os.path.isdir(logdir):
            for f in glob.glob(os.path.join(logdir, '*.jsonl')):
                for line in io.open(f, encoding='utf-8', errors='ignore'):
                    if '"decision"' not in line and '"task_result"' not in line:
                        continue
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    ev = e.get('event')
                    if ev == 'decision':
                        if e.get('rejected'):
                            rejected.append((os.path.basename(f)[:-6], str(e['rejected'])[:70]))
                        elif (not e.get('skill')) and isinstance(e.get('latency_ms'), (int, float)) and e['latency_ms'] > 0:
                            lat.append(e['latency_ms'])
                        th = e.get('text_helper')
                        if th:
                            helper.append(th)
                    elif ev == 'step':
                        th = e.get('text_helper')
                        if th:
                            helper.append(th)
        print('=== %s' % os.path.basename(path))
        print('  pass=%s fail=%s unknown=%s error=%s  fp=%s'
              % (s.get('pass'), s.get('fail'), s.get('unknown'), s.get('error'),
                 s.get('quadrants', {}).get('false_positive', 0)))
        steps = [(r.get('result') or {}).get('meta', {}).get('steps') for r in rows
                 if isinstance(r.get('result'), dict)]
        if steps:
            print('  每行步数: 合计 %d，中位 %s，最多 %s' % (sum(x or 0 for x in steps),
                                                       statistics.median(steps), max(steps)))
        if lat:
            q = statistics.quantiles(lat, n=100) if len(lat) > 20 else None
            print('  决策延迟 n=%d  中位 %.0f ms  p90 %.0f ms  最大 %.0f ms%s'
                  % (len(lat), statistics.median(lat),
                     (q[89] if q else max(lat)), max(lat),
                     '' if q else '  (样本 <20，p90 用最大值代替)'))
        else:
            print('  决策延迟: trace 里没有 latency_ms 字段（仪器缺件，不猜）')
        print('  非法决策(被拒收) %d 次' % len(rejected))
        for t, why in rejected[:6]:
            print('     %s  %s' % (t, why))
        if helper:
            print('  text_helper 取值集合: %s   <- 必须是本地那一个，否则变量没控住'
                  % sorted(set(helper))[:4])
        errs = [(r['task_id'], str(r.get('error'))[:90]) for r in rows if r.get('error')]
        for t, e in errs:
            print('  ERROR %s: %s' % (t, e))
        print()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
