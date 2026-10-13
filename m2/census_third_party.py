r"""#79 的普查：第三方上传文件名在**跟踪文件**里出现在哪些地方、各多少次。

背景：`m2/fixtures/r142_arrival.json` 与 `m2/tmp_download.html` 是 the-internet 公开下载页的快照，
那页会把**任何人上传的文件名**原样列出来（#60 的存储型 XSS 就在同一页）。10-13 已经把里面那条
个人邮箱脱敏，但同页还有几十个第三方文件名（`resume.pdf`、`JD-Coforge.docx`、Marathi letterhead、
`WhatsApp Image ….jpeg`）。「洗历史 / 换夹具 / 就地保留并说明」是发布形态的决定，先把**射程**数出来。

只读：不改任何文件。判据是「文件名是不是只有那台公开测试站上才有的第三方上传物」，
不是「看起来像英文人名就算」—— 所以这里只报命中与上下文，结论要人看图。

运行：python m2/census_third_party.py
"""
import collections
import io
import re
import subprocess

# 这些串只在"别人上传的私有文件"里出现过（从 r142 夹具的上传清单里抄的，不猜）：
PRIVATE_MARKS = ("resume", "JD-Coforge", "WhatsApp", "Screenshot", "SkodeQA", "Sharmatania",
                 "Obsqura", "mythili", "IOTUK", "girija", "Coforge", "BLACK BOOK",
                 "ecommerce dataset", "final_seminar_report", "Profile Marketing")
NAME_RE = re.compile(r"[^\s\"',<>|]{1,80}?\.(?:pdf|docx|xlsx|xls|txt|csv|png|jpg|jpeg|jfif|exe|json|pt)",
                     re.IGNORECASE)
SKIP_PATHS = ("m2/real-log.md", "CHANGELOG.md", "README.md", "MANIFEST.md", "m2/fixtures/",
              "docs/")


def hits(files=None):
    """返回 {文件: 命中次数}。测试与命令行都走这一个函数，不另造一份判据。"""
    if files is None:
        files = subprocess.run(["git", "ls-files"], capture_output=True, text=True).stdout.split()
    out = {}
    for f in files:
        try:
            data = io.open(f, encoding="utf-8", errors="ignore").read()
        except Exception:                                       # noqa: BLE001
            continue
        names = [n for n in NAME_RE.findall(data)
                 if any(m.lower() in n.lower() for m in PRIVATE_MARKS)]
        if names:
            out[f] = len(names)
    return out


def main():
    files = subprocess.run(["git", "ls-files"], capture_output=True, text=True).stdout.split()
    h = hits(files)
    print("跟踪文件总数 =", len(files))
    print("命中文件 =", len(h), "| 命中次数合计 =", sum(h.values()))
    for f, n in sorted(h.items(), key=lambda kv: -kv[1])[:20]:
        print("  %4d  %s" % (n, f))
    print()
    print("口径：这里只数【当前工作树的跟踪文件】。「跑批会带走的产物」（reports/）与"
          "git 历史里的旧内容是两回事，见 m2/real-log.md 的 #79 与 tests/test_no_third_party_pii.py。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
