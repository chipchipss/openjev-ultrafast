r"""把 403 页的**原文**取出来一次（词表只收见过的）。单次请求，别再打 NCBI。"""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\Administrator\openjev-ultrafast")
os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:2080")
os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:2080")
os.environ.setdefault("BU_CDP_URL", "http://127.0.0.1:9222")

from jev_ultrafast.browser import Browser                    # noqa: E402

for url in (sys.argv[1:] or ["https://pubmed.ncbi.nlm.nih.gov/"]):
    b = Browser(url)
    try:
        p = b.observe(screenshot=False)
        print("URL   %s" % p.get("url"))
        print("TITLE %r" % (p.get("title"),))
        print("TEXT  %r" % (str(p.get("text") or ""),))
        print("ACTS  %d raw" % len(p.get("actions") or []))
        print("HTML  head=%r" % (str(p.get("html_head") or "")[:200],))
    finally:
        b.close()
