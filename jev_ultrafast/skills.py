"""M16 确定性技能层：在模型之前短路"高精度可判定"的决策。

设计（与 M1.5 机制同构：纯世界语言、env 可关、失败即回落）：
    choose() → skills.route()
                 ├─ 命中 → 直接产出 decision（跳过 2B，确定性正确、零延迟）
                 └─ 未命中 → 回落 provider.decide()（模型照旧）

只做"字面可判"的技能——goal 里写明的目标/字段/值：
  1. blocked_dead_page  chrome 错误页 → BLOCKED
  2. explicit_target    goal 里的显式目标（引号串 / 路径 / RFC 号）唯一匹配某元素 → CLICK
  3. form_fill          "fill the <字段> field with '<值>'" → TYPE_TEXT 该字段
  4. form_submit        goal 含 submit 且已填过字段 → CLICK 提交按钮

精度优先：每个技能都要求"强信号"（唯一匹配 / 字面包含），否则返回 None。
env：M16_SKILLS=0 全关；M16_SKILL_<NAME>=0 单关（NAME 大写）。
"""
from __future__ import annotations
import os
import re
from urllib.parse import urlparse as _urlparse

KIND_TO_OP = {"click": "CLICK", "fill": "TYPE_TEXT", "select": "SELECT"}

STOPWORDS = {
    "the", "a", "an", "of", "to", "and", "or", "for", "with", "in", "on", "by",
    "open", "go", "search", "find", "page", "article", "website", "site", "from",
    "then", "it", "its", "use", "about", "please", "click", "this", "that", "new",
}
SUBMIT_WORDS = {"submit", "send", "go", "search", "continue", "ok", "apply", "confirm",
                "save", "update"}   # save/update：t003/t005 的保存按钮（旧集合缺 save → 永不点）


def _enabled(name: str) -> bool:
    if os.environ.get("M16_SKILLS", "1") != "1":
        return False
    return os.environ.get(f"M16_SKILL_{name.upper()}", "1") == "1"


def _tokens(s: str) -> list[str]:
    # Unicode 分词：\w 覆盖 CJK（"openai 官网" → ["openai","官网"]），
    # 否则中文被丢弃会让不同 label 归一化后碰撞，破坏"精确匹配"判据。
    return [t for t in re.findall(r"[^\W_]+", (s or "").lower())]


def _content(s: str) -> list[str]:
    return [t for t in _tokens(s) if t not in STOPWORDS and len(t) > 1]


def _indexed(actions: list[dict]) -> list[tuple[str, dict]]:
    """(index_str, action)，编号规则与 model.action_space / decision_validator 一致。"""
    seen: dict = {}
    out = []
    for a in actions:
        kind = a.get("kind")
        if kind not in KIND_TO_OP:
            continue
        node = a.get("node")
        if node not in seen:
            seen[node] = len(seen) + 1
        out.append((str(seen[node]), a))
    return out


def _decision(op: str, index: str | None, action: dict | None, skill: str,
              *, text: str | None = None) -> dict:
    """构造与 provider 同形的 decision（含 choice/target，且满足 validator 的映射链）。

    text：技能已知应填入的值（来自 goal 的字面量）。给了它 agent 就直接用，
    不再调 Text Helper——helper 的 field_context 里带 recent_actions，
    实测会把上一步的点击值（"Zürich, Switzerland"）当成日期值填进去（Flights v15）。
    """
    choice = action["id"] if action is not None else op
    out = {
        "choice": choice,
        "operation": op,
        "target": index,
        "operation_confidence": 1.0,
        "target_confidence": 1.0 if index is not None else None,
        "confidence": 1.0,
        "probabilities": {choice: 1.0},
        # agent.act 契约要求这两个键（provider 同形）
        "latency_ms": 0,
        "usage": None,
        "skill": skill,
    }
    if text:
        out["text"] = text
    return out


def _wait(skill: str, tries: int = 6) -> dict | None:
    """等页面渲染（建议列表 / 下拉选项 / 日历日格是异步出现的）。

    缺陷#26：技能在"该出现的候选还没渲染出来"时直接 return None → 回落模型 →
    模型在没有候选的页面上只能瞎点或 BLOCKED（Flights v24 实况：目的地建议、
    票种选项、日历日格都撞过这个窗口）。这里改成主动等一拍：最多连续 tries 次，
    之后仍无候选才让位（由 StepBudget 兜底，不会无限等）。
    """
    return {
        "choice": "wait",
        "operation": "WAIT",
        "target": None,
        "operation_confidence": 1.0,
        "target_confidence": None,
        "confidence": 1.0,
        "probabilities": {"wait": 1.0},
        "latency_ms": 0,
        "usage": None,
        "skill": skill,
    }


def _trailing_waits(history: list) -> int:
    n = 0
    for h in reversed(history or []):
        if h.get("kind") == "wait":
            n += 1
        else:
            break
    return n


def _can_wait(history: list, tries: int = 3) -> bool:
    return _trailing_waits(history) < tries


def _last_real(history: list) -> dict:
    """最后一个"真实动作"（跳过 wait）。

    缺陷#26b：技能发的 WAIT 会占据 hist[-1]，让"上一步是 fill/点了日期字段"
    这类锚点失效，技能随即让位给模型（Flights v25 实况：entity_confirm 等了一拍
    就再也认不出刚填过目的地）。
    """
    for h in reversed(history or []):
        if h.get("kind") != "wait":
            return h
    return {}


# ---------------------------------------------------------------------------
# 1. 死页 → BLOCKED
# ---------------------------------------------------------------------------

def blocked_dead_page(page: dict, goal: str, history: list) -> dict | None:
    url = (page.get("url") or "")
    if url.startswith("chrome-error://") or url.startswith("about:neterror"):
        return _decision("BLOCKED", None, None, "blocked_dead_page")
    return None


def page_not_ready(page: dict, goal: str, history: list) -> dict | None:
    """页面还在导航/渲染（观察里没有任何可操作元素）→ 等一拍，别让模型在空白页上决策。

    Flights v114/v117 实况：点完票种下拉后页面瞬时空白，全部技能落空 → 模型在空白页上
    选了 BLOCKED，整轮 3.3s 收口（0/7，两轮同签名）。空白页不是"决策点"，是"还没渲染"。
    """
    if not history:
        return None                        # 起始页交给 predict 的空白页重试逻辑
    # 滚动/可见性类目标例外：滚到底后页面只剩文本、没有任何可交互元素，那不是"还没渲染"，
    # 而是任务要求的**最终状态**。在这里等下去只会让模型反复 scroll/wait
    # （l004 实况：122 行日志全是 scroll 与 wait 交替，永远等不到"可交互元素"）。
    # 让位给模型去滚动，到位后由 stop_when_visible 收口。
    # 但只对"滚到某物可见"这类目标让位：l002/l003 是"滚去找"（没有可见性子句），
    # 那些页面上空白就该照旧等待，否则会让模型在空白页上瞎决策。
    # 判定与 scroll_to_target 共用（见 _is_scroll_visible_goal，两种句式必须一致）。
    if _is_scroll_visible_goal(goal):
        return None
    # 判"没有任何可交互元素"：不能看 page["actions"] 是否为空 —— 快照总会追加合成控件
    # （scroll/reload/wait），真正空白的是 KIND_TO_OP 里的那些，_indexed 正好按此过滤。
    if not _indexed(page.get("actions") or []):
        # 有正文、零可交互元素 = **内容页**（搜索结果 / JSON 回显 / 文章 / 报错页），
        # 不是"还没渲染"。判据必须看正文，否则表单提交后的回显页会被无限等待：
        # f002 实况——httpbin /post 的 JSON 响应零控件 → 连等 57 拍撞上 60 步上限，
        # 尽管断言（页面含 "hello world"）早已满足，goal_reached 根本没机会跑。
        if (page.get("text") or "").strip():
            return None
        return _wait("page_not_ready")
    return None


# ---------------------------------------------------------------------------
# 1b. 首步探索地板（M18）：第 0 拍模型 BLOCKED → 强制选最显著的真实动作
# ---------------------------------------------------------------------------

def first_action_floor(page: dict, goal: str, history: list) -> dict | None:
    """模型 BLOCKED、页面有真实可交互元素 → 强制探索一次。

    BLOCKED 的语义是"试过之后无路可走"。一步没走就放弃，是对陌生页面的保守
    误判（StartLux-2B 实况：s005 MDN 首页 0.74 / n004 RFC Editor 首页 0.77
    置信度 BLOCKED，两页都有可推进的控件）。

    由 model.choose() 在拿到模型 BLOCKED 后调用（此时技能层已全部落空）。
    这里不再重问模型——直接按打分取最优可交互元素执行。

    探索预算：不限于第 0 拍——**上一拍也是 floor 且改变了世界**时继续兜
    （菜单类站点一跳展开不了目标，s005 实况：floor 点开 HTML 菜单后模型在
    第 2 拍又 BLOCKED，而真实路径 Web APIs → Fetch API 需要两跳）。上限
    MAX_FLOOR_STEPS 次真实动作；上一步没改变世界（点了没反应）也停——
    floor 在死控体上重试只会重演 no_effect 循环。

    打分：role 权重（textbox > button > link）+ goal token 重合 bonus
    （s005 的真实入口是 "Web APIs"——goal 含 "API"，一次对齐；RFC 首页
    的 searchbox role=100 天然命中）。

    为什么安全：
      - 有界（MAX_FLOOR_STEPS），且每次都要求世界确实变了；
      - 只从真实元素里选（_indexed 过滤 scroll/wait/reload 合成控件）；
      - 后续安全链不变：Policy 黑名单 / DoneGuard / Validator 照常拦。
    env M18_FIRST_ACTION_FLOOR=0 关闭。
    """
    if os.environ.get("M18_FIRST_ACTION_FLOOR", "1") != "1":
        return None
    candidates = _indexed(page.get("actions") or [])
    if not candidates:
        return None
    if history:
        # 探索中：整条链必须是 floor 且每拍都改变了世界，且没超预算。
        # 中间插过一次模型决策（skill=None）→ 链断，放行模型判断。
        floor_hist = [h for h in history if h.get("skill") == "first_action_floor"]
        if not floor_hist or len(floor_hist) != len(history):
            return None
        if len(floor_hist) > _MAX_FLOOR_STEPS:
            return None
        if not floor_hist[-1].get("page_changed"):
            return None
    goal_tokens = {t for t in _tokens(goal) if t not in STOPWORDS}
    # 排除 floor 自己已点过的元素：菜单按钮点开后仍在新页态里、分数仍最高，
    # 不剔除就是 SPA toggle 循环（s005 实况：Web APIs 连点 3 次，开→合→开）。
    # M1.5 机制③同原则：重做已做过的动作不构成进展。
    tried = {h.get("choice") for h in (history or []) if h.get("skill") == "first_action_floor"}
    candidates = [(i, a) for i, a in candidates if a.get("id") not in tried]
    if not candidates:
        return None
    best = max(candidates,
               key=lambda ia: _floor_score(ia[1]) + _goal_overlap(ia[1], goal_tokens))
    index, action = best
    op = KIND_TO_OP[action["kind"]]
    return _decision(op, index, action, "first_action_floor")


_MAX_FLOOR_STEPS = int(os.environ.get("M18_FLOOR_MAX_STEPS", "3"))


