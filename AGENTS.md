# AGENTS.md - AI 知识库助手项目规范

## 1. 项目概述
本项目是一个 AI 知识库助手系统，用于自动采集 AI/LLM/Agent 领域技术动态（GitHub Trending、Hacker News），完成分析与结构化沉淀，并支持通过 Telegram、飞书等渠道分发。

## 2. 技术栈
- 语言：Python 3.12
- AI 编排：OpenCode + 国产大模型（DeepSeek / Qwen / GLM / Kimi）
- 工作流：LangGraph（第 3 周引入）
- 部署：OpenClaw（第 4 周引入）
- 依赖管理：`pip` + `requirements.txt`
- 版本控制：Git

## 3. 编码规范
- 遵循 PEP 8
- 变量命名使用 `snake_case`
- 类名使用 `PascalCase`
- 所有函数必须有 Google 风格 `docstring`
- 禁止裸 `print()`，统一使用 `logging` 或文件日志
- 禁止 `import *`
- 文件编码统一为 UTF-8

## 4. 项目结构
```text
ai-knowledge-base/
├── AGENTS.md
├── .opencode/
│   ├── agents/
│   │   ├── collector.md
│   │   ├── analyzer.md
│   │   └── organizer.md
│   └── skills/
├── knowledge/
│   ├── raw/
│   └── articles/
├── pipeline/
├── workflows/
└── openclaw/
```

## 5. 知识条目 JSON 格式
每条知识条目存放在 `knowledge/articles/` 目录中，建议格式如下：

```json
{
  "id": "2026-03-01-github-openclaw",
  "title": "OpenClaw: 开源 AI Agent 运行时",
  "source": "github-trending",
  "source_url": "https://github.com/example/project",
  "collected_at": "2026-03-01T10:00:00Z",
  "summary": "一句话中文摘要（不超过100字）",
  "analysis": {
    "tech_highlights": ["多 Agent 路由", "50+ 平台支持"],
    "relevance_score": 9
  },
  "tags": ["agent", "runtime", "open-source"],
  "status": "draft"
}
```

必填字段：`id`, `title`, `source_url`, `summary`, `tags`, `status`  
`status` 可选值：`draft` / `reviewed` / `published`

## 6. Agent 角色概览
| 角色 | 文件 | 职责 |
|---|---|---|
| 采集 Agent | `.opencode/agents/collector.md` | 从 GitHub Trending、Hacker News 抓取技术动态 |
| 分析 Agent | `.opencode/agents/analyzer.md` | 生成摘要、提炼亮点、评估价值 |
| 整理 Agent | `.opencode/agents/organizer.md` | 去重、标准化格式、归档发布 |

## 7. 红线（绝对禁止）
- 禁止编造不存在的项目、来源或数据
- 禁止在日志、代码、提交记录中暴露 API Key、Token、密钥等敏感信息
- 禁止执行高风险破坏命令（例如 `rm -rf`、批量无确认删除）
- 未经明确要求，不得修改本文件规范定义
