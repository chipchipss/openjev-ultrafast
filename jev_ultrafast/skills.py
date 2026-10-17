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
from jev_ultrafast.logger import dbg
import os
import re
from urllib.parse import parse_qsl, unquote, urlparse as _urlparse

KIND_TO_OP = {"click": "CLICK", "fill": "TYPE_TEXT", "select": "SELECT"}

STOPWORDS = {
    "the", "a", "an", "of", "to", "and", "or", "for", "with", "in", "on", "by",
    "open", "go", "search", "find", "page", "article", "website", "site", "from",
    "then", "it", "its", "use", "about", "please", "click", "this", "that", "new",
}
SUBMIT_WORDS = {"submit", "send", "go", "search", "continue", "ok", "apply", "confirm",
                "save", "update",
                # 中文提交控件（real-1007 r109 实况：OSM 按出口 IP 本地化成中文，
                # 提交按钮 label 是"提交"，英文词集永远匹配不上 → 填完不提交）。
                "提交", "发送", "前往", "搜索", "查找", "查询", "继续", "确定",
                "确认", "保存", "更新"}   # save/update：t003/t005 的保存按钮（旧集合缺 save → 永不点）


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


def indexed_actions(actions: list[dict]) -> list[tuple[str, dict]]:
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

#: `page_not_ready` 连续等待的上限。循环侧的停滞守卫**全部排除 wait**
#: （agent.py:220/240/260 —— "wait 不是动作"），所以这里不设限就等于"一路等到
#: 硬顶"：b10/b11 的 r107 点进一张永远空白的外链页后连等 59 拍撞 MAX_STEPS=60，
#: 收口还是靠 agent.py 那个抛异常的硬顶。
#:
#: 值取 8 而不是更小：已落盘 trace 里**自然收敛**的最长连等是 6 拍
#: （b10 的 r101，pypi 搜索结果页第 6 拍之后 `page_changed=True` 真的渲染出来了）。
#: 上限必须留在"真实页面还在渲染"这一侧，同时对 59 拍那种永远不渲染的页面封顶。
PAGE_NOT_READY_MAX_WAITS = 8


def blocked_dead_page(page: dict, goal: str, history: list) -> dict | None:
    url = (page.get("url") or "")
    if url.startswith("chrome-error://") or url.startswith("about:neterror"):
        return _decision("BLOCKED", None, None, "blocked_dead_page")
    return None


def page_not_ready(page: dict, goal: str, history: list) -> dict | None:
    """页面还在导航/渲染（观察里没有任何可操作元素）→ 等一拍，别让模型在空白页上决策。
    等是有上限的（PAGE_NOT_READY_MAX_WAITS），到上限让位给后续技能与模型。

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
    # （scroll/reload/wait），真正空白的是 KIND_TO_OP 里的那些，indexed_actions 正好按此过滤。
    if not indexed_actions(page.get("actions") or []):
        # 有正文、零可交互元素 = **内容页**（搜索结果 / JSON 回显 / 文章 / 报错页），
        # 不是"还没渲染"。判据必须看正文，否则表单提交后的回显页会被无限等待：
        # f002 实况——httpbin /post 的 JSON 响应零控件 → 连等 57 拍撞上 60 步上限，
        # 尽管断言（页面含 "hello world"）早已满足，goal_reached 根本没机会跑。
        if (page.get("text") or "").strip():
            return None
        if not _can_wait(history, PAGE_NOT_READY_MAX_WAITS):
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
      - 只从真实元素里选（indexed_actions 过滤 scroll/wait/reload 合成控件）；
      - 后续安全链不变：Policy 黑名单 / DoneGuard / Validator 照常拦。
    env M18_FIRST_ACTION_FLOOR=0 关闭。
    """
    if os.environ.get("M18_FIRST_ACTION_FLOOR", "1") != "1":
        return None
    candidates = indexed_actions(page.get("actions") or [])
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
    query = _goal_query(goal or "")
    # 只发**可执行**动作（real-1007 r102/r105 教训）：CLICK 永远可执行；
    # TYPE_TEXT 需 goal 能确定性派生文本；SELECT 需要值语义,floor 给不出 →
    # 跳过。按分数从高到低取第一个可执行的。
    for index, action in sorted(candidates, reverse=True,
                                 key=lambda ia: _floor_score(ia[1]) + _goal_overlap(ia[1], goal_tokens)):
        kind = action["kind"]
        if kind == "click":
            return _decision("CLICK", index, action, "first_action_floor")
        if kind == "fill" and query:
            return _decision("TYPE_TEXT", index, action, "first_action_floor", text=query)
    return None


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

# "同一句内"的跨词匹配片段：句点只有在**后面不接空格**时才算名字的一部分。
# 原来的 [^.;]* 把 "llama.cpp" 里的句点当成了句子结尾（r106 实况），凡目标名带
# 点（文件名、仓库名、版本号）的复合句都会被截断，第二跳因此认不出来。
_HOP_SPAN = r"(?:[^.;]|\.(?=\S))*"

# C2b 缩写表：URL 里常见的缩写 ↔ goal 里的全称。键 = URL 缩写,值 = goal 全称
# ——匹配方向是"goal 的头词全称 → 展开出 URL 缩写形式去 URL 里找"
#（n001 实况 2026-10-07:goal 要 "documentation",目标站 URL 是 docs.python.org）。
_ABBREV = {"docs": "documentation", "doc": "documentation"}


def _arrival_facts(page: dict, goal: str, hist: list) -> dict:
    """到达判据共用的一组"页面事实"，一次算清（原来摊在 `goal_reached`  body 里）。

    每一个键都在下面某条路径上用；没有一个是"预备着以后用"。
    """
    # 缺陷#40：URL 匹配只用 **path**，不吃 query —— 搜索词会原样出现在 ?q=… 里，
    # 于是 "Search for 'OpenAI' and open the official OpenAI website" 在**搜索结果页**
    # 就命中短语 → goal_reached 连发 8 次 DONE（s001 实况，整轮判失败）。
    # query 只是把搜索词回声出来，不构成"已到达目标"的证据。
    u = _urlparse(page.get("url") or "")
    here_url = _flat(_norm_page(u.netloc + u.path))
    # 带 query 的完整 URL：**提交类**目标的成功判据就在 query 里
    # （"Search for 'automation' and submit the search form" → 断言 q=automation）。
    here_full = _flat(_norm_page(u.netloc + u.path + "?" + u.query))
    here_all = here_url + " " + _flat(_norm_page(page.get("title") or ""))
    # 当前 URL 的 query：搜索词会被原样回声在这里，也会回声进结果页标题
    # （"OpenAI - Google Search"）。凡"短语就是搜索词"的一律不算到达目标 ——
    # 否则 "Search for 'OpenAI' and open the official OpenAI website" 在结果页
    # 就判完成（s001 实况：连发 8 次 DONE，整轮失败）。
    query_echo = _flat(_norm_page(u.query))
    # 起点页：优先用 agent 提供的任务起始 URL。history[0]["url"] 是"动作之后"的
    # URL——第一步就到达目标时会把它误当起点，导致 goal_reached 永不触发
    # （s003 实况：一步跳到 /standards/，"standards" 已在"起点"里 → 判据自锁）。
    start = _flat(_norm_page(page.get("start_url") or hist[0].get("url") or ""))

    # 目标明写是"网站/站点/官网"时，到达判据必须落在 **host** 上：goal 说 "open the
    # official OpenAI website"，点进任意一条标题含 OpenAI 的新闻结果也算"路径含
    # openai"，但那不是官网（s001 实况）。维基/RFC 类目标不写 website，仍走路径+标题。
    # 注意必须带"网站/官网"字样，不能见 "site" 就算：s002 的 goal 是 "Use the site search
    # on docs.python.org …"——这里 site 指"站内搜索功能"，不是"打开该网站"，按 host 判到达
    # 会让 URL 已含 asyncio 的结果页判不出到达（s002 实况）。
    # “homepage/website” 只有作为**目的地**时才算站点目标。r114 实况：goal 是
    # "From the Django homepage, open the page titled '…part 1'"，那个 homepage
    # 是**起点**，却被这条判据当成“打开网站” → 到达判据只认 host →
    # 文档页标题里明明逐字写着目标短语，goal_reached 永远发不出 DONE，
    # 于是 explicit_target 接手，在已到达的页面上点侧栏下一条（part 2）跑偏。
    # r115 同一句式。先把 "from the … homepage/website" 这类起点框架涂掉再判。
    dest = re.sub(r"\bfrom\s+the\s+[\w' -]{0,30}?\b(?:homepage|website|site)\b", "",
                  goal or "", flags=re.I)
    return {
        "here_url": here_url,
        "here_full": here_full,
        "here_all": here_all,
        "query_echo": query_echo,
        "start": start,
        "title_norm": _norm_page(page.get("title") or ""),
        "nav_verb": bool(re.search(r"\b(open|navigate|go to|find|visit|reach|use)\b",
                                   goal or "", re.I)),
        "submit_verb": bool(re.search(r"\b(submit|search|type|look up)\b",
                                      goal or "", re.I)),
        "website_goal": bool(re.search(
            r"\b(?:website|web\s*site|homepage|official\s+(?:site|website|page))\b",
            dest, re.I)),
        "host_flat": _flat(_norm_page(u.netloc)),
    }