def _floor_score(a: dict) -> int:
    """role 权重（与 model._element_score 同构，此处不 import 避免循环依赖）。"""
    role = a.get("role", "")
    if role in ("textbox", "searchbox", "combobox"):
        return 100
    if role == "button":
        return 50
    if role == "link":
        return -10
    return 0


def _goal_overlap(a: dict, goal_tokens: set) -> int:
    """goal 与 label 的内容词重合数 ×40：把 "Web APIs"（goal 含 api）顶到
    并列按钮之上；不喧宾夺主（搜索框 role=100 仍高于纯重合）。
    单复数归一（api/apis）：去尾 s 再比，别让英文复数毁掉唯一的高分入口。"""
    if not goal_tokens:
        return 0
    label_tokens = {_stem(t) for t in _content(a.get("label") or "")}
    return 40 * len(goal_tokens & label_tokens)


def _stem(t: str) -> str:
    return t[:-1] if len(t) > 3 and t.endswith("s") else t


# ---------------------------------------------------------------------------
# 2. 显式目标 → CLICK
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 0. 目标已达 → DONE
#    缺陷#19：修掉"连续 3 次无效果 → blocked"恒真 bug 后，agent 达成目标仍继续
#    点击直到预算耗尽（s005 实况：已到 Fetch API 页，又点到 fetchLater()）。
#    本技能把"达成即停"写成显式规则：goal 显式命名的目标出现在当前页 URL/title
#    → DONE。只认 URL/title（不认正文），避免 submit 类任务提前收口。
# ---------------------------------------------------------------------------

