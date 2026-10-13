import glob
import json
import os
import sys

rep = [p for p in sorted(glob.glob('reports/ci-1013-*.json'))
       if len(json.load(open(p, encoding='utf-8')).get('results') or []) == 100]
if not rep:
    print("no b40 report yet")
    sys.exit(3)
rep = rep[-1]
d = json.load(open(rep, encoding='utf-8'))
res = {r['task_id']: r for r in d['results']}
b39 = json.load(open('reports/real-1013-b39-100-1013-145827.json', encoding='utf-8'))
r39 = {x['task_id']: x for x in b39['results']}


def verdict(m, t):
    r = m.get(t, {}).get('result')
    return r if isinstance(r, str) else (r or {}).get('result')


def inner(m, t):
    r = m.get(t, {}).get('result')
    return r if isinstance(r, dict) else {}


def deep(m, key):
    return sum((inner(m, t).get('meta') or {}).get(key, 0) or 0 for t in m)


s = d['summary']
print("report:", rep)
print("pass=%s fail=%s unknown=%s error=%s quadrants=%s"
      % (s['pass'], s['fail'], s['unknown'], s['error'], s['quadrants']))
print("false_positive rows:", [t for t in res if inner(res, t).get('quadrant') == 'false_positive'])
print("判据①收益不退 r154/156/157/158:", {t: verdict(res, t) for t in ('r154', 'r156', 'r157', 'r158')})

logdir = 'logs/' + os.path.basename(rep).replace('.json', '')
paid = []
for f in glob.glob(logdir + '/*.jsonl'):
    for line in open(f, encoding='utf-8', errors='ignore'):
        if '"arrival_relook_ms"' in line:
            e = json.loads(line)
            paid.append((e.get('task_id'), e['arrival_relook_ms']))
print("判据②付费行: n=%d sum=%d ms" % (len(paid), sum(p[1] for p in paid)))
for t, ms in sorted(paid):
    print("   %-6s %6d ms  b39=%s b40=%s" % (t, ms, verdict(r39, t), verdict(res, t)))
print("   b39 里靠 link_followed_arrival 付费的 r126/r172/r177 这次付费了吗:",
      [p for p in paid if p[0] in ('r126', 'r172', 'r177')] or "没有（收窄生效）")

gain = [t for t in res if verdict(r39, t) != 'PASS' and verdict(res, t) == 'PASS']
loss = [t for t in r39 if verdict(r39, t) == 'PASS' and verdict(res, t) != 'PASS']
print("相对 b39  GAIN:", gain, " LOST:", [(t, verdict(res, t)) for t in loss])
print("判据③步数 b39=%d b40=%d ; 模型调用 b39=%d b40=%d"
      % (deep(r39, 'steps'), deep(res, 'steps'),
         deep(r39, 'model_calls'), deep(res, 'model_calls')))

vals = set()
for f in glob.glob(logdir + '/*.jsonl'):
    for line in open(f, encoding='utf-8', errors='ignore'):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if 'text_helper' in e:
            vals.add(json.dumps(e['text_helper'], ensure_ascii=False))
print("零云端口径 text_helper 取值集合:", sorted(vals)[:6])
