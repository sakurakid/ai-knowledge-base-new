---
name: article-organizer
description: 当需要将分析结果去重、标准化并落库到 knowledge/articles 时使用此技能
allowed-tools:
  - Read
  - Grep
  - Glob
  - Write
  - Edit
---

# 知识条目整理入库技能

## 使用场景
当采集和分析结果已准备好，需要统一格式、去重并写入知识库时使用本技能。

## 执行步骤
### 第 1 步：读取输入数据
读取 `knowledge/raw/` 下最新分析结果文件，作为入库输入。

### 第 2 步：去重检查
按 `source_url`、标题相似度进行去重，避免重复入库。

### 第 3 步：标准化字段
转换为统一知识条目结构，至少包含：
`id`, `title`, `source`, `source_url`, `collected_at`, `summary`, `analysis`, `tags`, `status`。

### 第 4 步：质量校验
校验必填字段、JSON 合法性、摘要长度与标签完整性，不合格条目应标记并跳过写入。

### 第 5 步：命名并写入
文件名格式：`{date}-{source}-{slug}.json`，写入目录：`knowledge/articles/`。

### 第 6 步：输出处理报告
输出本次写入统计（写入数、跳过数、重复数、失败原因）。

## 注意事项
- 仅处理本地输入数据，不扩展外部采集来源。
- `status` 默认设置为 `draft`，除非任务明确要求其他状态。
- 不覆盖已有同名文件；如冲突，在 `slug` 后追加区分后缀。

## 输出格式
```json
{
  "skill": "article-organizer",
  "processed_at": "2026-04-19T11:00:00Z",
  "written": 12,
  "duplicates_skipped": 2,
  "invalid_skipped": 1,
  "outputs": [
    {
      "file": "knowledge/articles/2026-04-19-github-example-repo.json",
      "id": "2026-04-19-github-example-repo",
      "status": "draft"
    }
  ]
}
```
