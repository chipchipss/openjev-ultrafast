"""r104 attribution: retry the results URL repeatedly in fresh tabs -- is the wall
per-request random (TLS/JA3 shape of headless Chrome) or session-bound? Zero model."""
import io
import json
import os
import re
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, ".")
os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:2080")
os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:2080")

from jev_ultrafast.browser import Browser, StalePage               # noqa: E402
from jev_ultrafast import skills as S                              # noqa: E402

URL = "https://pubmed.ncbi.nlm.nih.gov/?term=CRISPR+off-target"

for round in range(4):
    b = Browser(URL)
    try:
        time.sleep(2.5)
        try:
            p = b.observe(screenshot=False)
            print("round %d: title=%r url=%s actions=%d"
                  % (round + 1, str(p.get("title") or "")[:44], p.get("url"),
                     len(S.indexed_actions(p.get("actions") or []))))
        except Exception as e:                                      # noqa: BLE001
            print("round %d: observe EXC %s: %s" % (round + 1, type(e).__name__, e))
    except Exception as e:                                          # noqa: BLE001
        print("round %d: init EXC %s: %s" % (round + 1, type(e).__name__, e))
    finally:
        try:
            b.close()
        except Exception:
            pass
