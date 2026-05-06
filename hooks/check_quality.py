"""Score knowledge article JSON quality for hook automation.

这个脚本用于“质量评分”，和 validate_json.py 的职责不同：
validate_json.py 负责硬性 schema 校验；check_quality.py 负责给内容质量打分。
只要存在 C 级条目，脚本就返回 exit 1，方便 OpenCode hook 或 CI 阻断流程。
"""

from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from glob import glob
from pathlib import Path
from typing import Any


LOGGER = logging.getLogger("check_quality")

ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*-\d{8}-\d{3}$")
URL_PATTERN = re.compile(r"^https?://[^\s/$.?#].[^\s]*$")
VALID_STATUSES = {"draft", "review", "published", "archived"}
TIMESTAMP_FIELDS = ("collected_at", "created_at", "updated_at", "published_at")
GLOB_CHARS = {"*", "?", "["}

# 技术关键词用于给摘要质量加一点奖励。这里保持宽泛，避免只偏向某一种技术栈。
TECH_KEYWORDS = {
    "AI",
    "LLM",
    "Agent",
    "RAG",
    "MCP",
    "API",
    "workflow",
    "runtime",
    "benchmark",
    "model",
    "inference",
    "embedding",
    "向量",
    "模型",
    "智能体",
    "工作流",
    "推理",
    "评测",
    "检索",
}

# 标准标签列表可以随着知识库分类体系演进继续扩充。
STANDARD_TAGS = {
    "agent",
    "ai",
    "ai-coding",
    "ai-skill",
    "automation",
    "benchmark",
    "browser-automation",
    "chrome-extension",
    "claude-code",
    "cost-tracking",
    "developer-tools",
    "design-system",
    "embedding",
    "github",
    "hackernews",
    "html-presentation",
    "inference",
    "llm",
    "mcp-server",
    "open-source",
    "presentation-tool",
    "rag",
    "research",
    "runtime",
    "tui",
    "workflow",
}

CHINESE_HOLLOW_WORDS = {
    "赋能",
    "抓手",
    "闭环",
    "打通",
    "全链路",
    "底层逻辑",
    "颗粒度",
    "对齐",
    "拉通",
    "沉淀",
    "强大的",
}

ENGLISH_HOLLOW_WORDS = {
    "groundbreaking",
    "revolutionary",
    "game-changing",
    "cutting-edge",
    "paradigm-shifting",
    "next-generation",
}


def configure_logging() -> None:
    """Configure hook-friendly logging."""
    logging.basicConfig(
        format="[%(levelname)s] %(message)s",
        level=logging.INFO,
        stream=sys.stderr,
        force=True,
    )


@dataclass
class DimensionScore:
    """Score for one quality dimension."""

    name: str
    score: float
    max_score: int
    reasons: list[str] = field(default_factory=list)


@dataclass
class QualityReport:
    """Quality report for one JSON file."""

    path: Path
    dimensions: list[DimensionScore]
    total_score: float
    grade: str
    errors: list[str] = field(default_factory=list)


def has_glob_chars(value: str) -> bool:
    """Return whether a CLI argument contains glob characters.

    Args:
        value: Raw CLI argument.

    Returns:
        True if the argument should be expanded with glob().
    """
    return any(char in value for char in GLOB_CHARS)


def expand_paths(args: list[str]) -> tuple[list[Path], list[str]]:
    """Expand explicit file paths and wildcard patterns.

    Args:
        args: Raw CLI file arguments.

    Returns:
        Candidate paths and input expansion errors.
    """
    paths: list[Path] = []
    errors: list[str] = []

    for arg in args:
        LOGGER.info("Processing input argument: %s", arg)
        # Windows shell 不一定展开 *.json，所以脚本自己展开，hook 配置更省心。
        if has_glob_chars(arg):
            matches = sorted(Path(match) for match in glob(arg))
            LOGGER.info("Expanded glob %s to %d file(s)", arg, len(matches))
            if not matches:
                errors.append(f"No files matched pattern: {arg}")
            paths.extend(matches)
            continue

        paths.append(Path(arg))

    # 去重，避免同一个文件既被显式传入又被通配符命中时重复打分。
    unique_paths: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        normalized = path.resolve()
        if normalized not in seen:
            seen.add(normalized)
            unique_paths.append(path)

    return unique_paths, errors


