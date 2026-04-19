---
name: tech-summary
description: 当需要对采集的技术内容进行深度分析总结时使用此技能
allowed-tools:
  - Read
  - Grep
  - Glob
  - WebFetch
---

# 技术内容深度分析技能

## 使用场景
当 `knowledge/raw/` 已有采集结果，需要生成可决策的技术分析、评分和标签建议时使用本技能。

## 执行步骤（4 步）
### 第 1 步：读取最新采集文件
从 `knowledge/raw/` 中定位最新采集 JSON，作为分析输入。

### 第 2 步：逐条深度分析
对每个项目输出：
- 摘要：中文，`<= 50` 字
- 技术亮点：`2-3` 个，必须基于事实
- 评分：`1-10` 分，并给出评分理由
- 标签建议：便于后续检索和归档

评分标准：
- `9-10`：改变格局
- `7-8`：直接有帮助
- `5-6`：值得了解
- `1-4`：可略过

### 第 3 步：趋势发现
总结共同主题、新概念和可跟进方向，形成趋势观察结论。

### 第 4 步：输出分析结果 JSON
输出到：`knowledge/raw/tech-summary-YYYY-MM-DD.json`。

## 注意事项
- 15 个项目中，`9-10` 分条目不超过 2 个。
- 不得编造指标、性能、社区反馈等信息。
- 摘要、理由、趋势结论均使用中文。

## 输出格式
```json
{
  "source": "github",
  "skill": "tech-summary",
  "analyzed_at": "2026-04-19T10:30:00Z",
  "input_file": "knowledge/raw/github-trending-2026-04-19.json",
  "items": [
    {
      "name": "example-repo",
      "url": "https://github.com/org/example-repo",
      "summary": "50字以内中文摘要",
      "tech_highlights": ["亮点1", "亮点2"],
      "relevance_score": 8,
      "score_reason": "评分理由",
      "suggested_tags": ["agent", "inference"]
    }
  ],
  "trends": {
    "common_themes": ["主题1", "主题2"],
    "new_concepts": ["概念1"],
    "follow_up_suggestions": ["建议1", "建议2"]
  }
}
```
