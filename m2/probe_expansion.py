"""L2 扩题（#51）的可行性探针：候选题目在**发车之前**先量三件事，零模型。

每一行候选问三个问题，全部用产品自己的读法（`skills.explicit_target` / `goal_phrases`）：
  A 起点页的动作表里**真挂着**那条目标链接吗（curl 不作证：bootstrap 的 docs 首页对 curl
    只有 406 字节、0 个 `<a>`，浏览器里却有整条侧栏；sqlite 首页那条 `lang.html` 的 label
    套了子元素，`<a>…</a>` 正则看不见）。
  B 用拟定的 goal 文案调 `explicit_target`，地板点的是不是**那一行**（点错=这题会烧在近似行
    上，正是 r105/#46 的形状；返回 None=首屏出不去，等于复制一份 r105 的病）。
  C 直接落到目标 URL，页面标题/正文里有没有断言要的那串字（没有=断言写不成立，r106 的
    "404 目标"教训）。

只在没有批次在跑时使用（它驱动自有 headless Chrome `:9222`）。
"""
import io
import os
import sys
import time
from urllib.parse import urljoin, urlparse

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, ".")
os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:2080")
os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:2080")

from jev_ultrafast.browser import Browser, StalePage       # noqa: E402
from jev_ultrafast import skills as S                       # noqa: E402

# (id, 起点 URL, 拟定 goal, 目标 href 片段, 目标页应含的串)
CANDS = [
    ("e001", "https://docs.astral.sh/uv/",
     "From the uv documentation home, open the 'Resolution' concept page.",
     "concepts/resolution", "resolution"),
    ("e002", "https://numpy.org/doc/stable/",
     "From the NumPy documentation home, open 'To the absolute beginner’s guide'.",
     "absolute_beginners", "absolute beginner"),
    ("e003", "https://www.sqlite.org/lang.html",
     "From the SQLite language page, open the 'SELECT' statement page.",
     "lang_select", "SELECT"),
    ("e004", "https://doc.rust-lang.org/cargo/",
     "From the Cargo book home, open the 'Cargo Reference'.",
     "reference/index", "Reference"),
    ("e005", "https://the-internet.herokuapp.com/",
     "From the example list, open the 'Dropdown' page.",
     "dropdown", "Dropdown"),
    ("e006", "https://the-internet.herokuapp.com/",
     "From the example list, open the 'Add/Remove Elements' page.",
     "add_remove_elements", "Add/Remove"),
    ("e007", "https://docs.python.org/3/",
     "From the Python documentation home, open the 'Tutorial'.",
     "tutorial/index", "Tutorial"),
    ("e008", "https://kubernetes.io/docs/concepts/",
     "From the Kubernetes concepts page, open 'Cluster Architecture'.",
     "concepts/architecture", "Cluster Architecture"),
    ("e009", "https://getbootstrap.com/docs/5.3/getting-started/introduction/",
     "From the Bootstrap introduction page, open the 'Buttons' component page.",
     "components/buttons", "Buttons"),
    ("e010", "https://git-scm.com/docs",
     "From the git manual index, open the 'git-commit' man page.",
     "/docs/git-commit", "git-commit"),
    ("e011", "https://developer.mozilla.org/en-US/docs/Learn",
     "From the MDN Learn page, open the 'Getting started' section for learners.",
     "Learn_web_development/Getting_started", "Getting started"),
    ("e012", "https://arxiv.org/list/cs.CL/recent",
     "From the recent Computation and Language listing, open the 'new' submissions page.",
     "/list/cs.CL/new", "Computation and Language"),
]

