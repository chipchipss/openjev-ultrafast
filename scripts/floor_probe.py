"""Observe the MDN/RFC homepages through the real snapshot pipeline and dump
the top action-space elements, to see what first_action_floor would pick.
Requires headless Chrome on 9222 (proxy on).
Run: C:/Users/Administrator/miniconda3/envs/jev/python.exe scripts/floor_probe.py
"""
import os
import sys

sys.path.insert(0, r"C:\Users\Administrator\openjev-ultrafast")

from jev_ultrafast.browser import Browser          # noqa: E402
from jev_ultrafast.decider.action_space import action_space  # noqa: E402
from jev_ultrafast.model import _element_score     # noqa: E402

URLS = [
    "https://developer.mozilla.org/zh-CN/",
    "https://www.rfc-editor.org/",
]

for url in URLS:
    b = Browser(url)
    page = b.observe(screenshot=False)
    print("=== ", url)
    print("page url:", page.get("url"), "| title:", str(page.get("title"))[:60])
    elements, targets, controls = action_space(page["actions"])
    ranked = sorted(elements, key=lambda e: _element_score(e), reverse=True)
    for e in ranked[:8]:
        print(f"  idx={e['index']:>3} score={_element_score(e):>4} "
              f"role={str(e.get('role','')):<10} label={str(e.get('label',''))[:60]!r}")
    b.close()
