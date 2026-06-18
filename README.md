# 交互式 AI 新闻 Agent

这是一个纯命令行运行的 AI 新闻助手。用户启动 `ai-news start` 后，不需要记复杂参数，只要像聊天一样说明想看的新闻；DeepSeek 会先追问并补齐主题、时间范围和新闻数量，然后通过本地 MCP tools 获取真实新闻上下文，最后在终端直接输出中文新闻摘要。

项目的重点不是做一个固定格式的新闻日报，而是展示一个能“对话收集需求 -> 自主调用工具 -> 整合外部上下文 -> 输出结果 -> 缓存完整过程”的单一用途 Agent。

## 主要能力

- 交互式 CLI：运行 `ai-news start` 后进入连续对话，输入 `exit`、`quit` 或 `q` 退出。
- DeepSeek 引导提问：当用户没有说明时间范围或新闻数量时，模型会先追问，不会直接编默认值。
- 本地 MCP Server：把新闻检索、论文检索、网页抽取、去重排序封装成可调用工具。
- 多来源新闻上下文：默认接入 RSS/Atom、arXiv 和 Hacker News Algolia API。
- Tool Calling 流程：DeepSeek 通过 OpenAI-compatible tools 格式规划工具调用，程序执行本地 MCP tools 并把结果回填给模型。
- 终端自然语言输出：不再生成 Markdown 日报文件，结果直接作为对话消息展示。
- JSONL 对话缓存：完整记录用户输入、模型追问、结构化请求、tool call、tool result、最终回答和错误事件。
- Mock LLM 演示模式：没有 DeepSeek API key 时，也可以用 `--mock-llm` 演示工具链和缓存流程。

## 项目结构

```text
.
├── src/ai_news/
│   ├── cli.py                  # Typer CLI 入口：start、doctor、sources、history 等命令
│   ├── agent.py                # Agent 编排逻辑：intake、MCP tool loop、缓存写入
│   ├── deepseek_client.py      # DeepSeek 客户端、system prompt、tool schema
│   ├── mcp_server.py           # 本地 FastMCP server，对外暴露新闻 tools
│   ├── tools.py                # RSS/arXiv/HN/正文抽取/去重排序的具体实现
│   ├── models.py               # Pydantic 数据模型
│   ├── config.py               # 默认数据源、模型、路径配置
│   └── conversation_cache.py   # JSONL 会话缓存
├── tests/                      # 单元测试和 CLI smoke tests
├── docs/prompts.md             # Vibe Coding 过程中的关键提示词记录
├── report/experiment-report.md # 实验报告草稿
├── cache/conversations/        # 运行后生成的对话缓存，未提交也可复现查看
└── logs/agent.log              # 运行日志
```

## 安装与配置

建议使用 Python 3.11 或更新版本。

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
cp .env.example .env
```

然后在 `.env` 中填入 DeepSeek API key：

```bash
DEEPSEEK_API_KEY=your-api-key
AI_NEWS_MODEL=deepseek-v4-pro
```

默认 DeepSeek 配置：

```text
Base URL: https://api.deepseek.com
Model: deepseek-v4-pro
```

`DEEPSEEK_API_KEY` 不要写进代码或提交到仓库。没有 key 时可以使用 `--mock-llm` 进行本地演示。

## 快速开始

先检查环境：

```bash
ai-news doctor
```

查看默认数据源：

```bash
ai-news sources
```

启动交互式新闻助手：

```bash
ai-news start
```

示例对话：

```text
AI 新闻助手已启动。你可以直接描述想看的 AI 新闻；输入 exit、quit 或 q 退出。
会话缓存：cache/conversations/interactive-20260618-143000.jsonl

你> 我想看 AI 模型发布相关的新闻
助手> 你想看过去多久的新闻？希望几条？

你> 今天 5 条
助手> 已了解，我会查询过去 24 小时内与“AI 模型发布相关的新闻”相关的 5 条新闻。
助手> 正在调用 MCP tools 检索新闻...

1. ...
   来源：...
   时间：...
   摘要：...
   重要性：...
   链接：...
```

本地演示模式：

```bash
ai-news start --mock-llm
```

Mock 模式不会调用 DeepSeek，但仍会调用 MCP tools、获取外部新闻上下文并写入缓存，适合课堂演示或无 key 环境。

## 常用命令

```bash
ai-news start
ai-news start --mock-llm
ai-news doctor
ai-news sources
ai-news history --session interactive-YYYYMMDD-HHMMSS --limit 20
```

仍保留一个 legacy 单轮命令，主要用于测试或 cron 场景：

```bash
ai-news chat "今天 AI 新闻有哪些？" --hours 24 --top-k 5
```

交互式版本是推荐使用方式，因为它能让模型在对话中主动收集缺失信息。

## 工作流程

一次完整查询大致分为两个阶段。

第一阶段是 intake，也就是需求收集：

```text
用户自然语言输入
  -> DeepSeek 判断是否已具备主题、时间范围、新闻数量
  -> 信息不足时继续追问
  -> 信息齐全时调用 submit_news_request
  -> Agent 得到结构化请求 {question, hours, top_k}