# 第二批：label 全部从 `--dump` 的真实索引里照抄（"名词只收见过的"）。
# 重复行是这一批的主要风险——同一个 label 在页面上挂两次（TOC 侧栏 + 正文），
# 位置表里就是两个不同节点、同分，地板会弃权而不是猜一个。弃权不必然失败（模型还能点），
# 但这类题不该进 L2 的分子，所以必须量。
CANDS2 = [
    ("t2-01", "https://doc.rust-lang.org/cargo/",
     "From the Cargo book home, open the 'Getting Started' chapter.",
     "getting-started/index", "Getting Started"),
    ("t2-02", "https://www.sqlite.org/",
     "From the SQLite home page, open the 'SQL Syntax' page.",
     "lang.html", "syntax"),
    ("t2-03", "https://numpy.org/doc/stable/",
     "From the NumPy documentation home, open the 'API reference'.",
     "reference/index", "API reference"),
    ("t2-04", "https://docs.python.org/3/",
     "From the Python documentation home, open the 'Library reference'.",
     "library/index", "Standard Library"),
    ("t2-05", "https://docs.python.org/3/",
     "From the Python documentation home, open the 'Installing Python modules' guide.",
     "installing/index", "Installing Python Modules"),
    ("t2-06", "https://the-internet.herokuapp.com/",
     "From the example list, open the 'Disappearing Elements' page.",
     "disappearing_elements", "Disappearing Elements"),
    ("t2-07", "https://the-internet.herokuapp.com/",
     "From the example list, open the 'File Download' page.",
     "/download", "Download"),
    ("t2-08", "https://git-scm.com/docs",
     "From the git manual index, open the 'Everyday Git' guide.",
     "giteveryday", "Everyday Git"),
    ("t2-09", "https://developer.mozilla.org/en-US/docs/Learn",
     "From the MDN Learn page, open the 'Core modules' section.",
     "Learn_web_development/Core", "Core"),
    ("t2-10", "https://books.toscrape.com/catalogue/page-1.html",
     "From the book catalogue, open the 'Mystery' book category.",
     "mystery_3", "Mystery"),
    ("t2-11", "https://books.toscrape.com/catalogue/page-1.html",
     "From the book catalogue, open the 'Classics' book category.",
     "classics_6", "Classics"),
    ("t2-12", "https://pandas.pydata.org/docs/",
     "From the pandas documentation home, open the 'User Guide'.",
     "user_guide", "User Guide"),
    ("t2-13", "https://pandas.pydata.org/docs/",
     "From the pandas documentation home, open the 'API reference'.",
     "reference/index", "API reference"),
    ("t2-14", "https://go.dev/doc/",
     "From the Go documentation home, open the 'Effective Go' page.",
     "effective_go", "Effective Go"),
]

