r"""#79 的发布路线：**不动已推送的历史**，改用一份无历史的干净快照对外。

为什么选这条（决策与代价都写在这）：
- 洗历史（`git filter-repo` + force-push main）能真正删掉旧提交里那条第三方邮箱，
  但它重写的是**已经共享出去的引用**：任何已 clone 的人、以及 GitHub 上已缓存的分支都会和仓分叉。
  这类动作要操作者明确点头，我不擅自按。
- 而"公开这个仓库"这件事需要的其实不是洗内部历史，是**对外那份东西里没有泄漏**。
  快照正好给这个：它只有一个文件树，没有提交历史，可核验（包前包后各扫一遍 + sha256 标识这一次出包；
  gzip 里带 mtime，所以 sha256 **不宣称字节级可复现** —— 我第一次想拿两次出包比 sha256 证明这点，
  结果两次写的是同一个文件名、互相覆盖了，那个比较是空的，不能这么写），也
  也可以直接 `git init` 成一个公开仓的**初始提交**。

它做的事：
1. 从 `git ls-files`（= HEAD 的树）取文件，写 `dist/openjev-ultrafast-<sha7>-snapshot.tar.gz`；
2. 打包前用**结构判据**扫一遍（与 `tests/test_no_third_party_pii.py` 同一条：文件名里嵌非合成邮箱），
   有命中就**拒绝出包**；
3. 出包后再把包里的每个成员读出来重扫一遍（防"工作树干净、包里有东西"这种自欺）；
4. 落一份 `dist/<name>.manifest.json`：commit、文件数、字节数、sha256。

用法：python m2/make_release_snapshot.py
    （在公开仓发布时：`git init pub && tar -xzf <快照> -C pub && cd pub && git add -A && git commit`）
"""
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8', errors='replace')
    except Exception:                                          # noqa: BLE001
        pass

# 与 tests/test_no_third_party_pii.py 保持同一条判据；这里抄一份最小实现，
# 是因为测试在 tests/ 下、不属于运行时依赖 —— 两边都改才会不一致，所以第 ⑤ 案在测试里
# 会同时检查"这条判据能响"。
SYNTHETIC_LOCAL = {'redacted', 'test', 'a', 'user', 'info', 'example', 'nobody', 'foo'}
EMAIL_IN_NAME = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"
                           r"\.(?:pdf|docx|xlsx|txt|csv|png|jpg|jpeg|apk|exe|json)\b", re.I)


def offending(text):
    bad = []
    for m in EMAIL_IN_NAME.finditer(text):
        s = m.group(0)
        at = s.find('@')
        left = s[:at]
        local = left.rsplit('_', 1)[-1] if '_' in left else left
        if local in SYNTHETIC_LOCAL:
            continue
        bad.append(s[:40])
    return bad


def tracked():
    out = subprocess.run(['git', 'ls-files'], cwd=ROOT, capture_output=True, text=True)
    return [f.replace('\\', '/') for f in out.stdout.split() if f.strip()]


def scan_worktree(files):
    hits = {}
    for f in files:
        try:
            text = io.open(os.path.join(ROOT, f), encoding='utf-8', errors='ignore').read()
        except OSError:
            continue
        bad = offending(text)
        if bad:
            hits[f] = bad
    return hits


def build(sha):
    files = tracked()
    hits = scan_worktree(files)
    if hits:
        print('拒绝出包：工作树里有非合成的"邮箱即文件名"形状：')
        for f, bad in list(hits.items())[:10]:
            print('   %s  %s' % (f, bad[:2]))
        return 2
    os.makedirs(os.path.join(ROOT, 'dist'), exist_ok=True)
    name = 'openjev-ultrafast-%s-snapshot.tar.gz' % sha[:7]
    path = os.path.join(ROOT, 'dist', name)
    with tarfile.open(path, 'w:gz') as tf:
        for f in files:
            tf.add(os.path.join(ROOT, f), arcname=os.path.join('openjev-ultrafast', f))
    # 包内复检：不能只信工作树
    with tempfile.TemporaryDirectory() as td:
        with tarfile.open(path, 'r:gz') as tf:
            try:                                   # 3.12+ 用受限解包；旧版本退回普通解包
                tf.extractall(td, filter='data')
            except TypeError:
                tf.extractall(td)
        inner = []
        for base, _dirs, fs in os.walk(td):
            for f in fs:
                inner.append(os.path.join(base, f))
        bad = {}
        for p in inner:
            try:
                text = io.open(p, encoding='utf-8', errors='ignore').read()
            except OSError:
                continue
            h = offending(text)
            if h:
                bad[os.path.relpath(p, td)] = h
        if bad:
            print('包内复检失败：', list(bad.items())[:3])
            return 3
    blob = io.open(path, 'rb').read()
    manifest = {
        'artifact': 'dist/' + name,
        'source_commit': sha,
        'files': len(files),
        'bytes': len(blob),
        'sha256': hashlib.sha256(blob).hexdigest(),
        'history_included': False,
        'scanned': '文件名嵌非合成邮箱的结构判据，包前包后各一遍',
    }
    io.open(os.path.join(ROOT, 'dist', name + '.manifest.json'), 'w', encoding='utf-8',
            newline='\n').write(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print('快照：%s（%d 个文件，%.1f MB，无历史）' % (manifest['artifact'], len(files),
                                                   len(blob) / 1e6))
    print('sha256 =', manifest['sha256'])
    print('manifest = dist/%s.manifest.json' % name)
    print('发布时：把这份解到一个新仓做**初始提交**（或挂成 Release 附件）；内部历史保持私有，不 force-push。')
    return 0


def main():
    sha = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT,
                         capture_output=True, text=True).stdout.strip()
    return build(sha)


if __name__ == '__main__':
    raise SystemExit(main())
