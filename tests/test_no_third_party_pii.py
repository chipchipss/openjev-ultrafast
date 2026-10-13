r"""#79：第三方上传内容**不许回到跟踪文件里**，而且这道闸自己不许带着别人的名字。

来历（`m2/real-log.md` 的 #77/#79 两节）：`m2/fixtures/r142_arrival.json` 与 `m2/tmp_download.html`
是 the-internet 公开下载页的快照，那页把任何人上传过的文件名原样列出来（#60 那个存储型 XSS 就在同一页）。
里面有一条**带个人邮箱**的文件名，另有几十个别人简历/报告/截图形状的文件名。10-13 已脱敏与换成合成名，
但"已修好"和"不会再回来"是两件事——这道闸管后者。

为什么不写一份"禁止字符串清单"：那等于把那第三条邮箱原样抄回仓库（我今天已经因为**在 real-log 里抄了例子**
被自己的普查脚本抓出来 4 处，见 real-log 17:1x 那条更正）。
所以闸门只看**结构**：

1. 夹具里的上传链接必须全部是 `third-party-NNN.<扩展名>`（或两处刻意保留的合成名）；
2. 任何跟踪文件里都不许出现"文件名里嵌着一个非合成邮箱"这种形状；
3. 脱敏脚本必须幂等（第二次跑替换 0 处），否则"修好"这件事本身不可复核。

判据的可失败性由 case ④ 当场证：把一条**形状**（`<人名部分>_<邮箱>@<域名>.pdf`，运行时分段拼出来，
理由见那条案里的注释——本文件自己也是被扫描的跟踪文件）喂给同一个谓词，它必须被拒。
这条测试**不往仓里写任何第三方名字**。

运行：python tests/test_no_third_party_pii.py
"""
from __future__ import annotations

import importlib.util
import io
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

SPEC = importlib.util.spec_from_file_location(
    "census_third_party", REPO / "m2" / "census_third_party.py")
CEN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CEN)

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


FIXTURE = REPO / "m2" / "fixtures" / "r142_arrival.json"

#: 合成邮箱的本机部分白名单：只有这些可以出现在文件名形状里（都是我们自己造的）。
SYNTHETIC_LOCAL = {"redacted", "test", "a", "user", "info", "example", "nobody", "foo"}
#: 站点自己生成的、被测试点名的合成文件名（不是别人的上传）
KEPT_SYNTHETIC = re.compile(r"^(download|upload)-[0-9a-f-]{16,}\.(txt|csv|json)$|^(pdf\.jpg|some-file\.txt|default\.txt)$")
UPLOAD_NAME = re.compile(r"^third-party-\d+\.[a-z0-9]+$", re.I)

#: 文件名里嵌着邮箱 = 这次要防的形状。邮箱本体的域名白名单不判——判的是"这是个人标识"这个结构。
EMAIL_IN_NAME = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"
                           r"\.(?:pdf|docx|xlsx|txt|csv|png|jpg|jpeg|apk|exe|json)\b", re.I)


def local_part(name: str) -> str:
    at = name.find('@')
    left = name[:at]
    return left.rsplit('_', 1)[-1] if '_' in left else left


def offending(text: str):
    """返回 text 里"文件名里嵌非合成邮箱"的所有命中。"""
    bad = []
    for m in EMAIL_IN_NAME.finditer(text):
        s = m.group(0)
        if local_part(s) in SYNTHETIC_LOCAL:
            continue
        bad.append(s[:40])
    return bad


@case("① 夹具里的每条上传链接都是合成名（站点/测试点名的那几条除外）")
def t_fixture_upload_list_is_synthetic():
    d = json.load(io.open(FIXTURE, encoding='utf-8'))
    uploads = [str(a.get('href') or '') for a in (d.get('actions') or [])
               if str(a.get('href') or '').startswith('download/')]
    assert uploads, "夹具里没有 download/ 链接，这条就成空判据了"
    stray = [u[len('download/'):] for u in uploads
             if not (UPLOAD_NAME.match(u[len('download/'):]) or KEPT_SYNTHETIC.match(u[len('download/'):]))]
    assert not stray, f"夹具的上传清单里混进了真名：{stray[:4]}"
    print(f"      （{len(uploads)} 条链接，全部合成/保留名）")


@case("② 所有跟踪文件里都没有\"文件名嵌个人邮箱\"这种形状")
def t_no_email_in_filename_anywhere():
    files = subprocess.run(['git', 'ls-files'], capture_output=True, text=True).stdout.split()
    offenders = {}
    for f in files:
        p = REPO / f
        try:
            text = io.open(p, encoding='utf-8', errors='ignore').read()
        except OSError:
            continue
        bad = offending(text)
        if bad:
            offenders[f] = bad
    assert not offenders, (
        "这些跟踪文件里出现了非合成的\"邮箱即文件名\"形状（本测试不打印原文，只报位置与截断串）："
        + json.dumps({k: v[:2] for k, v in list(offenders.items())[:6]}, ensure_ascii=False))


@case("③ 脱敏脚本幂等：第二次跑不许再改任何东西")
def t_scrub_is_idempotent():
    out = subprocess.run([sys.executable, '-X', 'utf8', 'm2/scrub_third_party_fixtures.py'],
                         capture_output=True, text=True, cwd=str(REPO),
                         encoding='utf-8', errors='replace')
    assert out.returncode == 0, out.stdout[-300:] + out.stderr[-300:]
    assert '不改动' in out.stdout or '已经是合成名' in out.stdout, (
        "脚本第二次跑仍在改动 => 它的\"已修好\"不可复核。实际输出：" + out.stdout[-300:])


@case("④ 这条闸会响：真形状喂进去必须被拒（防的是判据空转）")
def t_gate_actually_fires():
    # 演示串**分段拼出来**，不写成字面量：这条闸扫描的是"所有跟踪文件"，而本文件自己就是跟踪文件，
    # 字面量一落盘就会被案② 判成夹带（这不是误伤，是判据真的在响——它抓到的第一个对象是写它的人）。
    bad = "".join(["Foo_Bar_s", "omeone", "@some", "where.edu", ".pdf"])
    hit = offending('见 ' + bad + ' 与 third-party-007.pdf 两条链接')
    assert hit == [bad], f"判据没响：{hit}"
    ok = offending('third-party-007.pdf 和 note_redacted@example.com.pdf 两条')
    assert ok == [], f"合成名被误判（会逼人放宽判据）：{ok}"


@case("⑤ 普查脚本自己不许带着第三方名字：PRIVATE_MARKS 只能是**片段**")
def t_scanner_table_carries_no_full_names():
    marks = CEN.PRIVATE_MARKS
    long_ones = [m for m in marks if len(m) > 24 or '@' in m]
    assert not long_ones, f"扫描器的清单里放了完整名字：{[m[:12] for m in long_ones]}"
    h = CEN.hits()
    allowed = {'m2/census_third_party.py', 'm2/real-log.md', 'CHANGELOG.md', 'README.md', 'MANIFEST.md'}
    leaked = {f: n for f, n in h.items() if f not in allowed}
    assert not leaked, f"数据文件里第三方内容又回来了：{list(leaked)[:5]}"


if __name__ == "__main__":
    failed = 0
    for name, fn in CASES:
        try:
            fn()
            print("ok    " + name)
        except Exception as e:                                       # noqa: BLE001
            failed += 1
            print("FAIL  " + name)
            print("      " + f"{type(e).__name__}: {str(e)[:300]}")
    print(f"{len(CASES) - failed}/{len(CASES)} passed")
    raise SystemExit(1 if failed else 0)