def _arrival_hit(facts: dict, phrase: str, where: str) -> bool:
    """短语算不算"到达"。原来是 `goal_reached` 里的闭包，读三个外部局部变量。"""
    pn = _flat(phrase)
    if not pn or pn in facts["start"]:
        return False
    if facts["website_goal"]:
        return pn.replace(" ", "") in facts["host_flat"].replace(" ", "")
    # 短语里的空格在 URL 里不存在："RFC 9110" 的 _flat 是 "rfc 9110"，而目标页是
    # /info/rfc9110/ —— 纯排版差异导致永远判不出到达（n004 实况）。两侧压掉空格再比一次。
    return pn in where or pn.replace(" ", "") in where.replace(" ", "")


def _arrival_by_phrases(goal: str, facts: dict) -> dict | None:
    """路径 A：显式短语（引号串 / RFC 号）出现在 URL 或标题 → 已到达目标页。
    路径 B：搜索/提交类，短语落在**含查询串**的完整 URL。"""
    _idents = set(_repo_ident_phrases(goal))
    for p in goal_phrases(goal):
        if p.startswith("/") or len(p.strip()) < 3:
            continue
        # 标识档不作到达证据（③）：goal 说 "the Releases page of the pytorch/pytorch
        # repository"，`/pytorch/pytorch` 只是**仓库根**，URL 里含它就 DONE 会把一个还没
        # 到 Releases 的页面判成成功（false positive，硬约束直接破）。r105 的到达判据
        # 留给下一刀的 "Releases" 档；带引号的 id（r106/r119）不走这一格，照旧。
        if p in _idents:
            continue
        # 短语就是搜索词（出现在 ?q= 里）时不算"已到达"—— 但两类例外：
        #   1) 目标是"打开某个网站"：那种目标只认 host（见 _arrival_hit），query 永远不算证据；
        #   2) 目标是"提交搜索"：?q= 恰恰就是成功判据本身。
        # s007 实况：一律排除 query 后 goal_reached 永不触发，搜索已经成功却继续跑，
        # 模型接手又提交了一次**空**表单 → 终点变成 ?q= → FAIL。
        # 但 goal 里还有**第二个 hop**（"…and open the first result link"）时，?q= 又不算了：
        # s011 的断言要的是结果页 articles.html/technology.html，而不是结果列表本身
        # （实况：搜索成功后 goal_reached 连发 5 次 DONE，断言 url_matches 挂）。
        # 片段用 _HOP_SPAN 而不是 [^.;]*：r106 实况（2026-10-07）的 hop 目标是
        # "ggml-org/llama.cpp repository page"，名字里的句点把旧正则截断在 "llama"，
        # 第二跳没认出来 → 搜索结果页（标题也回声 "llama.cpp"）上连发 7 次 DONE，
        # 每次都被 _done_guard 规则 2 拒掉 —— 类 C 拒绝循环就是这么形成的。
        _second_hop = bool(re.search(
            r"\bopen\b" + _HOP_SPAN + r"\b(result|link|article|item|page)\b",
            goal or "", re.I))
        if (_flat(p) and _flat(p) in facts["query_echo"]
                and (facts["website_goal"] or not facts["submit_verb"] or _second_hop)):
            continue
        if facts["nav_verb"] and _arrival_hit(facts, p, facts["here_all"]):
            return _decision("DONE", None, None, "goal_reached")
        if facts["submit_verb"] and _arrival_hit(facts, p, facts["here_full"]):
            return _decision("DONE", None, None, "goal_reached")
    return None


def _arrival_by_nav_object(goal: str, facts: dict) -> dict | None:
    """路径 C：无引号导航目标——"navigate to the Standards page" 这类。三条判据：
      C1 目标短语"整段连续"出现在标题里。必须连续（不是"内容词都出现"）：
         n001 实况——goal 要 docs.python.org，中间页 python.org/doc/ 的标题
         "Our Documentation | Python.org" 同时含 python+documentation，
         按词判会误判到达并提前 DONE。
      C2 目标的头词（末位内容词）出现在当前 URL 里。补 C1 的漏网：
         n003 实况——目标页标题是 "Standards and guidelines | W3C"，
         不含连续的 "w3c standards"，但 URL 是 /standards/。
      C2b 头词的**常见缩写**出现在 URL 里。n001 实况（2026-10-07 隔夜诊断）：
         goal "Open the Python documentation section"，agent 第 1 步已到
         docs.python.org/3/，但 C1 标题无 "python documentation"、C2 URL 是
         **docs**.python.org 不含 "documentation"——已达成却被漏接，agent 又
         点 logo 跑回 python.org 循环到预算耗尽（correct_abandon）。缩写归一
         是 laya-browser-agent goal-aware 原则的同类应用：目标词已到达就不该
         因排版变体而漏判。
    """
    if not (facts["nav_verb"] and not facts["website_goal"]):
        # website 类目标（"open the official X website"）不走这里：它的到达判据只能是
        # host（见 _arrival_hit），否则点进任意标题含 X 的新闻页都会判到达（s001 实况）。
        return None
    m = _NAV_OBJ_RE.search(goal or "")
    if not m:
        return None
    obj = m.group("t")
    obj_n = " ".join(_tokens(obj))
    title = facts["title_norm"]
    start = facts["start"]
    # obj 必须含**实义词**。_NAV_OBJ_RE 的 "the" 是可选项，"open the page
    # titled 'X'" 会退化成 obj="the"（实况 r114/r115），而 "the" 几乎出现在
    # 每个页面标题开头 → C1 在起点首页就判到达，提前 DONE。
    if obj_n and _content(obj) and obj_n in title and obj_n not in start:
        return _decision("DONE", None, None, "goal_reached")
    toks = _content(obj)
    head = toks[-1] if toks else ""
    # C2b: goal 用全称、URL 用缩写时展开（documentation → docs/doc）。
    # 缩写只允许命中 **host**，不允许命中路径——n001 实况：起点站 python.org
    # 自己就有 /doc/（文档入口页），路径级匹配会把中间页误判为到达（C1 注释
    # 警告过的原始案例，断言要的是 docs.python.org 域）；而目标站是
    # docs.python.org，'docs' 在 host 里。C2 原判据对全称仍是全 URL 匹配
    # （n003 /standards/ 依赖它），只有**展开的缩写**收紧到 host。
    heads = [head] + [k for k, v in _ABBREV.items() if v == head]
    if head and head not in start:
        if re.search(rf"\b{re.escape(head)}\b", facts["here_url"]):
            return _decision("DONE", None, None, "goal_reached")
        for h in heads[1:]:
            if re.search(rf"\b{re.escape(h)}\b", facts["host_flat"]):
                return _decision("DONE", None, None, "goal_reached")
    return None


