r"""#81：题集里同一个 `task_id` 的多份定义，一次可重跑的清点。

起因不是洁癖，是 18:1x 的一次实跑撞墙：`scripts/run_one.ps1 -TaskId r139` **拒绝出题**，
因为 `r139` 同时在 `m2/tasks_real.jsonl` 与 `m2/tasks_real_100.jsonl` 里定义。
入口拒guess是对的（#73 之前 smoke 取题器就死在"按文件顺序撞上的那份"上），
但**重复定义本身还在**，所以每次新工具取题都要重新踩一次：谁先被读到，读数就在测哪一题。

这个脚本把三件事分开数，混在一起就会看错：
- **同 id 同定义**（题集之间复制粘贴的）⇒ 危险低，但仍会让 `-TaskId` 歧义；
- **同 id 不同定义**（goal / url / 断言任一不同）⇒ 就是 r139 这一族，**必须逐个指名**；
- 每个 id 出现在几个文件里 ⇒ 决定"单题入口"能不能用。

退出码：**有"同 id 不同定义"就是 1**。`tests/test_task_id_uniqueness.py` 把它当闸门用，
所以往题集里复制一题而改了断言时，会先跑红灯，而不是等到某次单任务读数悄悄测错题。

运行：python m2/census_task_ids.py
"""
import io
import json
import os
import subprocess
import sys

def normalize_assertion(a):
    """把 `all_of[单一子句]` 折成该子句本身；其余形态原样返回。"""
    if isinstance(a, dict) and a.get('type') == 'all_of' and len(a.get('clauses') or []) == 1:
        return a['clauses'][0]
    return a


def task_files():
    out = subprocess.run(['git', 'ls-files'], capture_output=True, text=True).stdout.split()
    return [f for f in out if os.path.basename(f).startswith('tasks') and f.endswith('.jsonl')]


def definitions(path):
    d = {}
    for line in io.open(path, encoding='utf-8-sig', errors='replace'):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        tid = r.get('task_id')
        if not tid:
            continue
        d[tid] = {'goal': r.get('goal'), 'url': r.get('url') or r.get('start_url'),
                  'assertion': json.dumps(normalize_assertion(r.get('success_assertion')),
                                          sort_keys=True, ensure_ascii=False)}
    return d


def scan(paths):
    """返回 (每个 id 的所有出处, 同定义的, 不同定义的)——测试也走这一条路，不另造判据。"""
    seen = {}
    for f in paths:
        for tid, shape in definitions(f).items():
            seen.setdefault(tid, []).append((f, shape))
    same, differ = {}, {}
    for tid, occ in ((t, v) for t, v in seen.items() if len(v) > 1):
        shapes = {json.dumps(o[1], sort_keys=True, ensure_ascii=False) for o in occ}
        (same if len(shapes) == 1 else differ)[tid] = occ
    return seen, same, differ


def main():
    files = task_files()
    seen, same, differ = scan(files)

    print('题集文件 %d 个、唯一 task_id %d 个、出现在 >1 个文件里的 %d 个'
          % (len(files), len(seen), len(dup_ids)))
    print('  其中**定义完全相同** %d 个；**定义不同** %d 个' % (len(same), len(differ)))
    for tid, occ in sorted(differ.items()):
        print('  [冲突] %-6s %s' % (tid, ', '.join(os.path.basename(o[0]) for o in occ)))
        for f, shape in occ:
            print('           %-34s goal=%s url=%s assertion=%s'
                  % (os.path.basename(f), str(shape['goal'])[:44], str(shape['url'])[:22],
                     str(shape['assertion'])[:52]))
    for tid, occ in sorted(same.items())[:5]:
        print('  同定义 %-6s %s' % (tid, ', '.join(os.path.basename(o[0]) for o in occ)))
    print('“同 id 不同定义” = %d 个' % len(differ))
    return 1 if differ else 0


if __name__ == '__main__':
    sys.exit(main())