```

第二阶段是新闻检索和总结：

```text
结构化请求
  -> DeepSeek 规划 MCP tool calls
  -> 本地 MCP server 执行 RSS / arXiv / HN / 正文抽取 / 去重排序
  -> Agent 将 tool results 回填给 DeepSeek
  -> DeepSeek 基于真实工具结果生成中文编号新闻摘要
  -> Agent 写入 JSONL 会话缓存
```

模型被 system prompt 约束为：不能凭模型记忆编造新闻、链接、日期或引用；广义 AI 新闻问题至少应调用两个外部来源工具，再调用正文抽取和去重排序。

## MCP Tools

本项目通过本地 FastMCP server 暴露以下工具：

| Tool | 作用 |
| --- | --- |
| `fetch_rss_items` | 从 RSS/Atom 源抓取 AI 公司动态和 GitHub release 信息 |
| `search_arxiv_papers` | 查询 arXiv 最近的 AI、ML、NLP 论文 |
| `search_hackernews_stories` | 查询 Hacker News 上的 AI、LLM、MCP、Agent 相关讨论 |
| `extract_article_text` | 抽取新闻网页正文，失败时回退到摘要 |
| `deduplicate_and_rank` | 基于 URL、标题相似度、来源权重和关键词进行去重排序 |

默认数据源包括：

```text
https://openai.com/news/rss.xml
https://github.com/openai/openai-python/releases.atom
https://github.com/modelcontextprotocol/python-sdk/releases.atom
https://export.arxiv.org/api/query
https://hn.algolia.com/api/v1/search_by_date
```

这些工具也对应实验中“两个及以上 functional skills”的要求。当前实现至少覆盖外部新闻检索、论文检索、社区讨论检索、网页正文抽取、去重排序和对话缓存等多个技能。

## 输出与缓存

程序不会再生成 `outputs/digests/*.md` 形式的日报文件。新闻结果会直接输出到终端，同时完整过程会追加到 JSONL 缓存：

```text
cache/conversations/{session_id}.jsonl
logs/agent.log
```

常见缓存事件类型：

| Event | 含义 |
| --- | --- |
| `intake_user` | 用户在需求收集阶段的输入 |
| `intake_assistant` | 模型对缺失信息的追问 |
| `intake_request` | 模型提交的结构化查询请求 |
| `tool_call` | Agent 准备调用的 MCP tool 和参数 |
| `tool_result` | MCP tool 返回的结果 |
| `assistant` | 最终输出给用户的新闻摘要 |
| `error` | 运行过程中的异常信息 |
| `session_end` | 用户退出交互式会话 |

查看历史：

```bash
ai-news history --session interactive-YYYYMMDD-HHMMSS --limit 20
```

如果没有手动指定 session，`ai-news start` 会自动生成类似 `interactive-20260618-143000` 的会话名。

## 测试

运行全部测试：

```bash
pytest
```

当前测试覆盖重点包括：

- RSS/Atom 解析。
- arXiv Atom XML 解析。
- Hacker News Algolia JSON 解析。
- 正文抽取失败时回退到摘要。
- URL 或高度相似标题的去重排序。
- DeepSeek tool schema 和 intake tool schema。
- FastMCP `structuredContent={"result": ...}` 结果解码。
- JSONL conversation cache 追加和读取。
- `ai-news start` 的交互式 smoke test。

## 常见问题

### 1. 没有 DeepSeek API key 能运行吗？

可以。使用：

```bash
ai-news start --mock-llm
```

Mock 模式不会调用 DeepSeek，但仍会调用本地 MCP tools 和外部新闻源，因此能展示工具链、缓存和终端输出。

### 2. 为什么模型有时会先追问，而不是马上给新闻？

这是设计要求。程序要求模型必须先收集三项信息：新闻主题、时间范围、新闻数量。缺少任意一项时，模型只能追问，不能自行假设默认值。

### 3. 为什么结果里新闻数量可能少于我要求的数量？

因为模型只能基于 MCP tools 返回的真实内容回答。如果指定时间范围太短，或者外部源暂时没有足够相关结果，最终数量可能少于 `top_k`。这种情况下程序应该说明信息不足，而不是编造新闻。

### 4. 这个项目还支持日报 Markdown 吗？

当前主流程不再生成 Markdown 日报。旧版日报思路已经改造成对话式终端输出，并通过 JSONL 缓存保留完整过程。

### 5. cron 还能用吗？

代码中仍保留 `install-cron` 和 legacy `chat` 命令，但它们不是推荐主流程。交互式 `ai-news start` 更符合当前版本的应用设计。

## 实验说明

本项目适合作为 BYOA / Agent 实验项目，原因是：

- Agent 不是单纯调用一次大模型，而是通过对话先收集需求。
- 外部上下文由本地 MCP server 提供，模型不能只凭内部知识回答。
- 至少包含两个以上 functional skills，且这些技能以 tool 的形式被模型规划调用。
- 对话、工具调用和工具结果都写入 JSONL，方便在实验报告中截图和复盘。
- `docs/prompts.md` 记录了 Vibe Coding 过程中的关键提示词，可作为实验过程材料。

推荐报告截图：

- `ai-news doctor` 环境检查结果。
- `ai-news start` 中模型追问缺失信息。
- MCP tools 调用后的终端新闻摘要。
- `ai-news history --session <session>` 或 `cache/conversations/*.jsonl` 缓存记录。