# 第三批：唯一 label 的先从**已证可达**的站点取（t2-01 的教训——同 label 挂两次就是弃权），
# 再加 4 个新站点探路（新站点要先过可达性，代理对某些站会直接 000/墙）。
CANDS3 = [
    ("t3-01", "https://doc.rust-lang.org/cargo/",
     "From the Cargo book home, open the 'First Steps with Cargo' page.",
     "getting-started/first-steps", "First Steps"),
    ("t3-02", "https://doc.rust-lang.org/cargo/",
     "From the Cargo book home, open the 'Cargo.toml vs Cargo.lock' page.",
     "cargo-toml-vs-cargo-lock", "Cargo.lock"),
    ("t3-03", "https://doc.rust-lang.org/cargo/",
     "From the Cargo book home, open the 'Dependencies' page.",
     "guide/dependencies", "Dependencies"),
    ("t3-04", "https://www.sqlite.org/",
     "From the SQLite home page, open the 'Features' page.",
     "features.html", "features"),
    ("t3-05", "https://www.sqlite.org/",
     "From the SQLite home page, open the 'Frequently Asked Questions' page.",
     "faq.html", "FAQ"),
    ("t3-06", "https://www.sqlite.org/",
     "From the SQLite home page, open the 'JSON functions' page.",
     "json1.html", "JSON"),
    ("t3-07", "https://numpy.org/doc/stable/",
     "From the NumPy documentation home, open 'Building from source'.",
     "building/index", "building"),
    ("t3-08", "https://numpy.org/doc/stable/",
     "From the NumPy documentation home, open the 'Release notes' page.",
     "release.html", "release"),
    ("t3-09", "https://docs.python.org/3/",
     "From the Python documentation home, open the 'Built-ins reference'.",
     "builtins/index", "Built-in Functions"),
    ("t3-10", "https://docs.python.org/3/",
     "From the Python documentation home, open the 'Python HOWTOs' page.",
     "howto/index", "HOWTO"),
    ("t3-11", "https://docs.python.org/3/",
     "From the Python documentation home, open the 'Extending and embedding' guide.",
     "extending/index", "Extending and Embedding"),
    ("t3-12", "https://the-internet.herokuapp.com/",
     "From the example list, open the 'Checkboxes' page.",
     "checkboxes", "Checkboxes"),
    ("t3-13", "https://the-internet.herokuapp.com/",
     "From the example list, open the 'Drag and Drop' page.",
     "drag_and_drop", "Drag"),
    ("t3-14", "https://git-scm.com/docs",
     "From the git manual index, open the 'gitignore' man page.",
     "/docs/gitignore", "gitignore"),
    ("t3-15", "https://git-scm.com/docs",
     "From the git manual index, open the 'Glossary' page.",
     "/docs/gitglossary", "Glossary"),
    ("t3-16", "https://developer.mozilla.org/en-US/docs/Learn",
     "From the MDN Learn page, open the 'Your first website' module.",
     "Getting_started/Your_first_website", "website"),
    ("t3-17", "https://books.toscrape.com/catalogue/page-1.html",
     "From the book catalogue, open the 'Fantasy' book category.",
     "fantasy_19", "Fantasy"),
    ("t3-18", "https://books.toscrape.com/catalogue/page-1.html",
     "From the book catalogue, open the 'Poetry' book category.",
     "poetry_23", "Poetry"),
    # 新站点探路（只问 A：起点页有没有被索引到）
    ("t3-19", "https://doc.rust-lang.org/std/",
     "From the Rust standard library home, open the 'prelude' module page.",
     "prelude", "prelude"),
    ("t3-20", "https://www.kernel.org/",
     "From the kernel home page, open the 'Archives' of older releases.",
     "kernel.org/valid", "Archives"),
    ("t3-21", "https://en.cppreference.com/w/",
     "From the C++ reference home, open the 'C Standard Library' page.",
     "C/Standard_library", "C Standard Library"),
    ("t3-22", "https://www.lua.org/manual/5.4/",
     "From the Lua 5.4 manual contents, open '2 - Introduction'.",
     "2.html", "Introduction"),
]


def observe(b, tries=8):
    p = None
    for attempt in range(tries):
        try:
            p = b.observe(screenshot=False)
        except StalePage:
            time.sleep(0.4 * (attempt + 1))
            continue
        if S.indexed_actions(p.get("actions") or []):
            return p
        time.sleep(0.5 * (attempt + 1))
    return p


def shot(url):
    b = Browser(url)
    try:
        return b, observe(b)
    except Exception:
        b.close()
        raise


def dump(url, limit=70):
    """把起点页**真实索引到的**点击项打出来（label 原文照抄才许进 goal——
    "名词只收见过的"在扩题这里的字面意思）。"""
    b, p = shot(url)
    print("== DUMP %s" % url)
    if p is None:
        print("   NO PAGE OBSERVED")
        b.close()
        return
    for i, a in S.indexed_actions(p.get("actions") or [])[:limit]:
        if a.get("kind") != "click":
            continue
        print("   %-4s %-40s %s" % (i, str(a.get("label") or "")[:40],
                                    str(a.get("href") or "")[:60]))
    b.close()


