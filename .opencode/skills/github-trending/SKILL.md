---
name: github-trending
description: 当需要采集 GitHub 热门开源项目时使用此技能
allowed-tools:
  - Read
  - Grep
  - Glob
  - WebFetch
---

# GitHub 热门项目采集技能

## 使用场景
在知识库采集阶段，需要从 GitHub 获取 AI/LLM/Agent 方向的热门开源项目时使用本技能。

## 执行步骤（7 步）
### 第 1 步：搜索热门仓库（GitHub API）
使用 GitHub Search API 查询近 7 天高热项目，例如：

`GET https://api.github.com/search/repositories?q=created:>{7天前日期}+stars:>100&sort=stars&order=desc&per_page=30`

### 第 2 步：提取仓库信息
提取字段：`name`, `full_name`, `html_url`, `description`, `stargazers_count`, `language`, `topics`。

### 第 3 步：过滤候选项
纳入：AI/ML/LLM/Agent 相关项目、开发工具、框架重大更新。  
排除：Awesome 列表、纯教程仓库、疑似刷 Star、无有效 README。

### 第 4 步：去重
按 `full_name` 去重，只保留一条有效记录。

### 第 5 步：撰写中文摘要
摘要公式：`[项目名] + 做什么 + 为什么值得关注`。

### 第 6 步：排序并取 Top 15
按 `stargazers_count` 降序排序，保留前 15 条。

### 第 7 步：输出 JSON
输出到：`knowledge/raw/github-trending-YYYY-MM-DD.json`。

## 注意事项
- 未认证 GitHub API 有限频，必要时控制请求频率。
- 摘要必须为中文，禁止复制冗长英文描述。
- 所有条目必须来自真实仓库，不编造。

## 输出格式
```json
{
  "source": "github",
  "skill": "github-trending",
  "collected_at": "2026-04-19T10:00:00Z",
  "items": [
    {
      "name": "example-repo",
      "url": "https://github.com/org/example-repo",
      "summary": "一句话中文摘要",
      "stars": 1234,
      "language": "Python",
      "topics": ["llm", "agent", "rag"]
    }
  ]
}
```