def load_json(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    """Load a JSON object from disk.

    Args:
        path: JSON file path.

    Returns:
        Parsed object and a list of load errors.
    """
    errors: list[str] = []
    LOGGER.info("Loading JSON file: %s", path.as_posix())

    if not path.exists():
        return None, ["File does not exist"]

    if not path.is_file():
        return None, ["Path is not a file"]

    try:
        # utf-8-sig 兼容普通 UTF-8 和带 BOM 的 UTF-8。
        content = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        return None, [f"Cannot read file: {exc}"]
    except UnicodeDecodeError as exc:
        return None, [f"File is not valid UTF-8: {exc}"]

    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        return None, [f"Invalid JSON: line {exc.lineno}, column {exc.colno}: {exc.msg}"]

    if not isinstance(data, dict):
        errors.append("Top-level JSON value must be an object")
        return None, errors

    return data, errors


def clamp_score(score: float, max_score: int) -> float:
    """Clamp a score into the 0-max_score range.

    Args:
        score: Raw score.
        max_score: Maximum allowed score.

    Returns:
        Clamped score.
    """
    return max(0.0, min(float(max_score), score))


def contains_tech_keyword(summary: str) -> list[str]:
    """Find technical keywords in a summary.

    Args:
        summary: Article summary.

    Returns:
        Matched keywords.
    """
    lower_summary = summary.lower()
    matches = []
    for keyword in TECH_KEYWORDS:
        if keyword.lower() in lower_summary:
            matches.append(keyword)
    return sorted(matches)


def score_summary_quality(data: dict[str, Any]) -> DimensionScore:
    """Score summary quality out of 25.

    Args:
        data: Knowledge article data.

    Returns:
        Dimension score.
    """
    summary = data.get("summary")
    if not isinstance(summary, str):
        return DimensionScore("摘要质量", 0, 25, ["summary is missing or not str"])

    text = summary.strip()
    length = len(text)
    reasons = [f"summary length={length}"]

    # >= 50 字视为信息量充足；20-49 字给基本分；更短则线性给少量分。
    if length >= 50:
        score = 25
        reasons.append("length >= 50, full score")
    elif length >= 20:
        score = 12
        reasons.append("length >= 20, basic score")
    else:
        score = length / 20 * 8
        reasons.append("length < 20, below basic quality")

    matched_keywords = contains_tech_keyword(text)
    if matched_keywords and length < 50:
        bonus = min(5, len(matched_keywords) * 2)
        score += bonus
        reasons.append(f"tech keyword bonus: {', '.join(matched_keywords)}")
    elif matched_keywords:
        reasons.append(f"tech keywords: {', '.join(matched_keywords)}")

    return DimensionScore("摘要质量", clamp_score(score, 25), 25, reasons)


def extract_score(data: dict[str, Any]) -> Any:
    """Extract score from top-level score or analysis.relevance_score.

    Args:
        data: Knowledge article data.

    Returns:
        Raw score value.
    """
    if "score" in data:
        return data["score"]

    analysis = data.get("analysis")
    if isinstance(analysis, dict):
        return analysis.get("relevance_score")

    return None


def score_technical_depth(data: dict[str, Any]) -> DimensionScore:
    """Score technical depth out of 25.

    Args:
        data: Knowledge article data.

    Returns:
        Dimension score.
    """
    raw_score = extract_score(data)
    if not isinstance(raw_score, (int, float)) or isinstance(raw_score, bool):
        return DimensionScore("技术深度", 0, 25, ["score is missing or not numeric"])

    if raw_score < 1 or raw_score > 10:
        return DimensionScore("技术深度", 0, 25, [f"score={raw_score} out of 1-10"])

    # 需求要求 1-10 映射到 0-25：1 分对应 0，10 分对应 25。
    mapped_score = (float(raw_score) - 1) / 9 * 25
    reasons = [f"score={raw_score} mapped to {mapped_score:.1f}/25"]
    return DimensionScore("技术深度", clamp_score(mapped_score, 25), 25, reasons)


def has_valid_timestamp(data: dict[str, Any]) -> bool:
    """Return whether the article has a recognizable timestamp.

    Args:
        data: Knowledge article data.

    Returns:
        True if one known timestamp field is valid.
    """
    for field_name in TIMESTAMP_FIELDS:
        value = data.get(field_name)
        if not isinstance(value, str) or not value.strip():
            continue

        # 支持常见 ISO 8601：2026-03-17T10:00:00Z 或带 +00:00。
        normalized = value.replace("Z", "+00:00")
        try:
            datetime.fromisoformat(normalized)
        except ValueError:
            continue
        return True

    return False


def score_format(data: dict[str, Any]) -> DimensionScore:
    """Score format compliance out of 20.

    Args:
        data: Knowledge article data.

    Returns:
        Dimension score.
    """
    checks = [
        ("id", isinstance(data.get("id"), str) and ID_PATTERN.fullmatch(data["id"])),
        ("title", isinstance(data.get("title"), str) and bool(data["title"].strip())),
        (
            "source_url",
            isinstance(data.get("source_url"), str)
            and bool(URL_PATTERN.fullmatch(data["source_url"])),
        ),
        ("status", isinstance(data.get("status"), str) and data["status"] in VALID_STATUSES),
        ("timestamp", has_valid_timestamp(data)),
    ]

    score = 0
    reasons: list[str] = []
    for name, passed in checks:
        if passed:
            score += 4
            reasons.append(f"{name}: ok")
        else:
            reasons.append(f"{name}: missing or invalid")

    return DimensionScore("格式规范", score, 20, reasons)


def normalize_tag(value: str) -> str:
    """Normalize a tag for comparison.

    Args:
        value: Raw tag.

    Returns:
        Lowercase normalized tag.
    """
    return value.strip().lower()


def score_tags(data: dict[str, Any]) -> DimensionScore:
    """Score tag precision out of 15.

    Args:
        data: Knowledge article data.

    Returns:
        Dimension score.
    """
    tags = data.get("tags")
    if not isinstance(tags, list):
        return DimensionScore("标签精度", 0, 15, ["tags is missing or not list"])

    normalized_tags = [
        normalize_tag(tag) for tag in tags if isinstance(tag, str) and tag.strip()
    ]
    if not normalized_tags:
        return DimensionScore("标签精度", 0, 15, ["no valid tags"])

    reasons = [f"tag count={len(normalized_tags)}"]

    # 1-3 个标签最利于检索；过多说明标签不够聚焦。
    if 1 <= len(normalized_tags) <= 3:
        score = 10
        reasons.append("tag count is focused")
    else:
        score = 6
        reasons.append("too many tags, focus penalty")

    valid_tags = [tag for tag in normalized_tags if tag in STANDARD_TAGS]
    invalid_tags = [tag for tag in normalized_tags if tag not in STANDARD_TAGS]
    if valid_tags:
        score += min(5, len(valid_tags) * 2)
        reasons.append(f"standard tags: {', '.join(valid_tags)}")

    if invalid_tags:
        penalty = min(6, len(invalid_tags) * 2)
        score -= penalty
        reasons.append(f"non-standard tags: {', '.join(invalid_tags)}")

    return DimensionScore("标签精度", clamp_score(score, 15), 15, reasons)


def find_hollow_words(text: str) -> list[str]:
    """Find hollow buzzwords in article text.

    Args:
        text: Combined searchable article text.

    Returns:
        Matched hollow words.
    """
    lower_text = text.lower()
    matches: list[str] = []

    for word in CHINESE_HOLLOW_WORDS:
        if word in text:
            matches.append(word)

    for word in ENGLISH_HOLLOW_WORDS:
        if word.lower() in lower_text:
            matches.append(word)

    return sorted(matches)


def score_hollow_words(data: dict[str, Any]) -> DimensionScore:
    """Score hollow-word cleanliness out of 15.

    Args:
        data: Knowledge article data.

    Returns:
        Dimension score.
    """
    # 主要检查用户会读到的文本字段，避免因为 URL 或内部字段误伤。
    text_parts = []
    for field_name in ("title", "summary"):
        value = data.get(field_name)
        if isinstance(value, str):
            text_parts.append(value)

    analysis = data.get("analysis")
    if isinstance(analysis, dict):
        for value in analysis.values():
            if isinstance(value, str):
                text_parts.append(value)
            elif isinstance(value, list):
                text_parts.extend(item for item in value if isinstance(item, str))

    matches = find_hollow_words("\n".join(text_parts))
    if not matches:
        return DimensionScore("空洞词检测", 15, 15, ["no hollow words found"])

    score = 15 - min(15, len(matches) * 4)
    reasons = [f"hollow words: {', '.join(matches)}"]
    return DimensionScore("空洞词检测", clamp_score(score, 15), 15, reasons)


def get_grade(total_score: float) -> str:
    """Convert numeric score to A/B/C grade.

    Args:
        total_score: Total quality score.

    Returns:
        Grade label.
    """
    if total_score >= 80:
        return "A"
    if total_score >= 60:
        return "B"
    return "C"


def build_progress_bar(score: float, max_score: int, width: int = 20) -> str:
    """Build a text progress bar.

    Args:
        score: Dimension score.
        max_score: Dimension max score.
        width: Progress bar width.

    Returns:
        Progress bar text.
    """
    if max_score <= 0:
        return "[" + "-" * width + "]"

    filled = round(score / max_score * width)
    filled = max(0, min(width, filled))
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def build_report(path: Path, input_errors: list[str] | None = None) -> QualityReport:
    """Build a quality report for one file.

    Args:
        path: JSON file path.
        input_errors: Pre-existing input expansion errors.

    Returns:
        Quality report.
    """
    if input_errors:
        LOGGER.info("Input error for %s: %s", path.as_posix(), "; ".join(input_errors))
        return QualityReport(path=path, dimensions=[], total_score=0, grade="C", errors=input_errors)

    LOGGER.info("Scoring file: %s", path.as_posix())
    data, load_errors = load_json(path)
    if load_errors or data is None:
        LOGGER.info("Scoring failed before quality checks: %s", path.as_posix())
        return QualityReport(path=path, dimensions=[], total_score=0, grade="C", errors=load_errors)

    dimensions = [
        score_summary_quality(data),
        score_technical_depth(data),
        score_format(data),
        score_tags(data),
        score_hollow_words(data),
    ]
    total_score = sum(dimension.score for dimension in dimensions)
    grade = get_grade(total_score)
    LOGGER.info(
        "Quality score complete: %s, total=%.1f, grade=%s",
        path.as_posix(),
        total_score,
        grade,
    )
    return QualityReport(path=path, dimensions=dimensions, total_score=total_score, grade=grade)


def format_report(report: QualityReport) -> str:
    """Format one quality report.

    Args:
        report: Quality report.

    Returns:
        Human-readable report text.
    """
    lines = [
        f"{report.path.as_posix()}",
        f"Total: {report.total_score:.1f}/100  Grade: {report.grade}",
    ]

    if report.errors:
        for error in report.errors:
            lines.append(f"  - {error}")
        return "\n".join(lines)

    for dimension in report.dimensions:
        bar = build_progress_bar(dimension.score, dimension.max_score)
        lines.append(
            f"  {dimension.name:<10} {bar} "
            f"{dimension.score:.1f}/{dimension.max_score}"
        )
        for reason in dimension.reasons:
            lines.append(f"    - {reason}")

    return "\n".join(lines)


def format_summary(reports: list[QualityReport]) -> str:
    """Format aggregate quality summary.

    Args:
        reports: Quality reports.

    Returns:
        Summary text.
    """
    grade_counts = {"A": 0, "B": 0, "C": 0}
    for report in reports:
        grade_counts[report.grade] += 1

    return (
        "Summary: "
        f"total={len(reports)}, "
        f"A={grade_counts['A']}, "
        f"B={grade_counts['B']}, "
        f"C={grade_counts['C']}"
    )


def main(argv: list[str]) -> int:
    """Run the quality scoring CLI.

    Args:
        argv: Command-line arguments excluding script name.

    Returns:
        Exit code: 1 when any report is grade C, otherwise 0.
    """
    configure_logging()
    LOGGER.info("Starting quality check: inputs=%d", len(argv))

    if not argv:
        LOGGER.info("No input files provided")
        sys.stderr.write(
            "Usage: python hooks/check_quality.py <json_file> [json_file2 ...]\n"
        )
        return 1

    paths, expansion_errors = expand_paths(argv)
    reports = [build_report(path) for path in paths]

    for error in expansion_errors:
        reports.append(build_report(Path("<input>"), [error]))

    output_blocks = [format_report(report) for report in reports]
    output_blocks.append(format_summary(reports))
    output = "\n\n".join(output_blocks) + "\n"

    has_grade_c = any(report.grade == "C" for report in reports)
    LOGGER.info("Quality summary: %s", format_summary(reports))
    stream = sys.stderr if has_grade_c else sys.stdout
    stream.write(output)

    return 1 if has_grade_c else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
