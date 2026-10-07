"""Measure the shape of a headless cold-profile page so the wall marker list can be
extended on evidence instead of guesses. Run ONLY when no batch is in flight."""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, ".")
os.environ.setdefault("HTTPX_PROXY", "http://127.0.0.1:2080")

from jev_ultrafast.browser import Browser
from jev_ultrafast.evaluator import is_bot_wall, _WALL_MAX_TEXT, _WALL_MAX_ACTIONS

URLS = [
    ("pubmed root (the observed 403)", "https://pubmed.ncbi.nlm.nih.gov/"),
    ("pubmed search (goal start)", "https://pubmed.ncbi.nlm.nih.gov/?term=CRISPR+off-target"),
    ("pypi (control: real content)", "https://pypi.org/"),
]

for name, url in URLS:
    b = Browser(url)
    try:
        p = b.observe()
        text = (p.get("text") or "")
        acts = p.get("actions") or []
        print(f"--- {name}")
        print(f"    url={p.get('url')}")
        print(f"    title={p.get('title')!r}")
        print(f"    len(text)={len(text)}  n_actions={len(acts)}  "
              f"gate=({_WALL_MAX_TEXT},{_WALL_MAX_ACTIONS})  is_bot_wall={is_bot_wall(p)}")
        print(f"    text[:160]={text[:160]!r}")
    finally:
        b.close()