def dump_all(url, limit=60):
    """把起点页**所有 kind** 的索引项打出来（表单题要看 fill/select 目标存不存在，
    只看 click 会把「有搜索框但没有 Go 按钮」读成可提交）。"""
    b, p = shot(url)
    print("== DUMP-ALL %s" % url)
    if p is None:
        print("   NO PAGE OBSERVED")
        b.close()
        return
    for i, a in S.indexed_actions(p.get("actions") or [])[:limit]:
        print("   %-4s %-8s %-34s %s" % (
            i, a.get("kind"), str(a.get("label") or a.get("placeholder") or "")[:34],
            str(a.get("href") or a.get("name") or "")[:48]))
    b.close()


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--dump":
        for u in sys.argv[2:]:
            try:
                dump(u)
            except Exception as e:
                print("   DUMP ERROR %r" % (e,))
        return 0
    if len(sys.argv) > 1 and sys.argv[1] == "--dump-all":
        for u in sys.argv[2:]:
            try:
                dump_all(u)
            except Exception as e:
                print("   DUMP-ALL ERROR %r" % (e,))
        return 0
    cands = CANDS3 if "--t3" in sys.argv else (CANDS2 if "--t2" in sys.argv else CANDS)
    for cid, start, goal, frag, want in cands:
        if "--only" in sys.argv and cid not in sys.argv[sys.argv.index("--only") + 1:]:
            continue
        print("== %s  %s" % (cid, start))
        print("   goal: %s" % goal)
        try:
            b, p = shot(start)
        except Exception as e:
            print("   A NAV ERROR %r" % (e,))
            continue
        if p is None:
            print("   A NO PAGE OBSERVED (index empty after retries) -- probe cannot judge")
            b.close()
            continue
        # `indexed_actions` 的编号是**按节点去重后的位置号**（`skills.py:53`），不是 `eNN` 的 NN。
        # 早先这里用 `idx["e"+target]` 反查，把两个正确落点读成了"抢错行"（e007/e010），
        # 是仪器错，不是产品错——所以 candidates 和 pick 都必须走同一张位置表。
        pairs = S.indexed_actions(p.get("actions") or [])
        idx = dict(pairs)
        hits = [(i, a) for i, a in pairs
                if frag.lower() in ((a.get("href") or "") + " " + (a.get("label") or "")).lower()]
        print("   A n_actions=%d candidates=%d first=%s" % (
            len(pairs), len(hits),
            [(i, str(a.get("label") or "")[:30], str(a.get("href") or "")[:42], a.get("id")) for i, a in hits[:2]] or "NONE"))
        d = S.explicit_target(p, goal, [])
        pick = None
        if d:
            t = str(d.get("target") or "")
            node = idx.get(t) or {}
            pick = (t, node.get("id"), str(node.get("label") or "")[:30],
                    str(node.get("href") or "")[:42])
        print("   B phrases=%s" % (S.goal_phrases(goal),))
        print("   B explicit_target -> %s   (want frag %s)" % (pick or "None", frag))
        # 弃权时最可能的原因是同一 label 挂了两次（侧栏 + 正文）：位置表里是两个节点、
        # 同分，`top-second < 0.15` 就该弃权。把这个数打出来，弃权才有解释而不是猜测。
        dup = [(ph, sum(1 for _, a in pairs
                        if str(a.get("label") or "").strip().lower() == ph.lower()))
               for ph in S.goal_phrases(goal)]
        print("   B label-dup=%s" % (dup,))
        b.close()
        if not hits:
            print("   C skipped: no candidate href on the start page")
            continue
        tgt = urljoin(start, (hits[0][1].get("href") or "").split("#")[0])
        try:
            b2, q = shot(tgt)
            text = str(q.get("text") or "")
            print("   C %s -> title=%r  want=%r present=%s" % (
                urlparse(tgt).path[:42], str(q.get("title") or "")[:56], want,
                want.lower() in text.lower()))
            b2.close()
        except Exception as e:
            print("   C NAV ERROR %r" % (e,))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