def _norm_page(s: str) -> str:
    """URL/title 归一：解码 %XX、分隔符统一为空格、去重音。"""
    try:
        from urllib.parse import unquote
        s = unquote(s or "")
    except Exception:
        s = s or ""
    s = s.lower().translate(str.maketrans("üöäéèç", "uoaeec"))
    s = re.sub(r"[_\-/.+]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _flat(s: str) -> str:
    """短语比对专用归一：去重音、**去撇号**、非字母数字折成空格、压缩空白。

    与 _norm_page 的差别只有一个但致命：_norm_page 保留撇号（URL/title 原样），
    而短语侧必须把 "Gödel's" 的撇号也去掉 —— 否则一侧是 "godel's"、另一侧是
    "godel s"，永远对不上（wiki 实况：goal_reached 因此永不触发 DONE，DONE 只能
    由模型提议再交 decider 复核，每次 5.7s 且形成提议循环）。
    保留 CJK（\\u4e00-\\u9fff），中文目标同样可比。
    """
    s = (s or "").lower().translate(str.maketrans("üöäéèç", "uoaeec"))
    s = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


_NAV_OBJ_RE = re.compile(
    r"\b(?:navigate to|go to|open|visit|reach)\s+(?:the\s+)?"
    r"(?P<t>[A-Za-z][\w'\-]*(?:\s+[A-Za-z][\w'\-]*){0,4}?)"
    r"(?:\s+(?:page|section|article|tab|view|screen|link|dropdown)\b|[,.]|$)",
    re.I,
)

# C2b 缩写表：URL 里常见的缩写 ↔ goal 里的全称。键 = URL 缩写,值 = goal 全称
# ——匹配方向是"goal 的头词全称 → 展开出 URL 缩写形式去 URL 里找"
#（n001 实况 2026-10-07:goal 要 "documentation",目标站 URL 是 docs.python.org）。
_ABBREV = {"docs": "documentation", "doc": "documentation"}


def goal_reached(page: dict, goal: str, history: list) -> dict | None:
    hist = history or []
    if not hist:
        return None                        # 0 步 DONE 会被 DoneGuard 拦，不产出
    # 只在"导航到目标"类 goal 上生效。以下情况到达页面 ≠ 完成：
    #   破坏/交易类（delete / book…）——x001/x002 的正确答案是放弃
    if re.search(r"\b(delete|remove|destroy|permanently|book|buy|purchase|order)\b",
                 goal or "", re.I):
        return None
    if re.search(r"\bscroll\b", goal or "", re.I) and \
            not re.search(r"\b(open|navigate|go to|visit|reach)\b", goal or "", re.I):
        # 只在**纯滚动**目标上整体让位：那种目标「到达页面」确实不等于完成，
        # 要靠 stop_when_visible 收口。
        #
        # 目标**同时**要求导航和滚动时，导航那半段达成就该能收口。l002 实况：
        # "Open the Wikipedia 'List of countries by population' article and scroll to
        # the table" —— agent 第 3 步已点进正确文章（final_url 一度正确），但这个
        # 守卫让它永远产不出 DONE，于是继续乱点（点了 "Hide Appearance"、"categories"）
        # 跑偏到 Wikipedia:Categorizing_redirects，把一个已达成的任务判失败。
        return None
    # 目标里"要填进去的值"全部出现在页面文本上 → 已经达成。
    # _phrases 故意跳过 "with 'X'" 形式的引号串（当值不当目标），于是
    # "Go to /forms/post and fill the comments field with 'hello world', then submit
    # the form." 的证据短语只剩 /forms/post —— 提交后落到 /post，页面永远不含它，
    # 收不了口：f002 实况提交成功（final_url=/post，断言已过）却连等 30 拍撞上
    # 60 步上限才结束。
    # 为什么安全：未提交时 textarea/input 的值**不进 innerText**，只有提交后页面把
    # 数据回显出来才看得到；且要求已经发生过动作（history 非空，上面已挡 0 步）。
    _vals = _fill_values(goal)
    if _vals:
        _ptext = page.get("text") or ""
        if all(re.search(re.escape(v), _ptext, re.I) for v in _vals):
            return _decision("DONE", None, None, "goal_reached")
    # 缺陷#40：URL 匹配只用 **path**，不吃 query —— 搜索词会原样出现在 ?q=… 里，
    # 于是 "Search for 'OpenAI' and open the official OpenAI website" 在**搜索结果页**
    # 就命中短语 → goal_reached 连发 8 次 DONE（s001 实况，整轮判失败）。
    # query 只是把搜索词回声出来，不构成"已到达目标"的证据。
    _u = _urlparse(page.get("url") or "")
    here_url = _flat(_norm_page(_u.netloc + _u.path))
    # 带 query 的完整 URL：**提交类**目标的成功判据就在 query 里
    # （"Search for 'automation' and submit the search form" → 断言 q=automation）。
    here_full = _flat(_norm_page(_u.netloc + _u.path + "?" + _u.query))
    here_all = here_url + " " + _flat(_norm_page(page.get("title") or ""))
    # 当前 URL 的 query：搜索词会被原样回声在这里，也会回声进结果页标题
    # （"OpenAI - Google Search"）。凡"短语就是搜索词"的一律不算到达目标 ——
    # 否则 "Search for 'OpenAI' and open the official OpenAI website" 在结果页
    # 就判完成（s001 实况：连发 8 次 DONE，整轮失败）。
    query_echo = _flat(_norm_page(_u.query))
    # 起点页：优先用 agent 提供的任务起始 URL。history[0]["url"] 是"动作之后"的
    # URL——第一步就到达目标时会把它误当起点，导致 goal_reached 永不触发
    # （s003 实况：一步跳到 /standards/，"standards" 已在"起点"里 → 判据自锁）。
    start = _flat(_norm_page(page.get("start_url") or hist[0].get("url") or ""))

    nav_verb = bool(re.search(r"\b(open|navigate|go to|find|visit|reach|use)\b",
                              goal or "", re.I))
    submit_verb = bool(re.search(r"\b(submit|search|type|look up)\b", goal or "", re.I))

    # 目标明写是"网站/站点/官网"时，到达判据必须落在 **host** 上：goal 说 "open the
    # official OpenAI website"，点进任意一条标题含 OpenAI 的新闻结果也算"路径含
    # openai"，但那不是官网（s001 实况）。维基/RFC 类目标不写 website，仍走路径+标题。
    # 注意必须带"网站/官网"字样，不能见 "site" 就算：s002 的 goal 是 "Use the site search
    # on docs.python.org …"——这里 site 指"站内搜索功能"，不是"打开该网站"，按 host 判到达
    # 会让 URL 已含 asyncio 的结果页判不出到达（s002 实况）。
    website_goal = bool(re.search(
        r"\b(?:website|web\s*site|homepage|official\s+(?:site|website|page))\b",
        goal or "", re.I))
    host_flat = _flat(_norm_page(_u.netloc))

    def hit(phrase: str, where: str) -> bool:
        pn = _flat(phrase)
        if not pn or pn in start:
            return False
        if website_goal:
            return pn.replace(" ", "") in host_flat.replace(" ", "")
        # 短语里的空格在 URL 里不存在："RFC 9110" 的 _flat 是 "rfc 9110"，而目标页是
        # /info/rfc9110/ —— 纯排版差异导致永远判不出到达（n004 实况）。两侧压掉空格再比一次。
        return pn in where or pn.replace(" ", "") in where.replace(" ", "")

    # 路径 A：显式短语（引号串 / RFC 号）出现在 URL 或标题 → 已到达目标页
    for p in _phrases(goal):
        if p.startswith("/") or len(p.strip()) < 3:
            continue
        # 短语就是搜索词（出现在 ?q= 里）时不算"已到达"—— 但两类例外：
        #   1) 目标是"打开某个网站"：那种目标只认 host（见 hit），query 永远不算证据；
        #   2) 目标是"提交搜索"：?q= 恰恰就是成功判据本身。
        # s007 实况：一律排除 query 后 goal_reached 永不触发，搜索已经成功却继续跑，
        # 模型接手又提交了一次**空**表单 → 终点变成 ?q= → FAIL。
        # 但 goal 里还有**第二个 hop**（"…and open the first result link"）时，?q= 又不算了：
        # s011 的断言要的是结果页 articles.html/technology.html，而不是结果列表本身
        # （实况：搜索成功后 goal_reached 连发 5 次 DONE，断言 url_matches 挂）。
        _second_hop = bool(re.search(r"\bopen\b[^.;]*\b(result|link|article|item|page)\b",
                                     goal or "", re.I))
        if (_flat(p) and _flat(p) in query_echo
                and (website_goal or not submit_verb or _second_hop)):
            continue
        if nav_verb and hit(p, here_all):
            return _decision("DONE", None, None, "goal_reached")
        # 路径 B：搜索/提交类，短语落在完整 URL（含查询串）
        if submit_verb and hit(p, here_full):
            return _decision("DONE", None, None, "goal_reached")

    # 路径 C：无引号导航目标——"navigate to the Standards page" 这类。三条判据：
    #   C1 目标短语"整段连续"出现在标题里。必须连续（不是"内容词都出现"）：
    #      n001 实况——goal 要 docs.python.org，中间页 python.org/doc/ 的标题
    #      "Our Documentation | Python.org" 同时含 python+documentation，
    #      按词判会误判到达并提前 DONE。
    #   C2 目标的头词（末位内容词）出现在当前 URL 里。补 C1 的漏网：
    #      n003 实况——目标页标题是 "Standards and guidelines | W3C"，
    #      不含连续的 "w3c standards"，但 URL 是 /standards/。
    #   C2b 头词的**常见缩写**出现在 URL 里。n001 实况（2026-10-07 隔夜诊断）：
    #      goal "Open the Python documentation section"，agent 第 1 步已到
    #      docs.python.org/3/，但 C1 标题无 "python documentation"、C2 URL 是
    #      **docs**.python.org 不含 "documentation"——已达成却被漏接，agent 又
    #      点 logo 跑回 python.org 循环到预算耗尽（correct_abandon）。缩写归一
    #      是 laya-browser-agent goal-aware 原则的同类应用：目标词已到达就不该
    #      因排版变体而漏判。
    if nav_verb and not website_goal:
        # website 类目标（"open the official X website"）不走这里：它的到达判据只能是
        # host（见 hit），否则点进任意标题含 X 的新闻页都会判到达（s001 实况）。
        m = _NAV_OBJ_RE.search(goal or "")
        if m:
            obj = m.group("t")
            obj_n = " ".join(_tokens(obj))
            title = _norm_page(page.get("title") or "")
            if obj_n and obj_n in title and obj_n not in start:
                return _decision("DONE", None, None, "goal_reached")
            toks = _content(obj)
            head = toks[-1] if toks else ""
            # C2b: goal 用全称、URL 用缩写时展开（documentation → docs/doc）。
            # 缩写只允许命中 **host**，不允许命中路径——n001 实况：起点站 python.org
            # 自己就有 /doc/（文档入口页），路径级匹配会把中间页误判为到达（C1 注释
            # 警告过的原始案例，断言要的是 docs.python.org 域）；而目标站是
            # docs.python.org，'docs' 在 host 里。C2 原判据对全称仍是全 URL 匹配
            # （n003 /standards/ 依赖它），只有**展开的缩写**收紧到 host。
            from urllib.parse import urlparse as _urlparse2
            _host_flat = _flat(_norm_page(_u.netloc))
            heads = [head] + [k for k, v in _ABBREV.items() if v == head]
            if head and head not in start:
                if re.search(rf"\b{re.escape(head)}\b", here_url):
                    return _decision("DONE", None, None, "goal_reached")
                for h in heads[1:]:
                    if re.search(rf"\b{re.escape(h)}\b", _host_flat):
                        return _decision("DONE", None, None, "goal_reached")
    return None


def _fill_values(goal: str) -> list[str]:
    """goal 里处于「值位置」的引号串：`fill X with 'v'` / `enter 'v' into X`。

    与 _phrases 互补——那里刻意把这类串跳过（值不是目标），但对"是否已完成"
    而言，用户要求填进去的值出现在页面上恰恰是最强的完成证据。
    只认 "with/into/to" 紧邻的引号串，避免把 'Ada Lovelace' 这类目标名误当值。
    """
    out = []
    for m in re.finditer(r"['\"]([^'\"]{2,60})['\"]", goal or ""):
        pre = (goal or "")[max(0, m.start() - 12):m.start()].lower()
        # 值可能在介词**之后**（"fill X with 'v'"）也可能**之前**
        #（"Write 'v' into X"）—— 与 _fill_pairs 同一个理由，两个方向都要认。
        if re.search(r"\b(with|into|to)\s*$", pre):
            out.append(m.group(1))
            continue
        post = (goal or "")[m.end():m.end() + 12].lower()
        if re.match(r"\s+(with|into)\b", post):
            out.append(m.group(1))
    return out


def _phrases(goal: str) -> list[str]:
    """goal 里字面写明的目标短语：引号串 / 路径 / RFC 号 / 介词后的名词短语。"""
    out = []
    for m in re.finditer(r"['\"]([^'\"]{2,60})['\"]", goal):
        pre = goal[max(0, m.start() - 8):m.start()].lower()
        if re.search(r"\bwith\s*$", pre):     # 'Test User' 这类是"值"，不是目标
            continue
        out.append(m.group(1))
    out += [m.group(0) for m in re.finditer(r"(/[\w\-/\.]{2,40})", goal)]
    out += [m.group(0) for m in re.finditer(r"\bRFC[\s-]?\d{3,5}\b", goal, re.I)]
    # 介词后的名词短语："Open the Wikipedia article on Gödel's incompleteness theorems."
    # 三类都不命中（无引号、无路径、无 RFC）→ _phrases 曾返回 []，于是 goal_reached
    # 永远不产 DONE，只能由模型提议 DONE 再交 decider 复核（每次 5.7s 且形成提议循环，
    # wiki-laya-v4 实况 22 次哨兵调用 / 229s）。以句号/分号收尾，避免跨句误取。
    m2 = re.search(r"\b(?:on|about|titled|called|named)\s+([^.;]+?)\s*\.?\s*$",
                   goal, re.I)
    if m2:
        out.append(m2.group(1).strip())
    # 去重必须忽略"引号"：s002 的 goal "...to find the page about 'asyncio'." 会同时产出
    # 引号串 "asyncio" 与介词短语 "'asyncio'" 两条 → search_type 的兜底判据"goal 里有唯一
    # 显式 token"（len(cand)==1）直接失效 → 没有任何技能命中 → 全靠模型（s002 实况）。
    # 返回前统一剥掉引号：消费方（explicit_target / goal_reached）比对的是页面文本，
    # 页面文本里不会带引号。
    seen: set[str] = set()
    uniq: list[str] = []
    for p in out:
        p = p.strip().strip("'\"")
        key = p.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        uniq.append(p)
    return uniq


def explicit_target(page: dict, goal: str, history: list) -> dict | None:
    phrases = _phrases(goal)
    if not phrases:
        return None
    recent = {h.get("choice") for h in (history or [])[-4:]}
    scored = []
    for index, a in _indexed(page.get("actions") or []):
        if a.get("kind") != "click" or a.get("id") in recent:
            continue
        # 自动补全建议（role=option）是"改查询词"，不是导航目标：s001 里 goal 的引号串
        # "OpenAI" 与建议项 "openai" 逐字相同 → 精确匹配 2.0 → 点了建议 → 只是把查询
        # 重打一遍，永远到不了官网。目标页一定是链接，建议项不是。
        if (a.get("role") or "") == "option":
            continue
        lab = (a.get("label") or "").strip().lower()
        if not lab:
            continue
        lab_n = " ".join(_tokens(lab))
        lab_c, lab_t = _content(lab), set(_tokens(lab))
        # 链接地址的 host（快照新增 href / site 字段）：结果页里目标词会出现在**多条**
        # 标题里，只有域名能区分"官方站点"——"Search for 'OpenAI' and open the official
        # OpenAI website" 只看 label 会点到任意一条新闻结果（s001 实况）。
        # site 是结果卡片的 <cite>（"https://openai.com"）。Google 新版结果链接是
        # /goto?url=CAES… 不透明编码，解不出真实地址，所以 site 优先、href 兜底。
        _href = a.get("href") or ""
        _site = a.get("site") or ""
        host = ""
        try:
            if _site:
                # cite 可能是 "https://en.wikipedia.org › wiki › OpenAI"（Google 用 › 分隔
                # 面包屑）——只取域名那一段。否则整串被当成 netloc，"openai" 命中 →
                # 维基条目被误判成"官方站点"，与主结果同分 → 回落模型（s001 实况）。
                _site_head = re.split(r"[\s\u203a\u00bb>]+", _site.strip())[0]
                host = _urlparse(
                    _site_head if "://" in _site_head else "https://" + _site_head).netloc.lower()
            elif _href:
                # 旧式重定向：/url?q=https://openai.com/… —— host 必须从 q=/url= 参数里取
                _hm = re.search(r"[?&](?:q|url)=([^&]+)", _href)
                if _hm:
                    from urllib.parse import unquote as _unq
                    _href = _unq(_hm.group(1))
                host = _urlparse(_href).netloc.lower()
        except Exception:
            host = ""
        host_flat = host.replace("-", "").replace(".", "").removeprefix("www")
        best = 0.0
        for p in phrases:
            pn = " ".join(_tokens(p))
            if not pn:
                continue
            # 域名命中 = "这是对的站点"；label 命中 = "这是站点里对的那一页"。两者必须
            # **叠加**：同一站点会有多条链接（主结果 + 该站点的子链接共用同一个 cite），
            # 只按域名打分会全部同分 → "明显优势"判据不成立 → 直接回落模型
            # （s001 实况：openai.com 的主结果和子链接并列 3.0 → None）。
            host_hit = bool(host_flat and pn.replace(" ", "") and pn.replace(" ", "") in host_flat)
            label_score = 0.0
            if lab_n == pn:
                # 精确匹配（如结果标题与 goal 引号串逐字相同）显著高于"包含"
                label_score = 2.0 + min(len(pn), 40) / 1000.0
            elif pn in lab_n:
                label_score = 1.0 + min(len(pn), 40) / 1000.0
            elif p.startswith("/"):
                # 路径类短语（/forms/post）必须"整段出现在 label 里"——
                # 反向包含会让 "/post" 命中 "/forms/post"（f001 实况：点错到 /post）
                label_score = 0.0
            elif len(lab_n) >= 4 and lab_n in pn:
                label_score = 0.9
            else:
                pc = _content(p)
                if pc:
                    ratio = sum(1 for t in pc if t in lab_t) / len(pc)
                    if ratio >= 0.75:
                        label_score = 0.75 + ratio / 10
            if host_hit:
                best = max(best, 3.0 + label_score)
            elif label_score:
                best = max(best, label_score)
        if best > 0:
            scored.append((best, index, a))
    if not scored:
        return None
    scored.sort(key=lambda x: (-x[0], x[1]))
    top = scored[0]
    second = scored[1][0] if len(scored) > 1 else 0.0
    if top[0] < 0.75 or top[0] - second < 0.15:   # 强信号 + 明确优势，否则回落模型
        return None
    return _decision("CLICK", top[1], top[2], "explicit_target")


# ---------------------------------------------------------------------------
# 2b. goal 明写路径 -> 点 href 路径相同的链接
# ---------------------------------------------------------------------------

# "Go to /forms/post and fill the customer name field with 'Test User'."
# 起始页由 domain 解析成 https://httpbin.org/，目标是 /forms/post。首页确实挂着
# 那个链接，但 explicit_target 的路径分支被刻意归零（"/post" 反向包含 "/forms/post"，
# f001 曾因此点错到 /post）→ 该技能返回 None → 回落模型 → 模型点了页脚的
# "the developer - Website"（f001 实况，steps=1 即止）。
#
# 这里改用 **href 路径精确相等**：反向包含无从发生——"/post" 永远不等于
# "/forms/post"，所以不需要归零。href 是抓取器给出的真实地址，比 label 可信
# （label 会是 "forms/post" / "Post a form" / "POST" 各页面各样）。
_PATH_RE = re.compile(r"(?<![\w\-])(/[A-Za-z0-9._~\-/]{2,60})")

#: 找不到同名链接时最多向下滚几次。4 次 × 560px ≈ 2240px，够覆盖 Swagger UI
#: 这类接口列表的深度；再深就该由模型接管而不是无脑滚。
_PATH_SCROLL_MAX = 4


def _norm_path(p: str) -> str:
    """路径归一：去查询/片段、去重复斜杠、去尾斜杠、小写。"""
    p = (p or "").strip().split("#", 1)[0].split("?", 1)[0]
    if not p.startswith("/"):
        p = "/" + p
    p = re.sub(r"/{2,}", "/", p)
    if len(p) > 1:
        p = p.rstrip("/")
    return p.lower()


def goto_path(page: dict, goal: str, history: list) -> dict | None:
    """goal 里明写的路径 + 页面上唯一同路径链接 → 点它。判据必须是**唯一命中**：
    页面上有两个 /post（导航栏 + 页脚）时宁可回落模型，也不赌。"""
    wanted = {_norm_path(m.group(1)) for m in _PATH_RE.finditer(goal or "")}
    wanted.discard("/")
    if not wanted:
        return None

    # 已经在目标路径上 → 不该再点，交给 goal_reached 收口
    try:
        here = _norm_path(_urlparse(page.get("url") or "").path)
    except Exception:
        here = ""
    if here in wanted:
        return None

    recent = {h.get("choice") for h in (history or [])[-3:]}
    hits = []
    for index, a in _indexed(page.get("actions") or []):
        if a.get("kind") != "click" or a.get("id") in recent:
            continue
        if (a.get("role") or "") == "option":
            continue
        href = a.get("href") or ""
        if not href:
            continue
        try:
            ap = _norm_path(_urlparse(href).path)
        except Exception:
            continue
        if ap in wanted:
            hits.append((index, a))
    if len(hits) == 1:          # 唯一命中 → 点它
        return _decision("CLICK", hits[0][0], hits[0][1], "goto_path")
    if hits:                    # >1 个 → 有歧义，回落模型（宁可 None 不赌）
        return None
    # 没有同名链接，但 goal 确实写了路径 → 目标多半在**折叠线以下**。
    # snapshot.js:157 只在下方确有内容时才合成 scroll_down，所以拿得到控件就等于
    # "还有东西没看见"，这个守卫是免费的（f001/f002 实况：/forms/post 在 y=1174，
    # 视口剔除后快照里根本没有该链接 → 之前只能回落模型点页脚 → steps=1 即止）。
    # 有界：最多 _PATH_SCROLL_MAX 次，防止无止境地滚。
    if sum(1 for h in (history or []) if h.get("kind") == "scroll") < _PATH_SCROLL_MAX:
        ctl = _scroll_ctl(page, "down")
        if ctl:
            return _decision("SCROLL_DOWN", None, ctl, "goto_path")
    return None


# ---------------------------------------------------------------------------
# 3. 按 label 填表 → TYPE_TEXT
# ---------------------------------------------------------------------------

# goal 里可能有多对 <字段> '<值>'：
#   "Fill the contact form with name 'Test User', email 'test@example.com', comment 'hello', and submit."
# 旧写法只认 "fill … with '<值>'" 一种句式、且只取第一对 → 多字段表单只填一个就提交
# （f005/f006/f007/f009 实况：只填 email → 页面不出现 "Thank you" → 整轮失败）。
#
# 字段名可能在值的**前面**（"fill the comments field with 'hello world'"）或**后面**
# （"Write 'hello world' into the comments field"），中间的 with/into/the/field 是脚手架。
# 所以对每个引号值先向前找最近的内容词，找不到再向后找。
_FIELD_STOP = {"with", "to", "into", "for", "and", "then", "as", "the", "a", "an",
               "field", "fields", "input", "box", "value", "values", "of", "in", "on"}
_FIELD_VERBS = {"fill", "fills", "write", "enter", "type", "put", "set", "provide",
                "give", "use", "submit", "press", "click"}
_FILL_VERB_RE = re.compile(r"\b(fill|write|enter|type|put|set)\b", re.I)
_WORD_RE = re.compile(r"[A-Za-z][\w'\-]*")
_QUOTED_RE = re.compile(r"['\"]([^'\"]{1,60})['\"]")


def _fill_pairs(goal: str) -> list[tuple[str, str]]:
    """goal 里所有 <字段> '<值>' 对，按出现顺序去重。

    只在 goal 出现"填"类动词时才认 —— 否则 "Open the article on 'Gödel's theorems'"
    这种导航目标里的引号串会被当成一对，凭空去填一个叫 "article" 的字段。
    """
    text = goal or ""
    if not _FILL_VERB_RE.search(text):
        return []
    words = [(m.start(), m.group(0)) for m in _WORD_RE.finditer(text)]
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for m in _QUOTED_RE.finditer(text):
        before = [w for pos, w in words if pos < m.start()]
        after = [w for pos, w in words if pos > m.end()]
        field = ""
        for w in reversed(before):
            lw = w.lower()
            if lw in _FIELD_STOP or lw in _FIELD_VERBS:
                continue
            field = w
            break
        if not field:
            for w in after:
                lw = w.lower()
                if lw in _FIELD_STOP or lw in _FIELD_VERBS:
                    continue
                field = w
                break
        key = field.lower()
        if field and key not in seen:
            seen.add(key)
            out.append((field, m.group(1)))
    return out


def _field_hit(field_c: set[str], cand: set[str]) -> bool:
    """字段名命中：完全相等，或长度 ≥4 时一方是另一方的前缀（comment ↔ comments）。

    多词字段名要求**全部**命中：不能只凭 "instructions" 命中 "delivery instructions"。
    """
    if not field_c or not cand:
        return False
    for a in field_c:
        if not any(a == b or (len(a) >= 4 and len(b) >= 4
                              and (a.startswith(b) or b.startswith(a))) for b in cand):
            return False
    return True


def form_fill(page: dict, goal: str, history: list) -> dict | None:
    hist = history or []
    done = {(h.get("choice"), h.get("text")) for h in hist}
    filled_values = {(h.get("text") or "").strip() for h in hist if h.get("kind") == "fill"}
    actions = page.get("actions") or []
    pairs = _fill_pairs(goal or "")
    if not pairs:
        # "Fill all three fields (name, email, comments) with any values and submit." ——
        # goal 没给具体值，断言也只要求提交成功（页面出现确认字样）。把所有**空**文本框
        # 依次填上占位值即可（f007 实况：旧写法直接 None → 模型只填一个 → 提交后无确认）。
        if re.search(r"\bfill\b[^.;]*\ball\b[^.;]*\bfields?\b", goal or "", re.I):
            for index, a in _indexed(actions):
                if a.get("kind") != "fill" or (a.get("value") or "").strip():
                    continue
                label = ((a.get("label") or "") + " " + (a.get("name") or "")).lower()
                # email 字段必须填**合法邮箱**：填 "test" 会被 HTML5 校验拦下，
                # 表单根本不提交（f007 实况：三字段都填 "test" → 点 Submit 页面毫无反应
                # → 确认页永不出现 → FAIL。空表单反而能提交，所以只有"填过"才暴露）。
                value = "test@example.com" if "email" in label else "test"
                if (a.get("id"), value) in done:
                    continue
                return _decision("TYPE_TEXT", index, a, "form_fill", text=value)
        return None
    for field, value in pairs:
        if value.strip() in filled_values:
            continue                       # 这一对已经填过 → 下一对
        field_c = set(_content(field))
        if not field_c:
            continue
        best = None
        for index, a in _indexed(actions):
            if a.get("kind") != "fill":
                continue
            lab_t = set(_tokens(a.get("label") or ""))
            # name 属性也算字段名：httpbin 的 comments 字段可见标签是 "Delivery instructions:"，
            # 而 goal 说 "the comments field" —— 只有 name="comments" 能对上（f002 实况）。
            # 命中判据含单复数（comment ↔ Comments），否则 f005/f009 的 "comment 'hello'"
            # 永远匹配不到标签是 "Comments" 的字段 → 少填一个 → 提交后无确认字样。
            name_hit = _field_hit(field_c, set(_tokens(a.get("name") or "")))
            if not name_hit and not _field_hit(field_c, lab_t):
                continue
            if str(a.get("value") or "").strip() == value:
                continue                   # 已是该值 → 不重复
            if (a.get("id"), value) in done:
                continue
            score = 1.0 if name_hit else 0.9
            if best is None or score > best[0]:
                best = (score, index, a)
        if best is not None and best[0] >= 0.5:
            return _decision("TYPE_TEXT", best[1], best[2], "form_fill", text=value)
    return None


# ---------------------------------------------------------------------------
# 4. 提交表单 → CLICK
# ---------------------------------------------------------------------------

_CHOOSE_RE = re.compile(
    r"\b(select|choose|pick|check|tick)\s+(?:a|an|the|one)?\s*"
    r"([\w][\w \-]{1,24}?)\s*(?:\bfrom\b|\bon\b|\bin\b|\bof\b|\bfor\b|[,.]|$)", re.I)


def _norm_sel(s: str) -> str:
    return " ".join(_tokens(s or "")).lower()


def select_option(page: dict, goal: str, history: list) -> dict | None:
    """目标要求「选一个 X」而 X 是单选/复选框组，且还没选 → 点一个。

    select_first 只处理 <select> 下拉；httpbin 的 pizza size 是 radio 组
    （name="size"，选项标签是 Small/Medium/Large），此前**没有任何技能**能表达
    「选一个 size」。于是 form_submit 只看「动过一次」就提交 —— f004 实况：
    goal "select a size from the dropdown, then submit the form"，走完 goto_path
    就直接提交，目标要求的选项从未发生，断言失败。

    判据（都在快照里：snapshot.js 把 name 属性与 radio/checkbox 的 checked 都带出来）：
      · 目标里的选择对象先按**选项标签**匹配（"choose Medium"），
        否则按**控件组名**匹配（"select a size" → name="size"）
      · 组内已有 checked=="true" → 前置已满足，放行给 form_submit
      · 组名命中多个不同控件 → 有歧义，回落模型
    """
    m = _CHOOSE_RE.search(goal or "")
    if not m:
        return None
    noun = _norm_sel(m.group(2))
    if not noun or len(noun) < 2:
        return None

    opts, groups = [], {}
    for index, a in _indexed(page.get("actions") or []):
        if a.get("kind") != "click":
            continue
        if "checked" not in a and (a.get("role") or "") not in ("radio", "checkbox"):
            continue                                   # 只管 radio/checkbox 组
        opts.append((index, a))
        groups.setdefault(_norm_sel(a.get("name") or ""), []).append((index, a))
    if not opts:
        return None

    recent = {h.get("choice") for h in (history or [])[-2:]}

    # 1) 目标直接点名某个选项（"choose Medium"）
    by_label = [(i, a) for i, a in opts if _norm_sel(a.get("label") or "") == noun]
    if len(by_label) == 1:
        i, a = by_label[0]
        if i in recent or str(a.get("checked")).lower() == "true":
            return None
        return _decision("CLICK", i, a, "select_option")

    # 2) 目标点名控件组（"select a size" → name="size"）：取第一个未选中的
    hit = [g for name, g in groups.items() if name and (name == noun or noun in name)]
    if len(hit) != 1:                 # 0 个=没有；>1 个=有歧义，回落模型
        return None
    group = hit[0]
    if any(str(a.get("checked")).lower() == "true" for _, a in group):
        return None                   # 已经选过了 → 前置满足，让 form_submit 收口
    for i, a in group:
        if i not in recent:
            return _decision("CLICK", i, a, "select_option")
    return None


def form_submit(page: dict, goal: str, history: list) -> dict | None:
    # 闸门不能只认 "submit"：t003/t005 的 goal 是 "…then press **Save**"，
    # 旧写法直接 return None → 保存按钮永不点 → 页面不出现 "Settings saved" → FAIL。
    if not re.search(r"\b(submit|save|apply|confirm|update)\b", goal or "", re.I):
        return None
    hist = history or []
    # 只在"最后一次提交之后又动过表单"时提交（防重复点击提交按钮）。
    # "动过"必须包括**切换控件**：t003/t005 是"勾选复选框 → 按 Save"，全程没有 fill，
    # 旧写法要求必须先 fill → 保存按钮永不点（t003/t005 实况：一步动作后就卡住）。
    last_act = max((i for i, h in enumerate(hist) if h.get("kind") != "wait"), default=-1)
    if last_act < 0:
        return None                        # 一步没走 → 不提交（防误触发）
    last_submit = max(
        (i for i, h in enumerate(hist)
         if h.get("kind") == "click" and (set(_tokens(h.get("action") or "")) & SUBMIT_WORDS)),
        default=-1,
    )
    if last_submit >= last_act:
        return None                        # 最后一次动作就是提交 → 不再点（防重复提交）
    # 提交控件是 button（<button> / <input type=submit> 都是 role=button），导航项是 link。
    # 按 label 词匹配会先撞上导航栏的 "Search" 链接（自建站点 <a href="search.html">Search</a>
    # 实况：form_submit 点了它 → 离开表单页 → 表单丢失 → FAIL）。所以按钮优先，链接仅兜底。
    best = None
    for index, a in _indexed(page.get("actions") or []):
        if a.get("kind") != "click":
            continue
        # 非 http(s) 目标永远不可能是表单提交。SUBMIT_WORDS 含 "send"，
        # 于是 httpbin 首页的 "Send email to the developer"（mailto: 链接）
        # 被当成交付按钮连点 3 次（f001 实况：steps=1，点到页脚后 correct_abandon）。
        # 与其不断扩充 SUBMIT_WORDS，不如按协议排除——这条判据是封闭的。
        _h = (a.get("href") or "").strip().lower()
        if _h and not (_h.startswith("http") or _h.startswith("/")):
            continue
        lab_n = " ".join(_tokens(a.get("label") or ""))
        if not lab_n or lab_n.startswith("open"):
            continue                       # 开合开关（"Open ..."）不是提交
        if not (set(lab_n.split()) & SUBMIT_WORDS):
            continue
        is_button = (a.get("role") or "") == "button"
        if best is None or (is_button and not best[0]):
            best = (is_button, index, a)
        if is_button:
            break                          # 按钮命中即可返回
    if best is not None:
        return _decision("CLICK", best[1], best[2], "form_submit")
    return None


# ---------------------------------------------------------------------------
# 5. 往搜索框输入 → TYPE_TEXT（"type 'X' into the search box" / "Search <site> for 'X'"）
# ---------------------------------------------------------------------------

_TYPE_RE = re.compile(r"type\s+['\"](?P<q>[^'\"]{1,60})['\"]\s+(?:in|into)\s+the\s+search\s*box", re.I)
_SEARCH_RE = re.compile(r"search\s+(?:\S+\s+)?for\s+['\"](?P<q>[^'\"]{1,60})['\"]", re.I)


_SEARCHBOX_RE = re.compile(
    r"search|query|find|lookup|\bq\b|搜索|查找|检索|查询", re.I)


def _searchbox(a: dict) -> bool:
    """搜索框判定：只看 label 语义（含中文"搜索/查找"）。

    刻意不看 role：combobox 太泛（航班 "Where from?"、日期框都是 combobox），
    按 role 认会把目标字段误当搜索框（Flights 实况）。
    """
    return bool(_SEARCHBOX_RE.search(a.get("label") or ""))


def search_type(page: dict, goal: str, history: list) -> dict | None:
    m = _TYPE_RE.search(goal or "") or _SEARCH_RE.search(goal or "")

    query = m.group("q") if m else None
    if not query:
        # 兜底：goal 里有唯一显式 token（RFC 号 / 引号串，非路径）→ 当作查询词。
        # 但 goal 主句是"打开某物"时不算滚动任务（l002 "Open the Wikipedia
        # 'List of countries by population' article and scroll to the table."
        # 主句是 Open，scroll 是次要；l003 "scroll to find a job mentioning
        # 'remote'" 才是滚动任务）。
        if (re.search(r"\bscroll\b", goal or "", re.I)
                and not re.search(r"\bopen\b", goal or "", re.I)):
            return None
        cand = [p for p in _phrases(goal or "") if not p.startswith("/")]
        if len(cand) == 1:
            query = cand[0]
    if not query:
        return None
    hist = history or []
    done = {(h.get("choice"), h.get("text")) for h in hist}
    # 同一 query 本任务内已输入过 → 不再输入（结果页常又有一个空搜索框，
    # 否则会把 query 重打一遍而不去点结果：n004 实况）
    if any(h.get("kind") == "fill" and (h.get("text") or "").strip() == query for h in hist):
        return None
    for index, a in _indexed(page.get("actions") or []):
        if a.get("kind") != "fill" or not _searchbox(a):
            continue
        if (a.get("value") or "").strip() == query or (a.get("id"), query) in done:
            continue                       # 该框已是该值 → 不重复
        return _decision("TYPE_TEXT", index, a, "search_type", text=query)
    return None

# ---------------------------------------------------------------------------
# 5b. 搜索提交：刚往搜索框输入过 → 点搜索/Go 按钮（把"输入→提交"串成一步）
# ---------------------------------------------------------------------------

def search_submit(page: dict, goal: str, history: list) -> dict | None:
    # 机票搜索页：字段填完后点 "Search for flights" 提交。
    # 上次填的未必是搜索框（Where from?/Where to?/Departure），故单列一条：
    # 目标提到 flights + 页面已有 ≥2 个填好的字段 + 存在 Search…flight 按钮。
    if re.search(r"\bflights?\b", goal or "", re.I):
        done = {h.get("choice") for h in (history or [])}
        filled = sum(1 for a in (page.get("actions") or [])
                     if a.get("kind") == "fill" and (a.get("value") or "").strip())
        if filled >= 2:
            # 缺陷#36：goal 指定了日期时，日期字段必须已经是那天才允许提交。
            # v121 实况：日历点成了 "Thursday, October 22"（目标是 10/21），技能照样
            # 提交 → 结果页不是目标那天，此后无论等多久、重载多少次都拿不到目标结果
            # （整轮 6/7）。宁可交回 date_pick 继续修日期，也不提交错表单。
            dm = _DATE_RE.search(goal or "")
            if dm:
                want_m, want_d = dm.group(1).lower(), int(dm.group(2))
                vals = " ".join((a.get("value") or "").lower()
                                for a in (page.get("actions") or [])
                                if a.get("kind") == "fill"
                                and _DATE_FIELD_RE.search(a.get("label") or ""))
                if not (want_m[:3] in vals and re.search(rf"\b{want_d}\b", vals)):
                    return None
            for index, a in _indexed(page.get("actions") or []):
                if a.get("kind") != "click" or a.get("id") in done:
                    continue
                lab = (a.get("label") or "").strip().lower()
                # 缺陷#33："Search" 与 "Search for flights" 都要接受 —— 字段填好后
                # Google 会把按钮文案缩成 "Search"（v57/v58 实况：技能错过，模型接手
                # 点了 "Search"，每次 3~5s）。filled>=2 的守卫已保证这是提交而非搜索框。
                # 裸 "Search" 只在日期也填好（filled>=3）时才认：避免 from/to 刚填完
                # 就提前提交（长文案 "Search for flights" 沿用原判据 filled>=2）。
                if re.match(r"^search\b", lab) and ("flight" in lab or filled >= 3):
                    return _decision("CLICK", index, a, "search_submit")

    hist = history or []
    fills = [i for i, h in enumerate(hist) if h.get("kind") == "fill"]
    if not fills:
        return None
    last_fill = fills[-1]
    # 用 _searchbox 判"上次填的是不是搜索框"：它认得中文"搜索/查找/查询"。
    # 这里原来只写英文关键词，Google 中文界面的搜索框 label 是"搜索" → 守卫失败 →
    # 整个 search_submit 直接返回 None，填完永远不提交（s001 实况）。
    if not _searchbox({"label": hist[last_fill].get("action") or ""}):
        return None
    last_sub = max(
        (i for i, h in enumerate(hist)
         if h.get("kind") == "click"
         and (set(_tokens(h.get("action") or "")) & {"search", "go", "submit"})),
        default=-1,
    )
    if last_sub > last_fill:
        return None                        # 已提交且此后未再输入 → 不再提交
    # 与 form_submit 同理：提交控件是 button，导航项是 link。自建站点的导航栏就有
    # <a href="search.html">Search</a>，先撞上它会直接离开当前页（实况）。
    cands = {"b_exact": None, "b_loose": None, "l_exact": None, "l_loose": None}
    for index, a in _indexed(page.get("actions") or []):
        if a.get("kind") != "click":
            continue
        lab = " ".join(_tokens(a.get("label") or ""))
        if not lab or lab.startswith("open"):
            continue                       # "Open quick search" 之类是开合开关，不是提交
        toks = set(lab.split())
        if not (toks & {"search", "go", "submit", "send"}):
            continue
        key = ("b" if (a.get("role") or "") == "button" else "l") + (
            "_exact" if lab in {"search", "go", "submit", "send"} else "_loose")
        if cands[key] is None:
            cands[key] = (index, a)
    pick = cands["b_exact"] or cands["b_loose"] or cands["l_exact"] or cands["l_loose"]
    if pick is not None:
        return _decision("CLICK", pick[0], pick[1], "search_submit")
    # 没有提交按钮时，自动补全建议本身就是"提交"：Google 首页的搜索框是 combobox，
    # 页面里没有 "Google Search" 按钮（实测 actions 里根本没有），把查询交出去的唯一
    # 方式就是点一条建议 —— 点了它才会真的发起搜索。这与 explicit_target 的取舍相反：
    # 那里 option 是"改查询词"所以要跳过，这里 option 正是"把查询交出去"。
    # 优先选与刚输入内容最接近的那条，避免把 "openai api" 当成查询提交。
    typed = _norm_label(hist[last_fill].get("text") or "")
    best_opt = None
    for index, a in _indexed(page.get("actions") or []):
        if a.get("kind") != "click" or (a.get("role") or "") != "option":
            continue
        lab = _norm_label(a.get("label") or "")
        if not lab:
            continue
        score = 2 if (typed and lab == typed) else 1 if (typed and lab.startswith(typed)) else 0
        if best_opt is None or score > best_opt[0]:
            best_opt = (score, index, a)
        if score == 2:
            break
    if best_opt is not None:
        return _decision("CLICK", best_opt[1], best_opt[2], "search_submit")
    return None


# ---------------------------------------------------------------------------
# 6. 下拉/单选：goal 要求 select，但未指定具体项 → 取首个可用项
# ---------------------------------------------------------------------------

_SELECT_NEG_RE = re.compile(
    r"\b(?:do\s+not|don'?t|never|without|avoid)\b[^.]{0,40}?\bselect", re.I)


def select_first(page: dict, goal: str, history: list) -> dict | None:
    if not re.search(r"\bselect\b", goal or "", re.I):
        return None
    # 缺陷#17：goal 里的 "Do not select or book a flight" 是否定指令，不是任务要求。
    # 不排除时本技能会在建议列表上反复点 checkbox（Flights 实况：i8~i23 连点 12 次）。
    if _SELECT_NEG_RE.search(goal or ""):
        return None
    hist = history or []
    recent = {h.get("choice") for h in hist[-4:]}
    done_labels = {_norm_label(h.get("action")) for h in hist}
    for index, a in _indexed(page.get("actions") or []):
        if a.get("id") in recent:
            continue
        if a.get("kind") == "select":
            return _decision("SELECT", f"{index}:1", a, "select_first")
    for index, a in _indexed(page.get("actions") or []):
        if a.get("id") in recent:
            continue
        if a.get("kind") != "click" or not re.search(r"radio|checkbox", a.get("role") or "", re.I):
            continue
        lab = _norm_label(a.get("label"))
        if any(w in lab for w in ("else", "multiple", "nearby", "toggle")):
            continue                      # 展开/多选诱饵不是可选项
        if lab in done_labels:
            continue                      # 同一项已点过 → 不重复（id 每轮重排，靠 label 去重）
        return _decision("CLICK", index, a, "select_first")
    return None


# ---------------------------------------------------------------------------
# 7. 目标实体 → 表单字段（"from X to Y" 类）：出发地/目的地逐字段填
# ---------------------------------------------------------------------------

_FROM_TO = re.compile(
    r"\bfrom\s+(?P<o>[A-Za-zÀ-ÿ'’\-\. ]+?)\s+to\s+(?P<d>[A-Za-zÀ-ÿ'’\-\. ]+?)"
    r"(?=\s+on\b|,|\s+for\b|\s+in\b|$)",
    re.I,
)
# 字段语义 → label 判据。刻意排除 "Where else?"（多机场展开项，
# Flights 实况：模型误把它当目标字段）。
_FIELD_PATTERNS = (
    ("origin", r"where from|leaving from|\bfrom\b|origin|departure airport"),
    ("destination", r"where to|going to|\bto\b|destination|arrival airport"),
)


def entity_fill(page: dict, goal: str, history: list) -> dict | None:
    m = _FROM_TO.search(goal or "")
    if not m:
        return None
    values = {"origin": m.group("o").strip(), "destination": m.group("d").strip()}
    if not all(values.values()):
        return None
    hist = history or []
    # 缺陷#29：上一字段刚填完、建议项还没确认时不要抢着填下一个字段——
    # 否则出发地只填不确认（Google 要求从建议列表里选一项才算设定），
    # Flights v28 实况：step1 填出发地 → step2 直接填目的地，出发地始终没确认。
    last = _last_real(hist)
    if last.get("kind") == "fill" and any(
            re.search(pat, last.get("action") or "", re.I) for _, pat in _FIELD_PATTERNS):
        return None
    typed = {(h.get("choice"), (h.get("text") or "").strip()) for h in hist}
    for key, pat in _FIELD_PATTERNS:
        val = values[key]
        if any((h.get("text") or "").strip() == val for h in hist):
            continue                       # 该值已输入过
        for index, a in _indexed(page.get("actions") or []):
            if a.get("kind") != "fill":
                continue
            lab = a.get("label") or ""
            if "else" in lab.lower():      # "Where else?" 是多机场展开项，不是目标字段
                continue
            if not re.search(pat, lab, re.I):
                continue
            if (a.get("value") or "").strip() == val or (a.get("id"), val) in typed:
                continue
            return _decision("TYPE_TEXT", index, a, "entity_fill", text=val)
    return None


# ---------------------------------------------------------------------------
# 7b. 自动补全确认：刚填完 from/to 字段 → 点第一条建议
#     （Flights 实况：模型在建议列表里选了 "Open Where else?" 展开项，
#       出发地始终没被确认。技能层直接接管这一步。）
# ---------------------------------------------------------------------------

def _norm_label(s: str) -> str:
    return (s or "").lower().translate(str.maketrans("üöäéèç", "uoaeec"))


def entity_confirm(page: dict, goal: str, history: list) -> dict | None:
    if not _FROM_TO.search(goal or ""):
        return None
    hist = history or []
    if not hist:
        return None
    last = _last_real(hist)
    if last.get("kind") != "fill":
        return None
    if not any(re.search(pat, last.get("action") or "", re.I)
               for _, pat in _FIELD_PATTERNS):
        return None
    typed = _norm_label((last.get("text") or "").strip())
    if not typed:
        return None
    token = typed.split()[0]
    # 缺陷#34：去重必须用 (id, label) 对，不能只看 id —— snapshot 的 element id 每次
    # 观测重排，出发地确认点过的 "e4" 会和目的地城市候选的新 id 撞上，于是城市候选
    # 被当成"已点过"跳过 → 退回机场候选或让位模型（实测 3 次 decider 调用之一）。
    clicked = {(h.get("choice"), h.get("action")) for h in hist}
    # 该字段的建议已确认过（id 每轮重排，靠 label 判重）→ 不再重复点
    if any(h.get("kind") == "click" and token in _norm_label(h.get("action")) for h in hist):
        return None
    # 缺陷#28：Google 的建议列表同时含"城市"和"机场"两类，模型/首个命中会选到
    # 机场（Flights v27 实况：目的地被确认为 "London Stansted Airport (STN)"，
    # 而校验要的是城市 "London"）。同一 token 下优先不带 airport/(XXX) 的候选。
    first_any = None
    for index, a in _indexed(page.get("actions") or []):
        if a.get("kind") != "click" or (a.get("id"), a.get("label")) in clicked:
            continue
        label = a.get("label") or ""
        low = _norm_label(label)
        if any(w in low for w in ("else", "multiple", "nearby", "toggle")):  # 展开/多选诱饵
            continue
        if not (token and token in low):
            continue
        if first_any is None:
            first_any = (index, a)
        if "airport" not in low and not re.search(r"\([A-Z]{3}\)", label):
            return _decision("CLICK", index, a, "entity_confirm")   # 城市级优先
    if first_any is not None:
        # 缺陷#28b：此刻只看到机场级候选 → **不点**，保留输入框里的城市名。
        # 依据：校验要的是 "Where to?" == "London"（城市）；点机场会把它变成
        # "London Stansted Airport (STN)"（Flights v29/v34/v35 实况：等满 5 拍
        # 仍只有机场候选，点了就挂）。只填不点时字段值就是 "London"（v30/v31 实测
        # destination: true），搜索照样出结果。
        # 出发地不受影响：那里的目标值带变音符（"Zürich"），必须靠点击建议项归一化，
        # 而 Google 对城市字段总会给城市级候选。
        # 上限维持 5 拍（~2.5s）：v59 实测把它提到 12 拍后，城市候选**始终没出现**
        # 的那轮白等 6s，随后模型接手把 "Where to?" 重填一遍，整轮退化（39 步 / 1-of-7）。
        # 等到就赚一次 decider 调用，等不到就早让位——不值得为前者付后者的代价。
        if _can_wait(hist, 10):
            return _wait("entity_confirm")
        return None
    # 建议列表还没渲染出来 → 等一拍（缺陷#26），别让位给模型瞎点。
    # 预算 6 拍（~3s）：落地页首次填出发地时，Google 的 combobox 下拉有时要 3 拍以上
    # 才渲染（flights 实测：第 1 次观测还是落地页 actions=[Main menu/Flights/Hotels…]，
    # 第 4 拍才出 "Zürich, Switzerland"）。3 拍会在这里让位给 trip_type → 点"Change
    # ticket type" → 下拉关闭 → 整轮退化。注意这与下面"只看到机场候选"的 10 拍是两回事：
    # 那条是下拉已渲染但不给城市候选，等下去是浪费（v59 实测），所以不合并。
    if _can_wait(hist, 6):
        return _wait("entity_confirm")
    return None



# ---------------------------------------------------------------------------
# 8. 日期选择器：goal 里的日期 → 打开日期字段 → 点日历里对应的那一天
# ---------------------------------------------------------------------------

_MONTHS = ("january february march april may june july august september "
           "october november december").split()
_DATE_RE = re.compile(
    r"\b(" + "|".join(_MONTHS) + r")\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(\d{4}))?\b",
    re.I,
)
# 词边界：原 `depart` 会命中表单级按钮 "Done. Search for one-way flights,
# **departing** on …"，于是 date_pick 把"刚点了 Done"误判成"刚点过日期字段"
# （last_clicked_date_field=True）→ 以为日历还开着 → 重开选择器。
# Flights v128/v129/v130 实况：每轮都多一次 "Open Departure" + 其后数拍等待。
_DATE_FIELD_RE = re.compile(r"\bdeparture\b|\bdepart\b|\bdate\b|\bwhen\b", re.I)


def _scroll_count(hist: list) -> int:
    """历史里滚动动作次数（用作"最多滚几次"的上限）。"""
    return sum(1 for h in (hist or []) if "scroll" in (h.get("action") or "").lower())


def _scroll_ctl(page: dict, direction: str) -> dict | None:
    """按方向取合成滚动控件（"down"/"up"）。

    scroll 不在 KIND_TO_OP 里，_indexed 会把它滤掉，所以这里读原始 actions；
    另外 SCROLL_UP/DOWN 的 target 必须是 None（validator 拒绝带 target 的 scroll），
    因此不需要编号，直接把 action 交给 _decision 让 choice=id。
    """
    for a in (page.get("actions") or []):
        if a.get("kind") == "scroll" and direction in (a.get("label") or "").lower():
            return a
    return None


def _date_field_clicks(hist: list) -> int:
    """历史里点日期字段的次数（防止"开→关→开"打转）。"""
    return sum(1 for h in (hist or [])
               if h.get("kind") == "click"
               and _DATE_FIELD_RE.search(h.get("action") or ""))


def date_pick(page: dict, goal: str, history: list) -> dict | None:
    m = _DATE_RE.search(goal or "")
    if not m:
        return None
    month, day = m.group(1).lower(), int(m.group(2))
    hist = history or []
    # 缺陷#34：同 entity_confirm —— id 每次观测重排，跨字段撞号会把未点过的目标
    # 误判成"已点过"（日历日格/票种选项都中过这一枪）。用 (id, label) 对去重。
    clicked = {(h.get("choice"), h.get("action")) for h in hist}
    actions = list(_indexed(page.get("actions") or []))

    # 缺陷#21：日期字段已是目标日期 → 不再动它。
    # 无此守卫时，搜索提交后结果页上的 Departure 字段会让本技能再设一遍，
    # 与模型互相覆盖直到 blocked（Flights v14 实况：step 7 已提交搜索，
    # step 9~11 又把日期重设了一轮）。
    date_set = False
    for _, a in actions:
        if not _DATE_FIELD_RE.search(a.get("label") or ""):
            continue
        val = (a.get("value") or "")
        if val and month[:3] in val.lower() and re.search(rf"\b{day}\b", val):
            date_set = True
            break
    if date_set:
        # 缺陷#32：日期已设好后收起选择器。原实现额外要求页面上仍有 gridcell，
        # 但 Google 点完日格常立刻收起日历、只留一个 Done 按钮 —— 于是技能返回
        # None，这一步被交给模型（每次 2~5s 的 decider 调用；实测单轮 3 次模型
        # 调用里就有它，合计 ~4s）。改为：日期已设 + 有 Done 按钮 + 本步没点过 → 点掉。
        done_clicked = any(
            h.get("kind") == "click"
            and re.match(r"^done\b", (h.get("action") or "").strip(), re.I)
            for h in hist)
        if not done_clicked:
            for index, a in actions:
                if a.get("kind") == "click" and (a.get("id"), a.get("label")) not in clicked \
                        and re.match(r"^done\b", (a.get("label") or "").strip(), re.I):
                    return _decision("CLICK", index, a, "date_pick")
        # 日期已设但选择器仍开着 → 表单级 "Done. Search for one-way flights…" 被面板遮住
        # （实测该状态下 actions 里只有日格 + Departure 字段，没有 Done），技能返回 None
        # 就落到模型（每次 3~5s，且它常去滚动日历、把局面弄得更糟）。
        # 这里再点一次日期字段把面板收起（Google 的日期面板在这个状态下没有 Done 按钮）。
        # 限 3 次，避免"开→关→开"打转。
        if any((a.get("role") or "").lower() == "gridcell" for _, a in actions) \
                and _date_field_clicks(hist) < 3:
            for index, a in actions:
                if a.get("kind") == "click" and _DATE_FIELD_RE.search(a.get("label") or ""):
                    return _decision("CLICK", index, a, "date_pick")
        return None

    # 阶段 b：日历已展开（有 gridcell，或上一步刚点了日期字段）→ 点那一天
    cal_open = any((a.get("role") or "").lower() in {"gridcell", "option"} for _, a in actions)
    last_clicked_date_field = bool(
        re.search(_DATE_FIELD_RE, _last_real(hist).get("action") or ""))
    if cal_open or last_clicked_date_field:
        for index, a in actions:
            if a.get("kind") != "click" or (a.get("id"), a.get("label")) in clicked:
                continue
            lab = " ".join(_tokens(a.get("label") or ""))
            if not lab:
                continue
            if lab == str(day) or (month in lab and re.search(rf"\b{day}\b", lab)):
                return _decision("CLICK", index, a, "date_pick")
        # 日历开着但目标日格还没渲染出来 → 等一拍（缺陷#26）
        if _can_wait(hist):
            return _wait("date_pick")
        # 目标日在可视区外：Google 的日历一屏约两周（目标 Oct 21，初始可视 Sep 30~Oct 13）。
        # 关键：**按可见日期的早晚决定方向**，只朝下滚会滚过头（实测滚到 Nov~Dec，
        # 目标反而在视野外 → 技能再也找不到 → 回落模型，每次 3~5s 的废调用）。
        # 注意：scroll 不在 KIND_TO_OP 里，_indexed 会滤掉它，故这里用原始 actions；
        # SCROLL_UP/DOWN 的 target 必须是 None（validator 拒绝带 target 的 scroll）。
        if _scroll_count(hist) < 6:
            want = (_MONTHS.index(month) if month in _MONTHS else 0, day)
            seen = []
            for a in (page.get("actions") or []):
                m2 = _DATE_RE.search(a.get("label") or "")
                if m2 and m2.group(1).lower() in _MONTHS:
                    seen.append((_MONTHS.index(m2.group(1).lower()), int(m2.group(2))))
            if seen:
                want_key = "up" if min(seen) > want else "down"
                ctl = _scroll_ctl(page, want_key)
                if ctl is not None:
                    return _decision("SCROLL_" + want_key.upper(), None, ctl, "date_pick")
                # 兜底：该方向没有 scroll 可用（页面已在顶/底 —— validator 明确说
                # "页面在顶部时不会有 SCROLL_UP"）→ 重新点开日期字段。Google 的日期
                # 面板会回到当前值的月份，等于把滚过头的日历重置回目标附近。
                # 限 2 次，避免"点开→滚→点开"打转。
                if _date_field_clicks(hist) < 2:
                    for index, a in actions:
                        if a.get("kind") == "click" \
                                and _DATE_FIELD_RE.search(a.get("label") or ""):
                            return _decision("CLICK", index, a, "date_pick")

    # 阶段 a：打开日期字段（尚未操作过）。operation 必须匹配元素 kind——
    # 缺陷#18：对 textbox 类日期字段发 CLICK 会被校验器判非法，技能又是确定性的，
    # 同一非法决策重导出 3 次即触发循环检测 blocked（Flights v9 实况 i9~i11）。
    for index, a in actions:
        if (a.get("id"), a.get("label")) in clicked or a.get("kind") not in {"click", "fill"}:
            continue
        if not _DATE_FIELD_RE.search(a.get("label") or ""):
            continue
        if a.get("kind") == "click":
            return _decision("CLICK", index, a, "date_pick")
        date_text = f"{month.capitalize()} {day}" + (f", {m.group(3)}" if m.group(3) else "")
        return _decision("TYPE_TEXT", index, a, "date_pick", text=date_text)
    # 目标日期字段不在观察里：设完票种后页面常把它推到折叠下方（v83~v85 实况：这一
    # 步是模型自己在 SCROLL_DOWN，每次 3~5s 的 decider 调用）。滚动把它带进视野。
    # 守卫（v103 实况）：必须 from/to 都已填好才滚 —— 否则会在还没确认出发地时就把
    # 页面滚走、建议列表丢失，整轮退化到 blocked（step5 就滚，13 步收口）。
    # 上限 2 次（该字段离折叠线不远，多滚会把它推到视野上方去，反而更糟）。
    if sum(1 for v in ((a.get("value") or "").strip()
                       for _, a in actions if a.get("kind") == "fill") if v) >= 2 \
            and _scroll_count(hist) < 2:
        ctl = _scroll_ctl(page, "down")
        if ctl is not None:
            return _decision("SCROLL_DOWN", None, ctl, "date_pick")
    return None


# ---------------------------------------------------------------------------
# 9. 显式停止条件 → DONE（"Stop when X are visible"）
# ---------------------------------------------------------------------------

_STOP_WHEN_RE = re.compile(
    r"stop\s+when\s+(?P<what>[^.;]{3,60}?)\s+(?:are|is|be)\s+visible", re.I)


def _results_diag(page: dict, hist: list) -> dict:
    """结果页等不到时的现场快照，写进 report。

    目的（P0）：把"Google 没渲染"和"我们没看见"当场区分开。这一轮排查 v94/v110/v121
    全靠事后手工加载 final_url，绕了三轮；有这份快照一眼可判。
    """
    acts = page.get("actions") or []
    labels = [a.get("label") or "" for a in acts]
    return {
        "url": (page.get("url") or "")[:120],
        "n_actions": len(acts),
        "n_indexed": len(_indexed(acts)),
        "flight_hits": sum(1 for x in labels if "flight" in x.lower()),
        "select_flight": sum(1 for x in labels if "Select flight" in x),
        "waits_seen": sum(1 for h in (hist or []) if h.get("kind") == "wait"),
        "reloaded": any("reload" in (h.get("action") or "").lower() for h in (hist or [])),
        "text_head": (page.get("text") or "")[:160],
    }


def stop_when_visible(page: dict, goal: str, history: list) -> dict | None:
    """goal 里字面写明"停止条件"时，条件满足即 DONE。

    缺陷#24：Flights 的 goal 写着 "Stop when matching flight options are visible"，
    但 agent 没有对应技能，只能等模型自己 emit DONE（它不发）→ 结果页上空转到预算耗尽。
    取该从句里第一个内容词当"可见物"（"matching flight options" → "flight"），
    页面上有 ≥2 个含该词的可点元素即算满足。
    """
    # 滚动到"某物可见"类目标（l004/l005/l006）：
    #   "Scroll down the product list until 'Product 40' is visible."
    # 旧正则只认 "stop when X is visible"，"until X is visible" 完全不匹配；而这类页面
    # 滚到底后没有任何可交互元素，page_not_ready 会一直等下去（l004 实况：122 行日志
    # 全是 scroll 与 wait 交替）。判据对齐断言本身：history 里已有 scroll + 页面文本里
    # 出现目标串（断言就是 history_has_kind(scroll) + text_contains(X)）。
    if re.search(r"\bscroll", goal or "", re.I) and (history or []):
        if any(h.get("kind") == "scroll" for h in history):
            text = (page.get("text") or "").lower()
            wants = list(_phrases(goal))
            m_until = re.search(r"until\s+(?P<what>[^.;]{3,60}?)\s+(?:are|is|be)\s+visible",
                                goal or "", re.I)
            if m_until:
                wants.append(m_until.group("what"))
            for want in wants:
                w = (want or "").strip().strip("'\"").lower()
                if w and w in text:
                    return _decision("DONE", None, None, "stop_when_visible")
    m = _STOP_WHEN_RE.search(goal or "")
    if not m:
        return None
    hist = history or []
    if not hist:
        return None                        # 一步没走，谈不上"已可见"
    # 必须已离开起点**页面**：Flights 落地页本身就有 "Flights" / "Search for flights"
    # 两个含 "flight" 的可点元素，不加此守卫会开局即 DONE。
    # 缺陷#39：判据必须是**路径**变化，不能只比整条 URL —— 点票种/日期只改 query，
    # URL 就"变了"，而页面还是同一张表单（它自带 Flights/Hotels 导航链接，含 flight）
    # → 提前 DONE（flights-laya-v156 实况：step 7 只改 query，step 15 就 DONE，1/7）。
    from urllib.parse import urlparse as _urlparse
    here_url = page.get("url") or ""
    start_url = page.get("start_url") or ""
    if start_url and _urlparse(here_url).path == _urlparse(start_url).path:
        return None
    toks = [t for t in _content(m.group("what"))
            if t not in {"matching", "available", "the", "any", "all"}]
    if not toks:
        return None
    key = toks[0]
    hits = [a for a in (page.get("actions") or []) if key in (a.get("label") or "").lower()]
    if len(hits) >= 2 and any(a.get("kind") == "click" for a in hits):
        return _decision("DONE", None, None, "stop_when_visible")
    # 结果页正在渲染时**不要**把控制权让给模型：Flights v44 实况 —— Search 已执行
    # （URL 已是 /travel/flights/search），但结果卡片晚一拍出现，技能返回 None，
    # 模型接管后去戳 "All filters"/"Close dialog"，一路空转到预算耗尽（36 步 / 58s，
    # 校验 2/7）。这里改为有界等待，等结果渲染出来再 DONE。
    # 只在**结果页**上等：否则每填完一个字段都会白等 5 拍（v46 实况：39 步里 30 步是
    # 无谓等待，预算直接耗尽）。
    # 上限放到 20 拍（~10s）：命中即退出，快的情况（v48–v50 各 2 拍）零成本；
    # 结果页渲染慢时（v51 实况：5 拍后仍未渲染 → 让位模型 → 去戳 "All filters"
    # 空转到预算耗尽）不至于把控制权交出去。wait 不计入步预算与死循环检测，
    # 这里的 _can_wait 是唯一上限。
    if "/travel/flights/search" in (page.get("url") or ""):
        if _can_wait(hist, 20):
            return _wait("stop_when_visible")
        # 等满 20 拍（~10s）仍看不到结果 —— 实测这是 Google 的 SPA 路由偶发不渲染：
        # 同一 URL 重新整页加载必出结果（实测 12 个 "flight" 命中、3 行 "Select flight"），
        # 而运行中 25 拍都看不到。所以**整页重载一次**；比"再点一次 Search"可靠 ——
        # 重提走的是同一条出问题的 SPA 路由（v110 实测重提救不回来）。
        # 只重载一次（按历史里 reload 次数判，重载后又会累积 20 个 wait，不能用窗口判）。
        if not any("reload" in (h.get("action") or "").lower() for h in hist):
            for a in (page.get("actions") or []):
                if a.get("kind") == "reload":
                    return _decision("RELOAD", None, a, "stop_when_visible")
        # 重载后仍无结果 → 干净收口，别把控制权交给模型（v69 实况：模型去点
        # "All filters"，把结果页顶部的表单字段点掉，独立校验连 origin/destination/date
        # 都读不到，最终 2-of-7。收口后那些字段仍在，校验至少反映真实状态）。
        blocked = _decision("BLOCKED", None, None, "stop_when_visible")
        blocked["diag"] = _results_diag(page, hist)      # P0：把现场写进 report
        return blocked
    return None


# ---------------------------------------------------------------------------
# 10. 票种（one-way / round trip）
# ---------------------------------------------------------------------------

_TRIP_ONE_RE = re.compile(r"\bone[\s-]?way\b", re.I)
_TRIP_ROUND_RE = re.compile(r"\bround[\s-]?trip\b", re.I)
_TRIP_FIELD_RE = re.compile(r"ticket type|trip type", re.I)


def trip_type(page: dict, goal: str, history: list) -> dict | None:
    """goal 指定票种 → 设置它（确定性两步：展开下拉 → 点选项）。

    Flights 实况：goal 明写 "one-way"，但票种是个下拉，模型经常漏掉/被 Reset 清掉。
    """
    want = "one way" if _TRIP_ONE_RE.search(goal or "") else (
        "round trip" if _TRIP_ROUND_RE.search(goal or "") else None)
    if not want:
        return None
    actions = list(_indexed(page.get("actions") or []))
    for _, a in actions:                       # 已是目标票种 → 不动
        if _TRIP_FIELD_RE.search(a.get("label") or ""):
            text = ((a.get("label") or "") + " " + (a.get("value") or "")).lower()
            if want in text:
                return None
    hist = history or []
    clicked = {(h.get("choice"), h.get("action")) for h in hist}
    for index, a in actions:                   # 选项已展开 → 直接点
        if a.get("kind") == "click" and (a.get("id"), a.get("label")) not in clicked \
                and (a.get("label") or "").strip().lower() == want:
            return _decision("CLICK", index, a, "trip_type")
    expanded = any(_TRIP_FIELD_RE.search(h.get("action") or "") for h in hist)
    for index, a in actions:                   # 展开票种下拉
        if a.get("kind") == "click" and (a.get("id"), a.get("label")) not in clicked \
                and _TRIP_FIELD_RE.search(a.get("label") or ""):
            return _decision("CLICK", index, a, "trip_type")
    # 下拉已点开但选项还没渲染 → 等一拍（缺陷#26）
    if expanded and _can_wait(hist):
        return _wait("trip_type")
    return None


_VISIBILITY_CLAUSE_RE = re.compile(
    r"\b(?:until\b[^.;]{0,60}?\b(?:are|is|be|appears?)\b[^.;]{0,20}?\b(?:visible|screen)\b"
    r"|\bshowing\b)", re.I)


def _is_scroll_visible_goal(goal: str) -> bool:
    """goal 是否"滚动到某物可见"。page_not_ready 的让位与 scroll_to_target 的接管
    必须用**同一个**判定 —— 两处各写一份正则时（实际发生过），l005/l007 的
    "appears on screen" / "showing X" 句式只被一侧认出：scroll_to_target 想接管、
    page_not_ready 却还在原地等 → 122 行 scroll/wait 交替（M1/M2 实况）。"""
    return bool(re.search(r"\bscroll\b", goal or "", re.I)
                and _VISIBILITY_CLAUSE_RE.search(goal or ""))


def scroll_to_target(page: dict, goal: str, history: list) -> dict | None:
    """goal 是"滚动到 X 可见"但 X 还没进视口 → 一次滚到底。

    快照的 `text` 只含**视口**内容（实测 products.html 只有 257 字符、到 Product 13），
    所以"X 是否可见"就用 text 判。而 560px 一步的 scroll_down 要滚十几次，模型实测
    滚 4~5 次就放弃（l004 实况：scroll down/up 交替，永远到不了底部 → 收不了口）。
    本技能把"还看不到目标"变成一次确定性的 scroll_bottom（快照新增的合成动作）。
    接管条件见 _is_scroll_visible_goal（三种可见性句式 + scroll）。
    """
    if not _is_scroll_visible_goal(goal):
        return None
    if not (history or []):
        return None                        # 起步就滚没意义，先让页面渲染一拍
    text = (page.get("text") or "").lower()
    wants = list(_phrases(goal))
    m = re.search(r"until\s+(?P<what>[^.;]{3,60}?)\s+(?:are|is|be)\s+visible",
                  goal or "", re.I)
    if m:
        wants.append(m.group("what"))
    if any(w and w.strip().strip("'\"").lower() in text for w in wants):
        return None                        # 已经可见 → 交给 stop_when_visible 收口
    for a in (page.get("actions") or []):
        if a.get("id") == "scroll_bottom" and a.get("kind") == "scroll":
            return _decision("SCROLL_BOTTOM", None, a, "scroll_to_target")


#: 提交成功的可见确认字样（与 DoneGuard 规则 3 同表）。
_CONFIRM_WORDS = ("thank", "success", "confirm", "received", "submitted", "saved",
                  "已提交", "谢谢", "完成", "已保存")


def confirm_then_done(page: dict, goal: str, history: list) -> dict | None:
    """刚提交过 → 页面出现确认字样就 DONE，别让模型在确认页上乱点走开。

    f006 实况：form_submit 点了 Submit、页面已显示 "Thank you"，但模型接着点了导航栏的
    Home → Search → 确认页丢失 → 断言 text_contains("Thank you") 挂。
    "提交之后确认出现"是任务终点，技能应当直接收口，而不是把决定权交给模型。
    """
    if not re.search(r"\b(submit|save|send|apply|confirm)\b", goal or "", re.I):
        return None
    hist = history or []
    last_submit = max(
        (i for i, h in enumerate(hist)
         if h.get("kind") == "click" and (set(_tokens(h.get("action") or "")) & SUBMIT_WORDS)),
        default=-1,
    )
    if last_submit < 0:
        return None
    if any(h.get("kind") != "wait" for h in hist[last_submit + 1:]):
        return None                        # 提交之后又动过别的 → 不在"刚提交"窗口内
    text = (page.get("text") or "").lower()
    if any(w in text for w in _CONFIRM_WORDS):
        return _decision("DONE", None, None, "confirm_then_done")
    # 确认字样还没渲染出来 → 等一拍，别把决定权交给模型：f006 的模型正是在这个窗口里
    # 点了导航栏 Home → 确认页丢失。等待有界（_can_wait 默认 3 拍），等不到再让位。
    if _can_wait(hist):
        return _wait("confirm_then_done")
    return None


def first_result(page: dict, goal: str, history: list) -> dict | None:
    """goal 说"打开第一个结果" → 在结果页上点第一个结果链接，点了且跳转即收口。

    s011 实况："Search for 'data flywheel' and open the first result link." ——
    goal 里的短语是**搜索词**（就写在 ?q= 里），explicit_target 只会按短语匹配标签，
    无从下手；而"第一个结果"是**位置**规则，可以确定性执行。
    取"搜索输入框之后"的第一个链接：站点导航总在顶部（在搜索框之前），结果列表在后面。
    """
    if not re.search(r"\b(?:first|top)\s+(?:result|link|article|item)", goal or "", re.I):
        return None
    hist = history or []
    # 已经点过且页面确实跳转过 → 到达，收口（否则 DoneGuard 会一直否决 DONE：
    # goal 的短语是搜索词，目标页上根本不含它，goal_reached 永远为 None）
    for h in reversed(hist):
        if h.get("skill") == "first_result":
            if (h.get("outcome") or {}).get("url_changed"):
                return _decision("DONE", None, None, "first_result")
            break
    if not any(h.get("kind") == "fill" and _searchbox({"label": h.get("action") or ""})
               for h in hist):
        return None                        # 还没搜过 → 不是结果页
    seen_input = False
    for index, a in _indexed(page.get("actions") or []):
        if a.get("kind") == "fill" and _searchbox(a):
            seen_input = True
            continue
        if not seen_input or a.get("kind") != "click":
            continue
        lab = (a.get("label") or "").strip()
        if not lab:
            continue
        if set(_tokens(lab)) & {"search", "submit", "go"}:
            continue                       # 搜索按钮不是结果
        return _decision("CLICK", index, a, "first_result")
    return None


# 顺序即优先级。search_submit 放最后：机票页要先填完 from/to/日期/票种再提交。
SKILLS = (blocked_dead_page, page_not_ready, goal_reached, stop_when_visible,
          confirm_then_done, scroll_to_target, first_result,
          goto_path, explicit_target,
          select_option,
          form_fill, form_submit, entity_fill, entity_confirm,
          trip_type, search_type, select_first, date_pick, search_submit)


_STUCK: dict[str, dict[str, int]] = {}

#: 技能连着没产生效果时，让位给模型的**拍数**。必须是有界的：自建站点的实测显示，
#: 永久停用会把"技能本来是对的、只是那一次动作没生效"变成"模型乱撞到放弃"
#: （f005/f006/f007/f009、l004~l006、t003/t005 八个任务从 10/10 掉成 FAIL，
#: 失败模式全是 correct_abandon）。停两拍足够让模型换一个候选；还不行就把技能放回来。
_STUCK_TICKS = 3   # route() 每拍先减一，故实际让位 = _STUCK_TICKS - 1 = 2 拍


def note_no_effect(page_fingerprint: str, skill: str | None) -> None:
    """某个技能在同一页态上连着没产生效果 → 让位模型几拍。

    技能的动作不生效时（元素被覆盖、链接不可点、点完页面没变）会**反复重发同一决策**，
    最终被"3 次无变化 → blocked"收口 —— 那是一次可避免的失败（s001 的 explicit_target
    连点 5 次同一个翻译链接、n004 的 search_type 连填 4 次空搜索框都是这样）。
    让位给模型至少能换一个候选；但有界（见 `_STUCK_TICKS`），否则技能被永久剥夺后
    模型同样会卡死，只是从"技能死循环"变成"模型乱撞"，结果一样是失败。
    """
    if not page_fingerprint or not skill:
        return
    _STUCK.setdefault(page_fingerprint, {})[skill] = _STUCK_TICKS


def route(page: dict, goal: str, history: list) -> dict | None:
    """按精度优先级依次尝试；命中即返回 decision，全部未命中返回 None（回落模型）。

    缺陷#18 闸门：技能产出的 decision 必须过 DecisionValidator 才放行。
    确定性技能 + 非法决策 = 每次重导出同一决策 → 循环检测直接 blocked；
    非法即回落模型（模型至少会换一个选择）。
    """
    from .decision_validator import validate as _validate
    # 有界退避：每拍把剩余停用拍数减一，减到 0 就把技能放回来（见 note_no_effect）。
    fp = page.get("fingerprint") or ""
    stuck = _STUCK.get(fp) or {}
    for _name in list(stuck):
        stuck[_name] -= 1
        if stuck[_name] <= 0:
            del stuck[_name]
    if not stuck:
        _STUCK.pop(fp, None)
    for fn in SKILLS:
        if not _enabled(fn.__name__) or stuck.get(fn.__name__, 0) > 0:
            continue
        try:
            d = fn(page, goal, history or [])
        except Exception:
            d = None                       # 技能内部异常绝不影响主流程
        if not d:
            continue
        try:
            if not _validate(d, page).valid:
                continue                   # 结构非法 → 交给下一个技能/模型
        except Exception:
            continue
        return d
    return None
