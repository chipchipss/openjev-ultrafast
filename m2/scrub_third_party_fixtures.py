r"""#79 的执行件（第二版，**精确清单**）：把夹具里第三方上传文件名换成合成名。

第一版是错的，错法值得留着：我按"以扩展名结尾的 token"整页替换，结果打出
**8 657 处 / 250 个名字**——那台页面上每个 JS/CSS/图片资源名都被当成"别人上传的文件"改了，
夹具的形状当场变形。**射程要从工件自己的结构数出来，不能从正则的形状猜。**

这一版的清单来自结构本身：`the-internet` 的下载页把每个上传文件列成
`<a href="download/<文件名>">文件名</a>`，夹具（`snapshot.js` 的产物）里就是
`actions[].href` 以 `download/` 开头的那些条 —— 实测 **43 条**（`m2/tmp_download.html` 同源）。
所以：

- 要换的名字 = 这 43 条 href 解出来的**精确字符串**（含带空格的那种，如 `ecommerce dataset.xlsx`）；
- 换法 = 在整个文件里把这些精确字符串换成 `third-party-NNN.<原扩展名>`，**href 与 label 同步**，
  条数、扩展名、"这是一串别人上传的文件"这个形状全部保留；
- 保留：`download-fae92529-3e0b-4b5a-8b0c.txt`（`tests/test_skills.py` 的 #59 负例点名的就是它，
  它的形状本来就是 `download-<uuid>`，不含任何个人标识）。

历史没有洗（那是操作者的决定，见 #79 与 `m2/real-log.md` 的账）；**这个脚本只让 HEAD 的树干净**。

运行：python m2/scrub_third_party_fixtures.py     （幂等：第二次跑替换 0 处）
"""
import io
import json
import os
import re
import sys
import urllib.parse

# 与其它 m2/ 脚本同一惯例：先把 stdout 定成 UTF-8，否则父进程按本地码解码会炸在中文上
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8', errors='replace')
    except Exception:                                       # noqa: BLE001
        pass

FIXTURE = 'm2/fixtures/r142_arrival.json'
HTML = 'm2/tmp_download.html'
KEEP = {'download-fae92529-3e0b-4b5a-8b0c.txt'}


def is_real_upload(n):
    """幂等守卫：已经换过的 `third-party-NNN.ext` 不是"别人的文件"，不许再进清单。

    没有这一条，第二次跑会把上一轮的合成名当成原名重新映射，**合成名会一路变形**，
    而每一步都"看起来成功"。
    """
    return not re.match(r'^third-party-\d+\.[a-z0-9]+$', n, re.I)


def names_from_fixture():
    d = json.load(io.open(FIXTURE, encoding='utf-8'))
    out = []
    for a in d.get('actions') or []:
        href = str(a.get('href') or '')
        if href.startswith('download/'):
            n = urllib.parse.unquote(href[len('download/'):]).strip()
            if n and n not in KEEP and is_real_upload(n) and n not in out:
                out.append(n)
    return out


def names_from_html():
    # 第一版这里写的是 `href="/download/..."`（带前导斜杠），而这份抓取的形状是
    # `href="download/…"` ⇒ 正则零命中，脚本于是"替换 0 处"却照样报成功——又一把读错的尺子。
    # 现在两条路都认，并且要求显式拿到文件名那一组。
    s = io.open(HTML, encoding='utf-8', errors='ignore').read()
    out = []
    for m in re.finditer(r"""href=['"]?(?:/)?download/([^'">]+)['"]""", s):
        n = urllib.parse.unquote(m.group(1)).strip()
        if n and n not in KEEP and is_real_upload(n) and n not in out:
            out.append(n)
    return out


def build_mapping(all_names):
    """两个文件共用**一张映射表**：同一页的同一批上传，合成名必须两边一致，
    否则夹具与 HTML 互相指不到同一个东西。"""
    mapping = {}
    for n in all_names:
        if n not in mapping:
            ext = n.rsplit('.', 1)[1].lower() if '.' in n else 'bin'
            mapping[n] = 'third-party-%03d.%s' % (len(mapping) + 1, ext)
    return mapping


def scrub(path, mapping):
    s = io.open(path, encoding='utf-8', newline='').read()
    replaced = 0
    # 长的先换，避免短名是长名子串时把长名换坏
    for n in sorted(mapping, key=len, reverse=True):
        c = s.count(n)
        if c:
            s = s.replace(n, mapping[n])
            replaced += c
        # href 里被百分号编码的形态（空格 -> %20）
        enc = urllib.parse.quote(n, safe='')
        if enc != n:
            c2 = s.count(enc)
            if c2:
                s = s.replace(enc, urllib.parse.quote(mapping[n], safe='.'))
                replaced += c2
    io.open(path, 'w', encoding='utf-8', newline='').write(s)
    return replaced


def main():
    fx, hd = names_from_fixture(), names_from_html()
    print('%s 里的上传链接 = %d 条；%s = %d 条' % (FIXTURE, len(fx), HTML, len(hd)))
    union = [n for n in (fx + hd) if n not in []]
    if not union:
        print('已经是合成名（幂等：本次不改动）')
        return 0
    mapping = build_mapping(union)
    r1 = scrub(FIXTURE, mapping)
    r2 = scrub(HTML, mapping)
    print('%s: 替换 %d 处' % (FIXTURE, r1))
    print('%s: 替换 %d 处' % (HTML, r2))
    print('映射表 = %d 个名字（两个文件共用）' % len(mapping))
    d = json.load(io.open(FIXTURE, encoding='utf-8'))
    acts = d.get('actions') or []
    dl = [a for a in acts if str(a.get('href') or '').startswith('download/')]
    print('复核：JSON 可解析 | text 长度 %d | 动作 %d 条 | 其中 download 链接 %d 条'
          % (len(d.get('text') or ''), len(acts), len(dl)))
    for p in (FIXTURE, HTML):
        s = io.open(p, encoding='utf-8', errors='ignore').read()
        left = sum(1 for n in mapping if n in s)
        print('  %s 残留原名 %d 个' % (p, left))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