def goal_reached(page: dict, goal: str, history: list) -> dict | None:
    hist = history or []
    if not hist:
        return None                        # 0 步 DONE 会被 DoneGuard 拦，不产出
    # 只在"导航到目标"类 goal 上生效。以下情况到达页面 ≠ 完成：
    #   破坏/交易类（delete / buy…）——x001/x002 的正确答案是放弃
    #
    # book 必须**带宾语**才算交易。裸 \bbook\b 会把名词用法一并杀掉：
    # r111/r112 实况——"'Travel' book category"、"detail page of the book
    # 'Tipping the Velvet'" 都已经真的到达目标页（r112 到了两次），但这一行
    # 直接 return None → goal_reached 全程弃权 → agent 到站不认识路，
    # 继续点侧栏跑到别的书，budget 耗尽。"book a flight" 这类才是交易。
    if re.search(r"\b(delete|remove|destroy|permanently|buy|purchase|order)\b"
                 r"|\bbook\s+(?:a|an|the|our|my|to|for|now|flight|hotel|table|"
                 r"trip|ticket|room|seat|appointment)\b",
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
    # goal_phrases 故意跳过 "with 'X'" 形式的引号串（当值不当目标），于是
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
    facts = _arrival_facts(page, goal, hist)
    return _arrival_by_phrases(goal, facts) or _arrival_by_nav_object(goal, facts)


def _same_site(a: str, b: str) -> bool:
    from urllib.parse import urlsplit
    ha, hb = (urlsplit(a or "").hostname or "").lower(), (urlsplit(b or "").hostname or "").lower()
    return bool(ha) and ha == hb


def _phrase_token_set(s: str) -> set[str]:
    return {_stem(t) for t in _tokens(_flat(s or "")) if t}


#: "踩过链之后要不要停下来"里的"链"必须至少有两个实词，否则一个 'the' / 'page'
#: 就能把任意导航判成到站（#52 的页眉 chrome 就是这么混进来的）。
_ARRIVAL_MIN_TOKENS = 2

#: goal 里"要去哪儿"的动词。b25 的 r110 就是被这条钉住的：
#: `In 'The Rust Programming Language' book, go forward to Chapter 4, 'Understanding Ownership'.`
#: 第 1 拍点的是**容器**那条链（'The Rust Programming Language'），落地
#: `doc.rust-lang.org/stable/book/index.html`，而目的地是第二个短语——旧判据拿
#: "任一引号短语"去比标签，把容器认成终点，DONE 之后那一行从 b24 的 PASS 变 FAIL。
#: 动词集与 DoneGuard 规则 6 判"纯导航 goal"用的是同一族词（agent.py:107），
#: 另外要接住 "go forward to / go back to" 这种中间带副词的写法。
_NAV_VERB_RE = re.compile(
    r"\b(?:open[s]?|navigat(?:e|es)\s+to|go\s+(?:forward\s+|back\s+|on\s+)?to|visit[s]?"
    r"|reach(?:es)?)\b", re.I)


def _destination_phrases(goal: str, quoted: set[str]) -> list[str]:
    """goal 里**最后一个导航动词之后**出现的具名短语 = 这趟路要去的地方。

    认不出动词、或动词后面没有具名短语 → 返回空（不知道终点就不说话）。
    50 条 goal 里只有一条是"容器短语 + 目的地短语"的形状（r110），其余导航题的
    动词之后就只有一个短语，六行复跑与 b25 的 8 次开火都在这一类里。
    """
    verbs = list(_NAV_VERB_RE.finditer(goal or ""))
    if not verbs:
        return []
    tail = (goal or "")[verbs[-1].end():]
    return [p for p in quoted if p in tail]


def link_followed_arrival(page: dict, goal: str, history: list) -> dict | None:
    """goal 用引号点名的那条链**已经被踩了、页也换了** → DONE，别再为那个短语翻页面。

    形状来自 b24 的六行（`logs/real-1011-b24-ipc58-1011-015958/r1xx.jsonl`，
    `tests/test_skills.py::ARRIVAL_ROWS` 逐字抄的）：第 1 拍 `explicit_target` 在起点页
    点中 goal 里的短语，`page_changed=True`，落地页就是断言页；然后第 2–5 拍
    `scroll_to_named_target` 在到达页上继续找**同一个短语**，r123 第 6 拍走到
    `search_type`（把目标名打进站内搜索框），r142 第 6–8 拍由模型点在陌生人上传的
    文件链接上（三个 `page_changed=False` 的下载）。

    为什么"在到达页上找短语"这条路永远走不通：goal 的引号短语是**起点页那条链的标签**，
    不是目的地的标识。`m2/probe_arrival_fixtures.py` 抓的真实到达页量过（计数表在
    `m2/real-log.md`）：r126 的 'SQL Syntax' 在 sqlite.org/lang.html 正文里出现 **0** 次
    （那页的标题是 'Query Language Understood by SQLite'）。所以这不是"多滚两拍"的
    效率问题，是判据结构性地不会满足。

    守卫（每一条都有反面形状）：
      - **goal 是纯导航**：`_AWAY_VERB_RE`（search/scroll/fill/type/select/submit…）或
            `_is_scroll_visible_goal` 命中就弃权——goal 写了搜索/滚动时那一族有自己的收口，
            这里抢会把 `search_type` 的活吃掉（r116 第一次单任务实测就是这个形状）。
      - **最后一个真实动作是 click**（`_last_real` 跳过技能发的 WAIT，缺陷#26b 同因）。
      - **踩的就是那个短语**：标签与引号短语在词干集上互相包含；实词少于 2 个不认。
        而且比的是**目的地短语**——最后一个导航动词之后的那个（b25 的 r110 点的
        'The Rust Programming Language' 是容器，不是终点；认不出动词或动词后没有短语就弃权）。
      - **那一拍确实换了页**：用 agent 结算出来的 `outcome.url_changed`（:602-608），
        而不是"我以为历史里有出发页"——第一次实盘复跑就是因为读错这张表而全线没开火，
        详见 `m2/real-log.md`。
      - **还站在落地页上**：`page['url']` 等于那条历史记录的落地 `url`（去掉片段比）。
        已经走开了就不是"刚到站"，不该由这一档说话。
      - **同一个站点**：出发页 `url_from` 与落地页同主机——跨站跳过来的不是任务终点。
    """
    if _is_scroll_visible_goal(goal) or _AWAY_VERB_RE.search(goal or ""):
        return None
    quoted = {m.group(1) for m in re.finditer(r"['\"]([^'\"]{2,60})['\"]", goal or "")}
    if not quoted:
        return None
    phrases = _destination_phrases(goal, quoted)
    if not phrases:
        return None
    h = _last_real(history)
    if not h or h.get("kind") != "click":
        return None
    label = str(h.get("action") or "")
    if not label:
        return None
    from urllib.parse import urlsplit

    def _key(u: str) -> str:
        # SplitResult 的字段只有 scheme/netloc/path/query/fragment；netloc 本身带 userinfo，
        # 所以"去掉片段再比"就够，别去 _replace 不存在的 username/password。
        return urlsplit(u or "")._replace(fragment="").geturl()

    cur = str(page.get("url") or "")
    if not (h.get("outcome") or {}).get("url_changed"):
        return None
    if _key(cur) != _key(str(h.get("url") or "")):
        return None                                   # 已经离开落地页
    if not _same_site(str(h.get("url_from") or ""), cur):
        return None
    lab = _phrase_token_set(label)
    if len(lab) < _ARRIVAL_MIN_TOKENS:
        return None
    for ph in phrases:
        toks = _phrase_token_set(ph)
        if len(toks) < _ARRIVAL_MIN_TOKENS:
            continue
        if toks <= lab or lab <= toks:
            return _decision("DONE", None, None, "link_followed_arrival")
    return None


def _fill_values(goal: str) -> list[str]:
    """goal 里处于「值位置」的引号串：`fill X with 'v'` / `enter 'v' into X`。

    与 goal_phrases 互补——那里刻意把这类串跳过（值不是目标），但对"是否已完成"
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


#: goal 把 `org/repo` 型标识**明写成仓库**时才算标识（r105 是全场 101 题里唯一 witness：
#: "Open the Releases page of the pytorch/pytorch repository."）。
#: 为什么要语境门：`and/or`、`24/7`、`n/a` 这些英文斜杠词形状完全相同，纯词法认会把
#: 噪声灌进 `goal_phrases`/`explicit_target`/`goal_reached` 三条链；按"名词只收见过的"，
#: 只收 goal 自己把它称作 repository 的那种。语境词只有 repository/ies 一个见证，
#: 裸 repo 没见过，不收。
_REPO_CTX_RE = re.compile(r"\brepositor(?:y|ies)\b", re.I)
#: 左边界排除 `:` `/`，所以 `https://host/path` 这种已经带前导斜杠的写法仍归路径档管。
_IDENT_RE = re.compile(r"(?<![\w.\-/])([A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-]+)+)")


def _repo_ident_spans(goal: str) -> list[tuple[str, int, int]]:
    """(短语, 起, 止)：goal 里明写作仓库的 `org/repo` 标识及其跨度。"""
    if not _REPO_CTX_RE.search(goal or ""):
        return []
    return [(m.group(1), m.start(1), m.end(1)) for m in _IDENT_RE.finditer(goal or "")]


def _repo_ident_phrases(goal: str) -> list[str]:
    return [p for p, _s, _e in _repo_ident_spans(goal)]


def goal_phrases(goal: str) -> list[str]:
    """goal 里字面写明的目标短语：引号串 / org-repo 标识 / 路径 / RFC 号 / 介词后的名词短语。"""
    out = []
    for m in re.finditer(r"['\"]([^'\"]{2,60})['\"]", goal):
        pre = goal[max(0, m.start() - 8):m.start()].lower()
        if re.search(r"\bwith\s*$", pre):     # 'Test User' 这类是"值"，不是目标
            continue
        out.append(m.group(1))
    idents = _repo_ident_spans(goal)
    out += [p for p, _s, _e in idents]
    # 路径档必须跳过**落在标识跨度内**的斜杠：r105 实测 `pytorch/pytorch` 被旧读法从
    # 词中间的斜杠吃成 `/pytorch` → 结果页认组织名单元格、仓库页被 `host_hit` 抬到
    # 3.0+ 点上站外 `pytorch.org`（两发都在 `m2/probe_r105_shape.py` 的 D/E 段）。
    out += [m.group(0) for m in re.finditer(r"(/[\w\-/\.]{2,40})", goal)
            if not any(s <= m.start() < e for _p, s, e in idents)]
    out += [m.group(0) for m in re.finditer(r"\bRFC[\s-]?\d{3,5}\b", goal, re.I)]
    # 介词后的名词短语："Open the Wikipedia article on Gödel's incompleteness theorems."
    # 三类都不命中（无引号、无路径、无 RFC）→ goal_phrases 曾返回 []，于是 goal_reached
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
    phrases = goal_phrases(goal)
    if not phrases:
        return None
    recent = {h.get("choice") for h in (history or [])[-4:]}
    idents = set(_repo_ident_phrases(goal))

    # 单/复数折叠：只在**这一层**做，绝不进 `goal_phrases` / `_goal_query`（它们喂搜索词，
    # 折叠会把 "Downloads" 变成 "Download" 去搜）。证据面：r115 实况，python.org 上
    # goal 写 'Download Python'，导航 label 是 "Downloads"，一个 s 之差 → 全部档位
    # 不认 → 回落 2B → 第 1 拍点了搜索框。别的任务还没有复数标签 witness，
    # 名词只收见过的，不许按想象扩充。
    def _fold_s(t: str) -> str:
        return t[:-1] if len(t) > 5 and t.endswith("s") else t

    try:
        _page_host = _urlparse(page.get("url") or "").netloc.lower()
    except Exception:
        _page_host = ""
    scored = []
    for index, a in indexed_actions(page.get("actions") or []):
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
        lt = _tokens(lab)
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
        # 越域守卫（探针 E 段）：`org/repo` 标识指的是**某个站点里面的位置**，不是站外的
        # 同名品牌。旧读法把它吃成 `/pytorch` 之后，`host_hit` 会把仓库页 About 栏里的
        # `pytorch.org` 抬到 3.0+ —— 地板就这样把任务带出任务域名。标识档只认站内候选
        # （相对 href，或与当前页同 host）；站外一律不给分，宁可弃权也不跳域。
        off_site = bool(host and _page_host and host != _page_host)
        # R 类（r107 唯一 witness）：HN 的导航链是**无前导斜杠的相对路径**，目标写成
        # label "new" / href "newest"，而 goal 引号里是 'newest' —— 五个 label 档结构上
        # 够不到，goto_path 又只认 goal 明写的路径。这里补一档"站内路径段整段相等"。
        href_segs: list[str] = []
        if _href and not _site:
            try:
                _hp = _urlparse(_href)
                _rel = (not _hp.netloc
                        and not re.match(r"^[A-Za-z][A-Za-z0-9+.\-]*:", _href))
                if _rel or (_page_host and _hp.netloc.lower() == _page_host):
                    href_segs = [s for s in _hp.path.split("/") if s]
            except Exception:
                href_segs = []
        best = 0.0
        for p in phrases:
            if p in idents and off_site:
                continue
            pn = " ".join(_tokens(p))
            if not pn:
                continue
            pt = _tokens(p)
            # 域名命中 = "这是对的站点"；label 命中 = "这是站点里对的那一页"。两者必须
            # **叠加**：同一站点会有多条链接（主结果 + 该站点的子链接共用同一个 cite），
            # 只按域名打分会全部同分 → "明显优势"判据不成立 → 直接回落模型
            # （s001 实况：openai.com 的主结果和子链接并列 3.0 → None）。
            host_hit = bool(host_flat and pn.replace(" ", "") and pn.replace(" ", "") in host_flat)
            label_score = 0.0
            if lab_n == pn:
                # 精确匹配（如结果标题与 goal 引号串逐字相同）显著高于"包含"
                label_score = 2.0 + min(len(pn), 40) / 1000.0
            elif lab_n.startswith(pn + " "):
                # 短语落在标签**开头** = 这一条就是被点名那条。结果列表里"包含短语"的
                # 行远不止一条（r101 实况：pypi /search/?q=flask 上 Flask 与
                # tesseral-flask / thunderdome-flask / toga-flask 同拿 1.0），
                # 0.15 的优势门槛一触即发 → 地板弃权 → 2B 在 0.3~0.5 置信度上
                # 反复点同一个 target，三次无变化就被 agent.py 的无进展判据收尾。
                # 0.5 的档差稳过该门槛；若页面上仍有**两行同为前缀**（真同分）照旧弃权交模型——不赌位置。
                label_score = 1.5 + min(len(pn), 40) / 1000.0
            elif pn in lab_n:
                label_score = 1.0 + min(len(pn), 40) / 1000.0
            elif p.startswith("/"):
                # 路径类短语（/forms/post）必须"整段出现在 label 里"——
                # 反向包含会让 "/post" 命中 "/forms/post"（f001 实况：点错到 /post）
                label_score = 0.0
            elif len(lab_n) >= 4 and pn.startswith(lab_n + " "):
                # 片段匹配只认**从头对齐**的缩写（"Style Guide" ⊂ "Style Guide for Python Code"）。
                # 任意位置的包含会把站点名当目标：r113 实况，peps 首页上唯一命中短语的动作是导航链接
                # "Python"（"python" 只是短语中间的词）→ 0.9 且无对手 → 跳出任务域名，后面全塌。
                label_score = 0.9
            elif (pt[0] not in STOPWORDS and len(lt) <= len(pt)
                  and all(_fold_s(x) == _fold_s(y) for x, y in zip(lt, pt))
                  and any(x != y for x, y in zip(lt, pt))):
                # 复数折叠档（r115 唯一 witness）：标签是短语的**逐词前缀**，唯一差别
                # 是单/复数。0.95 稳在 0.9（片段）之上、1.0（包含）之下；与 0.9 并存的
                # 页面（"Downloads" + "Download" 同时挂链接）差 0.05 < 0.15 → 照旧弃权，
                # 不赌位置。
                label_score = 0.95 + min(len(pn), 40) / 1000.0
            # （这里原来还有一档"词重叠 ≥0.75 ⇒ 0.75+ratio/10"，#46 把它删了。）
            # 删的理由不是它误点了 r113，而是**两条离线读数说它是死档**：
            # ① `m2/probe_near_miss_tier_attribution.py` 在 186 份真实页上数 `explicit_target` 的
            #    71 次非弃权命中，档位分布是 精确 50 / 前缀 6 / 包含 8 / 片段 3 / 折叠 1 / 其它 3，
            #    词重叠档 **0 次** —— 没有任何一次正确的命中靠它；
            # ② 测量时把门槛抬到刚好压过它（`top[0] ≥ 0.86`，这一版**没进产品**）之后
            #    `m2/golden_tier3.py --compare` 在 193 页 / 772 例上**摘要一字不动**（`f7e05f70…`）
            #    ⇒ 这一档在语料上是死档；进产品的改动是**删档**，门槛保持 0.75
            #    （剩下的最低 label 档是 href 的 0.88，抬门槛会顺手禁掉未来的低档，那是两件事混成一件）。
            # 而它单独开火的代价是实测的：peps 滚一格时页面只有 `Style Guide for C Code`
            # （goal 引号串是 `Style Guide for Python Code`，缺 `python` 这个词 = 3/4 = 0.825），
            # 候选只有一个时 `second = 0`，0.825 自己就过门槛 ⇒ 那一拍点向 `pep-0007/`，
            # 一页**没被 goal 点名**的页。改前改后 r113 都是 3 步 / 4 次模型调用 ⇒ **这一刀不买步数，
            # 买的是"不在错页上开火"**（`reports/one-r113-1014-142145.json` 与批内
            # `logs/ci-1014-1423-1014-144253/r113.jsonl` 同一形状）。形状与判据都在
            # `tests/test_explicit_target_near_miss.py`。
            if not label_score and href_segs and not p.startswith("/"):
                # 0.88 故意压在 0.9（从头对齐片段）之下：页面上只要还有别的 label 信号，
                # 差值就 <0.15 → 照旧弃权，这一档**只在 href 是唯一线索时**开火。
                # 明写路径的短语（"/forms/post"）仍归 goto_path 管。
                # （它原先还压在词重叠档之上，那一档已按 #46 删除，见上面的注释。）
                for _seg in href_segs:
                    if " ".join(_tokens(_seg)) == pn:
                        label_score = 0.88 + min(len(pn), 40) / 1000.0
                        break
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
    for index, a in indexed_actions(page.get("actions") or []):
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
            for index, a in indexed_actions(actions):
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
        for index, a in indexed_actions(actions):
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
    for index, a in indexed_actions(page.get("actions") or []):
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
    for index, a in indexed_actions(page.get("actions") or []):
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


_SEARCH_SUBMIT_WORDS = {"search", "go", "submit", "send",
                        # 中文界面（r109 实况：OSM 本地化成"提交"按钮）
                        "搜索", "前往", "提交", "发送", "查找", "查询"}


def _searchbox(a: dict) -> bool:
    """搜索框判定：只看 label 语义（含中文"搜索/查找"）。

    刻意不看 role：combobox 太泛（航班 "Where from?"、日期框都是 combobox），
    按 role 认会把目标字段误当搜索框（Flights 实况）。
    """
    return bool(_SEARCHBOX_RE.search(a.get("label") or ""))


def _goal_query(goal: str) -> str | None:
    """goal 里可确定性派生的搜索词（显式正则优先，单一短语兜底）。

    search_type 与 first_action_floor 共用同一判据：派生不出文本的 TYPE_TEXT
    动作不可执行——real-1007 实况 r102/r105，floor 发无 text 的 TYPE_TEXT、
    agent 无从执行、history 恒空、去重失效，同一决策连发 5 次空转。
    """
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
        # 标识档不派生成搜索词（④）：实测一派生，`first_action_floor` 就把
        # `pytorch/pytorch` 打进 github 页脚的订阅邮箱框（`m2/probe_r105_shape.py` A 段
        # 唯一可 fill 的就是它）——比 b16 那一拍空点击更糟。"该填哪个框"是另一刀，
        # 不在读法这一格里夹带。
        _idents = set(_repo_ident_phrases(goal or ""))
        cand = [p for p in goal_phrases(goal or "")
                if not p.startswith("/") and p not in _idents]
        if len(cand) == 1:
            query = cand[0]
    return query


def search_type(page: dict, goal: str, history: list) -> dict | None:
    query = _goal_query(goal or "")
    if not query:
        return None
    hist = history or []
    done = {(h.get("choice"), h.get("text")) for h in hist}
    # 同一 query 本任务内已输入过 → 不再输入（结果页常又有一个空搜索框，
    # 否则会把 query 重打一遍而不去点结果：n004 实况）
    if any(h.get("kind") == "fill" and (h.get("text") or "").strip() == query for h in hist):
        return None
    for index, a in indexed_actions(page.get("actions") or []):
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
            for index, a in indexed_actions(page.get("actions") or []):
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
         and (set(_tokens(h.get("action") or "")) & _SEARCH_SUBMIT_WORDS)),
        default=-1,
    )
    if last_sub > last_fill:
        return None                        # 已提交且此后未再输入 → 不再提交
    # 页态判据（n004 三轮冻结 round 1331 的第 5 拍）：上面那条按历史的去重会被
    # "模型在结果页把同一句 query 重填一次"重置，而结果页上同一个提交按钮换了编号
    # （e15→e10），"这个 id 点过没有"也认不出来。于是地板又交一次 —— 实测这一交把
    # URL 打回 /search/、query 直接丢失，已经拿到手的结果页被毁掉，任务在预算耗尽时收场。
    # 所以再问一次**页面本身**：URL 的查询参数里已经带着这句 query，就说明这次搜索早跑过了，
    # 该由结果页的技能接管。换了查询词照旧放行（改法只拦"同一句已经提交过的"）。
    typed_toks = set(_tokens(_norm_label(hist[last_fill].get("text") or "")))
    if typed_toks:
        in_url: set = set()
        try:
            for _, _v in parse_qsl(_urlparse(page.get("url") or "").query):
                in_url |= set(_tokens(_norm_label(unquote(_v))))
        except Exception:
            in_url = set()
        if typed_toks <= in_url:
            return None
    # 与 form_submit 同理：提交控件是 button，导航项是 link。自建站点的导航栏就有
    # <a href="search.html">Search</a>，先撞上它会直接离开当前页（实况）。
    cands = {"b_exact": None, "b_loose": None, "l_exact": None, "l_loose": None}
    for index, a in indexed_actions(page.get("actions") or []):
        if a.get("kind") != "click":
            continue
        lab = " ".join(_tokens(a.get("label") or ""))
        if not lab or lab.startswith("open"):
            continue                       # "Open quick search" 之类是开合开关，不是提交
        toks = set(lab.split())
        if not (toks & _SEARCH_SUBMIT_WORDS):
            continue
        key = ("b" if (a.get("role") or "") == "button" else "l") + (
            "_exact" if lab in _SEARCH_SUBMIT_WORDS else "_loose")
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
    for index, a in indexed_actions(page.get("actions") or []):
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
    for index, a in indexed_actions(page.get("actions") or []):
        if a.get("id") in recent:
            continue
        if a.get("kind") == "select":
            return _decision("SELECT", f"{index}:1", a, "select_first")
    for index, a in indexed_actions(page.get("actions") or []):
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
        for index, a in indexed_actions(page.get("actions") or []):
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
    for index, a in indexed_actions(page.get("actions") or []):
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

    scroll 不在 KIND_TO_OP 里，indexed_actions 会把它滤掉，所以这里读原始 actions；
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
    actions = list(indexed_actions(page.get("actions") or []))

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
        # 注意：scroll 不在 KIND_TO_OP 里，indexed_actions 会滤掉它，故这里用原始 actions；
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
        "n_indexed": len(indexed_actions(acts)),
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
            wants = list(goal_phrases(goal))
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
    actions = list(indexed_actions(page.get("actions") or []))
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
    wants = list(goal_phrases(goal))
    m = re.search(r"until\s+(?P<what>[^.;]{3,60}?)\s+(?:are|is|be)\s+visible",
                  goal or "", re.I)
    if m:
        wants.append(m.group("what"))
    if any(w and w.strip().strip("'\"").lower() in text for w in wants):
        return None                        # 已经可见 → 交给 stop_when_visible 收口
    for a in (page.get("actions") or []):
        if a.get("id") == "scroll_bottom" and a.get("kind") == "scroll":
            return _decision("SCROLL_BOTTOM", None, a, "scroll_to_target")


#: "这一拍该由别的技能做"的 goal 动词面：搜索/表单/滚动三类。**词表只收任务文件里
#: 真实出现过的说法**（2026-10-09 对 m1/tasks-laya-19.jsonl + m2/tasks_real.jsonl 的
#: 逐条分类：search/fill/type/write/check/select/choose/submit/press/scroll），
#: 不按要求"所有可能的英文动词"。
_AWAY_VERB_RE = re.compile(
    r"\b(?:search|scroll|fill|type|enter|write|check|select|choose|submit|press)\b", re.I)


def scroll_to_named_target(page: dict, goal: str, history: list) -> dict | None:
    """goal 用引号点名的目标**不在这张首屏**，但页面下方还有内容 → 发一步有界 SCROLL_DOWN。

    与 `scroll_to_target` 的区别：那一支接管"滚到 X 可见"的 goal（字面写了 scroll）；
    这一支接管**没写 scroll 的导航 goal**——r116 实况（2026-10-09，`m2/probe_scroll_reach.py`）：
    doc.rust-lang.org/stable/ 首屏只索引 4 个动作，'The Cargo Book' 那条链在 +1812px
    （文档高 3318px），滚进视口后 `explicit_target` 自己就以 conf 1.0 命中。
    快照只收录视口内动作（snapshot.js:124），所以**给这条链加分数的任何档位都买不到它**
    ——病是视口覆盖，唯一的出路是让页面动。

    为什么排在 `explicit_target` 之后、fill/search 族之前（r116 第一次单任务实测）：
    地板滚动本身生效了（第 1 拍 `skill=scroll_to_named_target`），但第 2 拍滚出的是站内
    搜索框，`search_type` 把导航目标名当成查询词打了进去 →
    `doc.rust-lang.org/stable/std/index.html?search=The%20Cargo%20Book`（FAIL）。
    goal 没要求搜索时，"滚到那条被点名的链"比"把它搜出去"更有据。

    安全性：
      - 只在 `explicit_target` 自己都弃权时才动页面（首屏能看见就不该滚）；
      - goal 含搜索/表单/滚动动词 → 让位（f001/f005/t003/l002/l003 的形状归原来的技能）；
      - `scroll_down` 是快照在**下方确有内容**时才合成的（snapshot.js:157），拿不到控件
        就等于滚不动，这条守卫是免费的（与 goto_path 同一依据）；
      - 有界 `_PATH_SCROLL_MAX`：r105/r122 那样"目标根本不在这一页"的站点最多浪费几拍，
        之后照常交回模型（两页实测滚到 2800px / 滚到底仍不出现目标）；**并且结束时把
        页面滚回顶部**（#47）——不然这一趟会把视口外的原生搜索控件一起带走。
    """
    if _is_scroll_visible_goal(goal) or _AWAY_VERB_RE.search(goal or ""):
        return None
    # 只接管 goal 里**用引号点名**的目标（r116 的形状）。`goal_phrases` 还会返回介词尾巴
    # （"… on the site" → "the site"），那种短语在页面上到处都是，为它滚是纯噪声；
    # 路径类短语（/forms/post）已由 goto_path 自带同样的有界滚动，也不重复接管。
    quoted = {m.group(1) for m in re.finditer(r"['\"]([^'\"]{2,60})['\"]", goal or "")}
    phrases = [p for p in goal_phrases(goal) if not p.startswith("/") and p in quoted]
    if not phrases:
        return None
    if explicit_target(page, goal, history) is not None:
        return None                        # 目标已在首屏，那一档的活
    scrolls = [h for h in (history or []) if h.get("kind") == "scroll"]
    down = _scroll_ctl(page, "down")
    if down is not None and len(scrolls) < _PATH_SCROLL_MAX:
        return _decision("SCROLL_DOWN", None, down, "scroll_to_named_target")
    # 单向门守卫（#47，r114 在 b15 的死法）：campaign 结束了（滚不动了，或者预算用完了）
    # 却没把目标滚进索引集，这一趟不是"多花 4 拍"——快照只收录**视口内**的动作
    # （snapshot.js:124），滚下去之后页头的原生搜索框就不在 actions 里了。
    # `m2/probe_scroll_cost.py`（零模型，2026-10-09 17:1x 跑两遍一致）逐拍实测 django 首页：
    # y=0 `fills=['Search']` 且 `search_type` 开火，y≥560 `fills=NONE`、`search_type`
    # 全程 None —— b14 靠 search_type 两步通关的出路，是被这个 campaign 自己滚出视口的
    # （目标链在 y=1120 确实出现，但 goal 写 'Writing your first Django app, part 1'
    # 而链接写 "Write your first Django app"，词重叠 3/6 → `explicit_target` 认不出，
    # 所以"少滚两拍"救不了它）。页面在滚下去之后仍然给得到回顶控件（同探针实测
    # undo available: True），所以这扇门是产品自己关的：**还一次**，把那一拍还回给
    # `search_type`。只还一次（还过的 campaign 不再说话，不许来回滚）；两种"没有欠下的门"
    # 的情况也不多花那一拍：首屏本来就滚不动的页面，以及**已经交过棒**的页面
    # ——目标一旦被滚进索引集，`explicit_target` 就接管了（r116 实测第 4 拍），后面
    # 若还有滚动是别人的战役，由 `scroll_to_target`/`goto_path` 自己收口（⑦ 对照）。
    if not scrolls or any(h.get("skill") == "explicit_target" for h in (history or [])):
        return None
    if any(re.search(r"\b(up|top)\b", (h.get("action") or "").lower()) for h in scrolls):
        return None
    ctl = _scroll_ctl(page, "top") or _scroll_ctl(page, "up")
    if ctl is None:
        return None
    # op 名必须是控件 id 的大写（decision_validator 用 controls[action.id.upper()]
    # 反查 expected_choice，:181），所以这里不写死 SCROLL_UP。
    return _decision(ctl["id"].upper(), None, ctl, "scroll_to_named_target")



# ---------------------------------------------------------------------------
# 2c. 标识 goal、无候选、页面下方还有内容 → 一次 SCROLL_BOTTOM（t6 / r105）
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# 2c. 标识 goal 在仓库页上、目标链接在折叠线下 → 一次 SCROLL_DOWN（t6 / r105）
# ---------------------------------------------------------------------------

def repo_scroll_target(page: dict, goal: str, history: list) -> dict | None:
    """goal 明写 repository 且**当前就在该仓库页**、目标链接全在折叠线下 → 滚一步。

    病家（t4 实测，m2/shape_5rows_2026-10-17.md E 段）：r105 的 repo 页
    /pytorch/pytorch 上有 3 条 /pytorch/pytorch/releases 链，全在 +894..984px ——
    780px 视口折叠线下，快照只索引视口内动作（snapshot.js:124），explicit_target
    结构性够不到；而 goal 的短语集只有标识 pytorch/pytorch（tests/test_phrases_ident.py
    ① 钉死），没有任何档位能替它把页面滚过去。一步 SCROLL_DOWN（560px）之后链接落进
    视口（334..424px），模型与 explicit_target 都重新拿得到它。

    为什么是 SCROLL_DOWN 一步而不是 scroll_bottom：GitHub repo 页文档很高，
    滚到底会把 +894..984px 的链接甩到视口**上方**去；实测几何只支持一步 560px。
    发火窗口也由该几何给出：滚一步后可见 ⇔ y+560 ≤ 894 ⇔ y ≤ 334。

    安全性（每条都有反面形状）：
      - 只认 _REPO_CTX_RE + 标识出现在**当前 URL 路径**里：接管面收在"已到仓库页"
        这一个实测状态上，首页照旧走原路径（不新增回归面）；
      - URL 路径已含目标段（到达页）→ 弃权，goal_reached 的收口面不抢；
      - 目标链接已在索引集（href/label 命中标识 + goal 目的地词）→ 弃权，
        explicit_target 的拍不抢（r116 交接形状）；
      - explicit_target 自己开火 → 弃权；
      - 有界：历史里有本技能 → 永不再发（一发即收，无效果由 _STUCK 退避兜底）；
      - goal 目的地词取自 **goal 自己的字面词**（Releases），不是站点词表
        （handover §7：不添词表）。
    """
    idents = _repo_ident_phrases(goal or "")
    if not idents:
        return None
    try:
        path = (_urlparse(page.get("url") or "").path or "").lower()
    except Exception:
        return None
    # 只在"当前就在 goal 点名的那个仓库页"上接管（t4 E 段的实测状态）
    if not any(p.lower() in path for p in idents):
        return None
    # 已经在目标子页上（URL 已含 goal 的目的地词）→ 到达页不动
    hist = history or []
    dest_toks = [t for t in _content(goal or "")
                 if t not in {x for p in idents for x in _tokens(p)}]
    if any(t in path for t in dest_toks):
        return None
    # 有界：滚过一次就永不再发
    if any(h.get("skill") == "repo_scroll_target" for h in hist):
        return None
    idx = indexed_actions(page.get("actions") or [])
    # 目标链接已进索引集 → explicit_target 的活，弃权
    for _i, a in idx:
        if a.get("kind") != "click":
            continue
        hay = ((a.get("href") or "") + " " + (a.get("label") or "")).lower()
        if any(p.lower() in hay for p in idents) and any(t in hay for t in dest_toks):
            return None
    # explicit_target 自己开火 → 它的拍，弃权
    if explicit_target(page, goal or "", hist) is not None:
        return None
    # 实测发火窗口：一步 560px 后链接可见 ⇔ y ≤ 334（链接在 +894..984、视口 780）
    if ((page.get("scroll") or {}).get("y") or 0) > 334:
        return None
    down = _scroll_ctl(page, "down")
    if down is None:
        return None
    return _decision("SCROLL_DOWN", None, down, "repo_scroll_target")


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
    r"""goal 说"打开第一个结果" → 在结果页上点第一个结果链接，点了且跳转即收口。

    s011 实况："Search for 'data flywheel' and open the first result link." ——
    goal 里的短语是**搜索词**（就写在 ?q= 里），explicit_target 只会按短语匹配标签，
    无从下手；而"第一个结果"是**位置**规则，可以确定性执行。
    取"搜索输入框之后"的第一个链接：站点导航总在顶部（在搜索框之前），结果列表在后面。

    触发词表是真实站教的（2026-10-07 批次 1 复跑），见 `_FIRST_RESULT_RE`：原写法
    `(first|top)\s+(result|...)` 要求名词**紧挨着**，而真实 goal 会说 "open the
    **first research article**"（r104）或 "open the **first question**"（r103）——中间
    隔了修饰语、名词也不在表里，于是技能根本不触发，页面已经到了结果页却直接 BLOCKED。

    词表补上后，批次 4 教了第二课（H 类）：**光"填过搜索框"不等于在结果页上**。
    r103 填完框、还没提交，first_result 就抢在 search_submit 前面开火，连点四次页脚
    "Help Center and other resources"；r104 同理点了自动补全的 chip，再点 Advanced，
    最后发 DONE 被 guard 否决。所以闸门是"那次 fill **之后**出现过 url_changed"——
    搜索提交成功才会跳页，跳了页才是结果页。

    b18 的 r104 教了第三课（#52）：**跳了页也不等于那条链接是结果**。搜索链两拍全对、
    终页就是 `?term=CRISPR+off-target` 结果页，"搜索框之后第一个可点标签"却落在页眉
    'Advanced' 上（快照 `m2/fixtures/r104_pubmed_results.json`：引文行在位置 26/28，
    href 是相对的 `/36970624/`；它们前面排着 20 多条页壳与翻页控件）。所以选行改成
    **先筛"是结果的"，再按位置取第一个**：goal 内容词重合最高的候选赢，**同分保持
    先出现的**（"第一个结果"的位置规则没有被丢掉，只是加了一层资格筛选）。重合全为 0
    时退回原规则（第一个可点标签）——s011/r103 的形状里结果标题就是不含搜索词，
    那条路不能断。

    为什么翻页控件抢不走：'Navigates to the first page of results.' 与 goal 只重合
    'first' 一词（'page'/'article'/'search'/'open' 都在 STOPWORDS 里），引文行重合
    'crispr'+'off'+'target' 三词。
    """
    if not _FIRST_RESULT_RE.search(goal or ""):
        return None
    hist = history or []
    # 已经点过且页面确实跳转过 → 到达，收口（否则 DoneGuard 会一直否决 DONE：
    # goal 的短语是搜索词，目标页上根本不含它，goal_reached 永远为 None）
    for h in reversed(hist):
        if h.get("skill") == "first_result":
            if (h.get("outcome") or {}).get("url_changed"):
                return _decision("DONE", None, None, "first_result")
            break
    fill_at = next((i for i, h in enumerate(hist)
                    if h.get("kind") == "fill"
                    and _searchbox({"label": h.get("action") or ""})), None)
    if fill_at is None:
        return None                        # 还没搜过 → 不是结果页
    if not any((h.get("outcome") or {}).get("url_changed") for h in hist[fill_at:]):
        return None                        # 填了但没提交 → 还不是结果页（H 类）
    goal_tokens = {_stem(t) for t in _content(goal or "")}
    seen_input = False
    first = None                           # 兜底用：搜索框之后的第一个可点标签
    best = None
    best_overlap = 0
    for index, a in indexed_actions(page.get("actions") or []):
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
        if first is None:
            first = (index, a)
        overlap = _goal_overlap(a, goal_tokens)
        if overlap > best_overlap:         # 同分保持先出现的 = "第一个结果"的位置规则
            best, best_overlap = (index, a), overlap
    chosen = best or first
    if chosen is None:
        return None
    return _decision("CLICK", chosen[0], chosen[1], "first_result")


# 顺序即优先级。search_submit 放最后：机票页要先填完 from/to/日期/票种再提交。
# scroll_to_named_target 紧跟 explicit_target：目标在首屏就点它，不在首屏就先让页面动，
# 再往下才轮到 fill/search 族（r116 第一次单任务实测：晚一步就被站内搜索框拐走）。
# repo_scroll_target 紧随其后：goal 明写 repository 且已在仓库页、目标链接全在折叠线下
# 时滚一步（t6/r105 实测几何）；排在 explicit_target 之后 = 它开火就让位。
SKILLS = (blocked_dead_page, page_not_ready, goal_reached, link_followed_arrival,
          stop_when_visible,
          confirm_then_done, scroll_to_target, first_result,
          goto_path, explicit_target, scroll_to_named_target, repo_scroll_target,
          select_option,
          form_fill, form_submit, entity_fill, entity_confirm,
          trip_type, search_type, select_first, date_pick, search_submit)


#: `first_result` 的触发词表：形状是 "first/top + 至多 3 个修饰词 + 结果名词"。
#: 每一项都有真实 goal 背书（2026-10-07 批次 1 复跑）：
#:   s011 "open the first result link"        → 名词紧挨着（旧写法唯一能匹配的形状）
#:   r104 "open the first research article page" → first 与 article 之间隔了 research
#:   r103 "open the first question in the results" → 名词是 question，旧词表里没有
#: 名词只收**见过的**，不许按想象扩充（Fix D 的教训：猜进去的词表后来全删了）。
#: 标点会挡住 `(?:[\s-]+\w+)` 的延续，所以 "First, fill the form…" 不会误触发；
#: "first name … click the link" 也不会（first 与 link 之间隔了 4 个词，超过 3 上限）。
_FIRST_RESULT_RE = re.compile(
    r"\b(?:first|top)(?:[\s-]+\w+){0,3}?[\s-]+"
    r"(?:result|link|article|item|question)\b",
    re.I)

#: 一页态的停用记录：`{"task": 写笔记那一题的标签, "ticks": {技能名: 剩余拍数}}`。
#: `task` 与 `ticks` 在**同一张表里**（#72 的教训：一个概念一张表；两张表一定会漂开）。
_STUCK: dict[str, dict] = {}

#: #83 的前置仪器 —— **只数，不改判据**。
#: 为什么要数：`_STUCK` 是模块级字典、键是页态指纹、**任务之间不清洗**，
#: 而夜间档 r3 实测一轮 100 题里 111 个不同指纹有 25 个被 >1 个任务共用（最多 6 个题共用一个）
#: ⇒ 第 N 题写的"让位"笔记可以在第 N+1 题的前两拍把技能按住，这是一条**跨任务通道**。
#: 100 行批（`reports/tier3-100-1014-105704.json`）的第一份读数把两件事分开了：
#: **带进场**（`entries_at_start>0`）= 61/100 行，但**被按住**（`suppressed>0`）= 1 行，
#: 而那唯一一次发生在写笔记的同一题（r140）里 ⇒ "进场"不等于"受害"，#83 要的是后者。
#: 所以这里再数一个 `cross_task`：抑制发生时，笔记不是本题写的。
#: 为什么是计数器而不是 trace 事件：技能层拿不到 logger（只吃 page/goal/history），
#: 给 `route()` 加一个事件写出参就是行为变更 —— 所有调用点都要动。
_STUCK_NOTES = 0
_STUCK_SUPPRESSED = 0
_STUCK_CROSS_TASK = 0
_STUCK_TASK = ""


def set_current_task(task_id: str) -> None:
    """runner 每题开始时告知技能层"现在是谁"，用来把跨题抑制数出来。

    这只影响计数标签，不影响任何判据：`route()` 的产出与这行调不调用**无关**。
    """
    global _STUCK_TASK
    _STUCK_TASK = task_id or ""


def stuck_counters() -> dict:
    """公开读数（runner 与测试都走这一个，不许伸手进私有）。

    - `entries`：还活着的页态条目数（runner 在每题**进场前**读 ⇒ 大于 0 = 带着上一题的笔记进场）；
    - `suppressed`：抑制发生了多少次（不管笔记是谁写的）；
    - `cross_task`：其中有多少次的笔记**不是本题写的** —— 这一格才是 #83 的决策量。
    """
    return {"notes": _STUCK_NOTES, "suppressed": _STUCK_SUPPRESSED,
            "cross_task": _STUCK_CROSS_TASK, "entries": len(_STUCK)}


def stuck_ticks(page_fingerprint: str) -> dict:
    """这一页态上还剩谁的停用拍数。**读接口**：测试与探针从这里读，不许再手抄内层形状。

    为什么要单开这个函数（今天现演的一次）：把内层从 `{技能: 拍数}` 改成
    `{"task":…, "ticks":{…}}` 时，`tests/test_skills.py` 里那处直接塞字典的用例立刻 77/78 红 ——
    那就是"伸手进私有形状"的代价。有了读接口，形状归形状，用例走用例。
    """
    return dict((_STUCK.get(page_fingerprint) or {}).get("ticks") or {})


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
    global _STUCK_NOTES
    _STUCK_NOTES += 1
    entry = _STUCK.setdefault(page_fingerprint, {"task": "", "ticks": {}})
    entry["task"] = _STUCK_TASK            # 谁写的笔记：跨题抑制就靠这一格判
    entry["ticks"][skill] = _STUCK_TICKS


def route(page: dict, goal: str, history: list) -> dict | None:
    """按精度优先级依次尝试；命中即返回 decision，全部未命中返回 None（回落模型）。

    缺陷#18 闸门：技能产出的 decision 必须过 DecisionValidator 才放行。
    确定性技能 + 非法决策 = 每次重导出同一决策 → 循环检测直接 blocked；
    非法即回落模型（模型至少会换一个选择）。
    """
    from .decision_validator import validate as _validate
    # 有界退避：每拍把剩余停用拍数减一，减到 0 就把技能放回来（见 note_no_effect）。
    global _STUCK_SUPPRESSED, _STUCK_CROSS_TASK
    fp = page.get("fingerprint") or ""
    entry = _STUCK.get(fp)
    stuck = (entry or {}).get("ticks") or {}
    for _name in list(stuck):
        stuck[_name] -= 1
        if stuck[_name] <= 0:
            del stuck[_name]
    if not stuck:
        _STUCK.pop(fp, None)
    for fn in SKILLS:
        if not _enabled(fn.__name__):
            continue
        if stuck.get(fn.__name__, 0) > 0:
            _STUCK_SUPPRESSED += 1            # 只数（#83 的前置仪器），控制流一字不动
            if _STUCK_TASK and (entry or {}).get("task") not in ("", _STUCK_TASK):
                _STUCK_CROSS_TASK += 1        # 笔记不是本题写的 —— 这才是 #83 要的那一格
            continue
        try:
            d = fn(page, goal, history or [])
        except Exception as e:             # noqa: BLE001
            # 行为一字不改（仍然回落模型），但留下"哪个技能、抛了什么"这一行（#68）。
            dbg("skill_raised", f"{fn.__name__}: {type(e).__name__}: {str(e)[:120]}")
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
