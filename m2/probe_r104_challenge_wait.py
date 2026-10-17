"""r104 final attribution: it is the headless-Chrome TLS/UA fingerprint that gets the
challenge, not the proxy route -- curl with the SAME chrome UA still gets 200 while the
browser gets the challenge every time. One last check: after ~30s does the challenge
auto-resolve in the live tab (title flips)? Zero model."""
import io
import json
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, ".")
os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:2080")
os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:2080")

from jev_ultrafast.browser import Browser, StalePage               # noqa: E402
from jev_ultrafast import skills as S                              # noqa: E402

URL = "https://pubmed.ncbi.nlm.nih.gov/?term=CRISPR+off-target"
b = Browser(URL)
try:
    t0 = time.time()
    last = ""
    while time.time() - t0 < 45:
        try:
            title = b.evaluate("document.title") or ""
        except Exception:
            title = "(stale)"
        if title != last:
            print("%.1fs title=%r" % (time.time() - t0, title[:50]))
            last = title
        if "reCAPTCHA" not in title and title != "(stale)":
            break
        time.sleep(2)
    print("final url=%s title=%r" % (b.evaluate("location.href"),
                                     str(b.evaluate("document.title") or "")[:50]))
finally:
    b.close()
