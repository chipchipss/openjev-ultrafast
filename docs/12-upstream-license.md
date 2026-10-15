# 上游许可归档（#77 第一件）

日期：2026-10-13。动机不是礼节：`README.md` 的 License 一节写的是「MIT —— 继承自 jev-ultrafast」，
而仓里从来没有那份"继承"的原文；`docs/00-project-plan.md:6` 与 `docs/01-hard-rules.md` 的 **H3**
把基座决策写成「Fork jev-ultrafast（MIT）」。既然定位是 fork 出来的分发物，MIT 的条件句
（"The above copyright notice and this permission notice shall be included in all copies"）
要求**上游那份告示必须跟着走**——归档之前，我们只在 README 里口头声称继承，没有可核对的原文。

## 取文与核证（命令贴着结论）

```
curl -x http://127.0.0.1:2080 -H "Accept: application/vnd.github.raw" \
     https://api.github.com/repos/browser-use/jev-ultrafast/contents/LICENSE
```

| 项 | 值 |
|---|---|
| 上游仓库 | `browser-use/jev-ultrafast`（description: "Fastest and cheapest web agent"） |
| 取文时刻的 default branch 头 | `1231850a0bf1a0c0341fe408ef1668dbbfdfac46`（committer date 2026-09-18T16:28:35Z） |
| 抓取日期 | 2026-10-13（经操作者的出口代理 `http://127.0.0.1:2080`） |
| LICENSE 字节数 | 1068 |
| LICENSE sha1 | `c5f3915d649ae54b48ee19644ce502065968be1b` |
| `/repos` 元数据里的许可 | `{"key":"mit","spdx_id":"MIT","name":"MIT License"}` |

两条独立来源对上（元数据 API 说 MIT，原文首行也是 `MIT License`），所以这份归档不是从网页抄的。

**逐文件对应关系：2026-10-15 起有实测了**（`m2/census_file_provenance.py`；比的是上游今天的 git 树，
tree sha `1231850a0bf1a0c0341fe408ef1668dbbfdfac46`、40 个 blob、`truncated=False`，与本仓
`git ls-files -s` 的索引 blob sha 逐路径对，两边同一算法 ⇒ 不需要下载内容就能判同不同）：

| 类 | 数 | 是哪批 |
|---|---|---|
| 与上游**逐字节相同** | **7** | `jev_ultrafast/__init__.py`、`demo.py`、`questions.py`、`static/app.js`、`static/fixture.html`、`static/index.html`、`static/style.css` |
| 同路径、内容不同 | **9** | `.env.example`、`.gitignore`、`LICENSE`、`README.md`、`jev_ultrafast/agent.py`、`browser.py`、`model.py`、`snapshot.js`、`pyproject.toml` |
| 我们独有（sha 不等于任何上游 blob） | **731**（跟踪文件共 747） | 测试、探针、题集、runner、文档、报告 |

**这条实测把两件旧说法的性质改了**：
1. 「发布要带上游告示」不再只是礼节问题——本仓里确有 7 个文件是上游原文、我们一行没改。
   而 `LICENSE` 全文 21 行、只有 `Copyright (c) 2026 chipchipss` **一条**告示（`grep -c Copyright LICENSE` = 1），
   上游原文目前只在本文档里。把告示并进 `LICENSE` / 加 `NOTICE` / 维持"归档文件随快照走"三种都能做，
   **这个形状选择仍归操作者**（#77 当年挂起的那件事，现在有数垫着了）。
2. **仍然没核证的**：那 9 个"同路径不同内容"里，哪些是**我们**改的、哪些是**上游后来**改的——
   比的是上游今天的树，两种事实混在一起，分开要上游历史（`/commits?path=`）。
   仓内文档也没留下 fork 的 commit。所以"基座 = fork"这句话依旧不许被上面这张表升级成结论。

## 上游 LICENSE 原文（逐字）

```
MIT License

Copyright (c) 2026 Browser Use

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## 对本仓的约束与一件没做的事

- 本仓 `LICENSE`（© 2026 chipchipss，MIT）覆盖的是**我们自己写的那部分**；上面这份原文覆盖
  Runtime 基座。发布（`sdist`/`wheel`/仓库快照）时两者都要在仓里带着走——这也是这份文件存在的理由：
  原文进了版本库，就不再依赖任何人的记忆。
- **没动 `LICENSE` 本体**：把上游告示并进 `LICENSE`、还是保留"我们的 LICENSE + 归档文件"这种形状，
  是发布形态的选择，不是技术活，归操作者定（`pyproject.toml` 的 `license = "MIT"` 两种形状都成立）。
- `pyproject.toml` 的 `license` 元数据若要对外声明"derived from"，需要的是同一份依据；那条与上面
  "逐文件对应关系未核证"一起处理，别先写漂亮话。
