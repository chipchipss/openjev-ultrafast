"""Fix V 回归：goal 里**不带引号**的 `org/repo` 标识不能被读成路径 `/pytorch`（r105 实测，2026-10-09）。

病家（`m2/probe_r105_shape.py` 的 D/E 两段，零模型，真页复现；本文件用同形合成页离线复现）：
  `_phrases("Open the Releases page of the pytorch/pytorch repository.")` 返回 `['/pytorch']`
  ——路径正则 `(/[\\w\\-/.]{2,40})` 从**词中间**那个斜杠开始吃。
  后果一（D 段）：仓库搜索结果页上地板点**组织名单元格** `pytorch`（href `/pytorch`，label 与
  短语逐字相同 → 精确档 2.0），而不是仓库行 `pytorch/pytorch`。
  后果二（E 段）：仓库页上 `host_hit` 把站外 `pytorch.org` 抬到 3.0+ → 地板**跳出任务域名**。

四格各管一件事，每一格都有"只做前面几格仍然失败"的实测（见 real-log 的 Fix V 小节）：
  ① `_phrases`：认标识、并抑制落在标识跨度内的路径读法；
  ② `explicit_target`：这一档短语**只认站内候选**（相对 href 或同 host）——治越域；
  ③ `goal_reached`：这一档短语**不作到达证据**——`/pytorch/pytorch` 只是仓库根，
     goal 还要 `Releases`；少了这一格就会在仓库根提前 DONE（= false positive）；
  ④ `_goal_query`：这一档短语**不派生成搜索词**——实测派生出来之后 `first_action_floor`
     会把 `pytorch/pytorch` 打进页脚订阅邮箱框（比 b16 的空点击更糟）。开框/选框是下一刀。

这一档只在 goal 明写 repository/repos 时启用（`_REPO_CTX_RE`），所以全场 101 题里**只有
r105 的短语集发生变化**；r106/r119 的带引号 id 走原有引号档，本文件逐字钉住它们的短语表。

运行：python tests/test_phrases_ident.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jev_ultrafast import skills as S  # noqa: E402

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


GOAL = "Open the Releases page of the pytorch/pytorch repository."
R106_GOAL = "Search Hugging Face for 'ggml-org/Llama-2-7B-GGUF' and open the model page."
R119_GOAL = ("Search Hugging Face for 'bert-base-uncased' and open the model page "
             "'google-bert/bert-base-uncased'.")


def page(url, title, labels, start="https://github.com/"):
    acts = [{"id": f"e{i}", "kind": "click", "node": i, "role": "link",
             "label": lab, "href": href, "value": ""}
            for i, (lab, href) in enumerate(labels, 1)]
    return {"url": url, "title": title, "start_url": start, "text": "",
            "scroll": {"y": 0, "height": 3000}, "actions": acts}


def pick(p, goal=GOAL):
    """explicit_target 的落点 (choice, label)，弃权时返回 None。"""
    d = S.explicit_target(p, goal, [])
    if d is None:
        return None
    return d["choice"], next(a["label"] for a in p["actions"] if a["id"] == d["choice"])


REPO_ROOT = page("https://github.com/pytorch/pytorch",
                 "GitHub - pytorch/pytorch: Tensors and CUDA operations",
                 [("pytorch", "/pytorch"), ("pytorch.org", "https://pytorch.org/"),
                  ("Code", "/pytorch/pytorch"), ("Issues", "/pytorch/pytorch/issues")])
SEARCH = page("https://github.com/search?q=pytorch%2Fpytorch&type=repositories",
              "Repository search results · GitHub",
              [("pytorch", "/pytorch"), ("pytorch/pytorch", "/pytorch/pytorch")])
ONLY_OFFSITE = page("https://github.com/pytorch/pytorch",
                    "GitHub - pytorch/pytorch: Tensors and CUDA operations",
                    [("pytorch.org", "https://pytorch.org/"), ("Watch", "/login")])
RELEASES = page("https://github.com/pytorch/pytorch/releases",
                "Releases · pytorch/pytorch", [("pytorch/pytorch", "/pytorch/pytorch")])


# --------------------------------------------------------------------------- ①
@case("① goal 里的 org/repo 读成标识，不读成词中斜杠的路径")
def t_phrases():
    got = S._phrases(GOAL)
    assert got == ["pytorch/pytorch"], f"_phrases={got!r}（修复前 ['/pytorch']）"


@case("① 明写路径的 goal 不受影响（f001/f002/f004/t001 的形状）")
def t_explicit_path_still_path():
    goal = "Go to /forms/post and fill the customer name field with 'Test User'."
    got = S._phrases(goal)
    assert got == ["/forms/post"], f"_phrases={got!r}"


@case("① 带引号的 id 保持逐字不变（r106/r119 是 PASS 题，一格都不许动）")
def t_quoted_ids_pinned():
    assert S._phrases(R106_GOAL) == ["ggml-org/Llama-2-7B-GGUF", "/Llama-2-7B-GGUF"]
    assert S._phrases(R119_GOAL) == ["bert-base-uncased",
                                     "google-bert/bert-base-uncased",
                                     "/bert-base-uncased"]


# --------------------------------------------------------------------------- ②
@case("② 搜索结果页点仓库行，不点组织名单元格（探针 D 段）")
def t_search_row():
    got = pick(SEARCH)
    assert got == ("e2", "pytorch/pytorch"), f"落点={got}（修复前 ('e1','pytorch')）"


@case("② 仓库页不再被站外 pytorch.org 劫持（探针 E 段）")
def t_no_offsite_on_repo_root():
    got = pick(REPO_ROOT)
    assert got is None or got[1] != "pytorch.org", f"落点={got}（修复前 ('e2','pytorch.org')）"


@case("② 页面上只有站外候选时弃权，而不是跳出域名")
def t_offsite_only_abstains():
    got = pick(ONLY_OFFSITE)
    assert got is None, f"落点={got}（修复前 ('e1','pytorch.org')）"


@case("② 带引号 id 在同站结果页照旧命中（r106/r119 的执行面）")
def t_quoted_id_same_host_still_fires():
    hf = page("https://huggingface.co/search/full-text?q=ggml-org%2FLlama-2-7B-GGUF",
              "Search results · Hugging Face",
              [("ggml-org/Llama-2-7B-GGUF", "https://huggingface.co/ggml-org/Llama-2-7B-GGUF"),
               ("Other model", "https://huggingface.co/some/other")],
              start="https://huggingface.co/")
    assert pick(hf, R106_GOAL) == ("e1", "ggml-org/Llama-2-7B-GGUF")


HIST = [{"kind": "click", "choice": "e9", "url": "https://github.com/", "page_fp": "x"}]
HF_HIST = [{"kind": "click", "choice": "e9", "url": "https://huggingface.co/", "page_fp": "x"}]


# --------------------------------------------------------------------------- ③
@case("③ 仓库根不是到达证据（少了这格就会提前 DONE = false positive）")
def t_repo_root_not_arrival():
    assert S.goal_reached(REPO_ROOT, GOAL, HIST) is None, "仓库根被 identifier 判成已到达"


@case("③ 带引号 id 仍是到达证据（r106 的收口面不动）")
def t_quoted_id_still_arrival():
    hf = page("https://huggingface.co/ggml-org/Llama-2-7B-GGUF",
              "ggml-org/Llama-2-7B-GGUF · Hugging Face",
              [("Files", "https://huggingface.co/ggml-org/Llama-2-7B-GGUF/tree/main")],
              start="https://huggingface.co/")
    d = S.goal_reached(hf, R106_GOAL, HF_HIST)
    assert d is not None and d["skill"] == "goal_reached", "带引号 id 的到达判据被打断"


# --------------------------------------------------------------------------- ④
@case("④ identifier 不派生成搜索词（否则 floor 把它打进页脚邮箱框）")
def t_no_derived_query():
    assert S._goal_query(GOAL) is None, f"_goal_query={S._goal_query(GOAL)!r}"


@case("④ floor 不会把标识打进非搜索框（探针 A 段：首页唯一可 fill 的是页脚邮箱框）")
def t_floor_does_not_type_ident_into_email():
    home = {"url": "https://github.com/", "title": "GitHub", "start_url": "https://github.com/",
            "text": "", "scroll": {"y": 0, "height": 10818},
            "actions": [{"id": "e1", "kind": "click", "node": 1, "role": "button",
                         "label": "Search or jump to, type / to search", "href": ""},
                        {"id": "e2", "kind": "fill", "node": 2, "role": "textbox",
                         "label": "Enter your email", "value": ""}]}
    d = S.first_action_floor(home, GOAL, [])
    assert not (d and d["operation"] == "TYPE_TEXT"), \
        f"floor 把派生出来的搜索词打进了邮箱框：{d}"


@case("④ 引号串照旧派生成搜索词（search_type 的活路不动）")
def t_quoted_query_still_derives():
    assert S._goal_query(R106_GOAL) == "ggml-org/Llama-2-7B-GGUF"


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[attr-defined]
    except Exception:                                                # noqa: BLE001
        pass
    failed = 0
    for name, fn in CASES:
        try:
            fn()
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {name}\n      {e}")
        except Exception as e:                                       # noqa: BLE001
            failed += 1
            print(f"ERROR {name}\n      {type(e).__name__}: {e}")
        else:
            print(f"ok    {name}")
    print(f"\n{len(CASES) - failed}/{len(CASES)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
