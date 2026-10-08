"""Measure the *shape of a results page* so "click the result" style fixes are scheduled
on evidence, not on the guess that a target row is where the agent can see it.

Run ONLY when no batch is in flight (it drives the owned headless Chrome on :9222).
Zero model calls: navigate + observe + call the skill functions directly.

Why this file exists (2026-10-08, #15 re-attribution): the "second hop" hypothesis said
r102/r106/r115 all stand on a results page their own fill+submit produced and then abstain.
Reading the three pages shows three *different* situations, and only one of them is cheap:

  r102 arXiv     the submit lands on an archive-scoped search with 2 rows, neither of them
                 the target paper; under every reachable ordering the target is the LAST row
                 (36 of 36) and arXiv's row *link label* is `arXiv:NNNN.NNNNN`, not the title.
  r106 HF        the assertion target `huggingface.co/ggml-org/llama.cpp` renders
                 "404 - Hugging Face" (responseStatus 401): the task cannot be passed.
  r115 python.org the target link IS in the first viewport (nav `Downloads` -> `/downloads/`);
                 what stops the floor is that no tier of explicit_target can equate the goal
                 phrase 'Download Python' with the plural label 'Downloads'.

It also records a systemic limit for any future "click result N" proposal: the page snapshot
indexes only viewport-visible actions, so a results page yields ~2 rows to the agent at best.
"""
import io
import re
import sys
import os

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, ".")
os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:2080")
os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:2080")

from jev_ultrafast.browser import Browser                    # noqa: E402
from jev_ultrafast import skills as S                        # noqa: E402

R102_GOAL = ("Search arXiv for the paper 'Attention Is All You Need' "
             "and open its abstract page.")
R115_GOAL = "From the Python homepage, open the 'Download Python' releases page."
R116_GOAL = "From the Rust documentation home, open 'The Cargo Book'."
R122_GOAL = "Open RFC 9110, 'HTTP Semantics'."
R105_GOAL = "Open the Releases page of the pytorch/pytorch repository."

CASES = [
    ("r102 floor-lands-here", "https://arxiv.org/search/physics?query=Attention+Is+All+You+Need&searchtype=all&abstracts=show&order=-announced_date_first&size=50", R102_GOAL, "1706.03762"),
    ("r102 all-archives", "https://arxiv.org/search/?query=Attention+Is+All+You+Need&searchtype=all", R102_GOAL, "1706.03762"),
    ("r106 assertion target", "https://huggingface.co/ggml-org/llama.cpp", "n/a", "ggml-org/llama.cpp"),
    ("r115 python home", "https://www.python.org/", R115_GOAL, "/downloads/"),
    ("r115 python search", "https://www.python.org/search/?q=Download+Python&submit=", R115_GOAL, "/downloads/"),
    ("r116 rust root", "https://doc.rust-lang.org/", R116_GOAL, "/cargo/"),
    ("r116 rust std (where the run sits)", "https://doc.rust-lang.org/stable/std/index.html", R116_GOAL, "/cargo/"),
    ("r122 rfc-editor root", "https://www.rfc-editor.org/", R122_GOAL, "rfc9110"),
    ("r105 github root", "https://github.com/", R105_GOAL, "pytorch"),
]

ROWS_RE = re.compile(r"Showing 1[–-](\d+) of ([\d,]+) results")


def raw_html(url):
    try:
        import requests
        return requests.get(url, timeout=25,
                            headers={"User-Agent": "Mozilla/5.0"},
                            proxies={"http": os.environ["HTTP_PROXY"],
                                     "https": os.environ["HTTPS_PROXY"]}).text
    except Exception as e:                                          # noqa: BLE001
        print("    (raw html unavailable: %s)" % e)
        return ""


for name, url, goal, needle in CASES:
    print("=" * 78)
    print("%s\n  %s" % (name, url))
    b = Browser(url)
    try:
        p = b.observe(screenshot=False)
        clicks = [(i, str(a.get("label"))[:46], str(a.get("href"))[:52])
                  for i, a in S._indexed(p.get("actions") or []) if a.get("kind") == "click"]
        text = p.get("text") or ""
        m = ROWS_RE.search(text.replace("\n", " | "))
        print("  landed=%s  n_click=%d  %s" % (p.get("url"), len(clicks),
                                               m.group(0) if m else "no 'Showing' line"))
        print("  needle %r in visible text = %s" % (needle, needle in text))
        html = raw_html(p.get("url") or url)
        if html:
            ids = re.findall(r"arXiv:(\d{4}\.\d{4,5})", html)
            if ids:
                pos = ids.index(needle) if needle in ids else None
                print("  raw html rows=%d  target row index=%s (0-based, of %d on page)"
                      % (len(ids), pos, len(ids)))
            else:
                a_tags = re.findall(r'href="(/[A-Za-z0-9._\-/]*)"', html)
                print("  raw html: needle in html=%s   anchors=%d"
                      % (needle.lower() in html.lower(), len(a_tags)))
        hit = [c for c in clicks if needle.lower().lstrip("/") in c[2].lower()]
        print("  visible clicks carrying the needle: %d -> %s" % (len(hit), hit[:3]))
        if goal != "n/a":
            print("  phrases=%s" % (S._phrases(goal),))
            d = S.explicit_target(p, goal, [])
            if d:
                ci = (d.get("choice") or "").lstrip("e")
                lab = next((a.get("label") for i, a in S._indexed(p["actions"]) if i == ci), None)
                print("  explicit_target -> %s %s (%r)" % (d.get("operation"), d.get("choice"), lab))
            else:
                print("  explicit_target -> None  (floor abstains here)")
    except Exception as e:                                          # noqa: BLE001
        print("  EXC %s: %s" % (type(e).__name__, e))
    finally:
        b.close()
