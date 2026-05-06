"""Validate knowledge article JSON files for hook automation.

这个脚本设计给 OpenCode hook、Git hook 或本地命令行共同使用：
校验通过返回 exit 0，校验失败返回 exit 1，并输出所有错误原因。
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from glob import glob
from pathlib import Path
from typing import Any


REQUIRED_FIELDS: dict[str, type] = {
    "id": str,
    "title": str,
    "source_url": str,
    "summary": str,
    "tags": list,
    "status": str,
}

# 下面这些常量就是“知识条目”的基础规则。以后如果规范变化，
# 优先改这里，避免把魔法字符串散落到多个函数里。
# OpenCode hooks often pass plain changed-file arguments. Shells on Windows may
# not expand wildcards, so the validator expands them itself for stable CLI use.
ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*-\d{8}-\d{3}$")
URL_PATTERN = re.compile(r"^https?://[^\s/$.?#].[^\s]*$")
VALID_STATUSES = {"draft", "review", "published", "archived"}
VALID_AUDIENCES = {"beginner", "intermed"}
GLOB_CHARS = {"*", "?", "["}


@dataclass
class ValidationResult:
    """Collect validation state for a single file."""

    path: Path
    errors: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """Return whether this file passed validation."""
        return not self.errors

    def add_error(self, message: str) -> None:
        """Append a human-readable validation error.

        Args:
            message: Error message without file prefix.
        """
        self.errors.append(message)


@dataclass
class Summary:
    """Aggregate validation counters across all inputs."""

    total: int = 0
    passed: int = 0
    failed: int = 0


def has_glob_chars(value: str) -> bool:
    """Return whether an argument contains glob wildcard characters.

    Args:
        value: Raw command-line argument.

    Returns:
        True when the argument should be expanded as a glob pattern.
    """
    return any(char in value for char in GLOB_CHARS)


def expand_paths(args: list[str]) -> tuple[list[Path], list[str]]:
    """Expand command-line file and glob arguments into JSON paths.

    Args:
        args: Raw command-line path arguments.

    Returns:
        A tuple containing resolved candidate paths and expansion errors.
    """
    paths: list[Path] = []
    errors: list[str] = []

    for arg in args:
        # PowerShell/cmd 不一定会帮我们展开 *.json，所以这里自己展开，
        # 这样 OpenCode hook 里写 knowledge/articles/*.json 也能稳定工作。
        if has_glob_chars(arg):
            matches = sorted(Path(match) for match in glob(arg))
            if not matches:
                errors.append(f"No files matched pattern: {arg}")
            paths.extend(matches)
            continue

        paths.append(Path(arg))

    # 同一个文件可能被多个参数命中，比如同时传入具体文件和 *.json。
    # 这里按绝对路径去重，避免重复报错或重复计数。
    unique_paths: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        normalized = path.resolve()
        if normalized not in seen:
            seen.add(normalized)
            unique_paths.append(path)

    return unique_paths, errors


def load_json(path: Path, result: ValidationResult) -> Any | None:
    """Load a JSON file using UTF-8.

    Args:
        path: JSON file path.
        result: Validation result to populate on failure.

    Returns:
        Parsed JSON data, or None when parsing fails.
    """
    try:
        # utf-8-sig accepts normal UTF-8 and UTF-8 with BOM, which is common
        # when JSON files are generated or edited on Windows.
        content = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        result.add_error(f"Cannot read file: {exc}")
        return None
    except UnicodeDecodeError as exc:
        result.add_error(f"File is not valid UTF-8: {exc}")
        return None

    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        result.add_error(f"Invalid JSON: line {exc.lineno}, column {exc.colno}: {exc.msg}")
        return None


def validate_required_fields(data: dict[str, Any], result: ValidationResult) -> None:
    """Validate required field presence and type.

    Args:
        data: Parsed JSON object.
        result: Validation result to populate.
    """
    # REQUIRED_FIELDS 使用 dict[str, type]，同时表达“必须存在”和“类型要求”。
    for field_name, expected_type in REQUIRED_FIELDS.items():
        if field_name not in data:
            result.add_error(f"Missing required field: {field_name}")
            continue

        value = data[field_name]
        if not isinstance(value, expected_type):
            expected_name = expected_type.__name__
            actual_name = type(value).__name__
            result.add_error(
                f"Field {field_name} must be {expected_name}, got {actual_name}"
            )


def validate_id(value: Any, result: ValidationResult) -> None:
    """Validate the article ID format.

    Args:
        value: Candidate article ID.
        result: Validation result to populate.
    """
    if isinstance(value, str) and not ID_PATTERN.fullmatch(value):
        result.add_error("Field id must match {source}-{YYYYMMDD}-{NNN}")


def validate_status(value: Any, result: ValidationResult) -> None:
    """Validate publication status.

    Args:
        value: Candidate status.
        result: Validation result to populate.
    """
    if isinstance(value, str) and value not in VALID_STATUSES:
        allowed = "/".join(sorted(VALID_STATUSES))
        result.add_error(f"Field status must be one of: {allowed}")


def validate_url(value: Any, result: ValidationResult) -> None:
    """Validate source URL shape.

    Args:
        value: Candidate source URL.
        result: Validation result to populate.
    """
    if isinstance(value, str) and not URL_PATTERN.fullmatch(value):
        result.add_error("Field source_url must be an http(s) URL")


def validate_summary(value: Any, result: ValidationResult) -> None:
    """Validate summary minimum length.

    Args:
        value: Candidate summary.
        result: Validation result to populate.
    """
    if isinstance(value, str) and len(value.strip()) < 20:
        result.add_error("Field summary must contain at least 20 characters")


def validate_tags(value: Any, result: ValidationResult) -> None:
    """Validate tags list shape.

    Args:
        value: Candidate tags list.
        result: Validation result to populate.
    """
    if not isinstance(value, list):
        return

    if not value:
        result.add_error("Field tags must contain at least 1 item")
        return

    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            result.add_error(f"Field tags[{index}] must be a non-empty string")


def validate_score(value: Any, field_name: str, result: ValidationResult) -> None:
    """Validate a score-like value in the 1-10 range.

    Args:
        value: Candidate score value.
        field_name: Field name to show in errors.
        result: Validation result to populate.
    """
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        result.add_error(f"Field {field_name} must be a number")
        return

    if value < 1 or value > 10:
        result.add_error(f"Field {field_name} must be between 1 and 10")


def validate_audience(value: Any, result: ValidationResult) -> None:
    """Validate optional audience value.

    Args:
        value: Candidate audience.
        result: Validation result to populate.
    """
    if isinstance(value, str) and value not in VALID_AUDIENCES:
        allowed = "/".join(sorted(VALID_AUDIENCES))
        result.add_error(f"Field audience must be one of: {allowed}")
    elif not isinstance(value, str):
        result.add_error("Field audience must be str")


def validate_optional_fields(data: dict[str, Any], result: ValidationResult) -> None:
    """Validate optional score and audience fields.

    Args:
        data: Parsed JSON object.
        result: Validation result to populate.
    """
    # score/audience 是可选字段：不存在不报错，存在就必须合法。
    if "score" in data:
        validate_score(data["score"], "score", result)

    # Current article examples may place the score inside analysis. Accept that
    # shape so the hook works with both compact and nested knowledge entries.
    analysis = data.get("analysis")
    if isinstance(analysis, dict) and "relevance_score" in analysis:
        validate_score(analysis["relevance_score"], "analysis.relevance_score", result)

    if "audience" in data:
        validate_audience(data["audience"], result)


def validate_file(path: Path) -> ValidationResult:
    """Validate one knowledge article JSON file.

    Args:
        path: JSON file path.

    Returns:
        Validation result with any collected errors.
    """
    # 每个文件都独立收集错误，不提前中断。这样一次 hook 能把所有问题列全。
    result = ValidationResult(path=path)

    if not path.exists():
        result.add_error("File does not exist")
        return result

    if not path.is_file():
        result.add_error("Path is not a file")
        return result

    if path.suffix.lower() != ".json":
        result.add_error("File extension must be .json")
        return result

    data = load_json(path, result)
    if data is None:
        return result

    if not isinstance(data, dict):
        result.add_error("Top-level JSON value must be an object")
        return result

    validate_required_fields(data, result)
    validate_id(data.get("id"), result)
    validate_status(data.get("status"), result)
    validate_url(data.get("source_url"), result)
    validate_summary(data.get("summary"), result)
    validate_tags(data.get("tags"), result)
    validate_optional_fields(data, result)

    return result


def format_results(results: list[ValidationResult], summary: Summary) -> str:
    """Format validation output for humans and hook logs.

    Args:
        results: Per-file validation results.
        summary: Aggregate counters.

    Returns:
        Complete output text.
    """
    lines: list[str] = []

    for result in results:
        display_path = result.path.as_posix()
        if result.is_valid:
            lines.append(f"OK: {display_path}")
            continue

        lines.append(f"FAIL: {display_path}")
        for error in result.errors:
            lines.append(f"  - {error}")

    lines.append("")
    lines.append(
        "Summary: "
        f"total={summary.total}, passed={summary.passed}, failed={summary.failed}"
    )

    return "\n".join(lines) + "\n"


def build_summary(results: list[ValidationResult]) -> Summary:
    """Build aggregate counters from validation results.

    Args:
        results: Per-file validation results.

    Returns:
        Summary counters.
    """
    summary = Summary(total=len(results))
    summary.passed = sum(1 for result in results if result.is_valid)
    summary.failed = summary.total - summary.passed
    return summary


def main(argv: list[str]) -> int:
    """Run the JSON validation CLI.

    Args:
        argv: Command-line arguments excluding the script name.

    Returns:
        Process exit code: 0 for success, 1 for validation failure.
    """
    if not argv:
        sys.stderr.write(
            "Usage: python hooks/validate_json.py <json_file> [json_file2 ...]\n"
        )
        return 1

    # 主流程：展开输入 -> 逐文件校验 -> 汇总 -> 按结果决定退出码。
    paths, expansion_errors = expand_paths(argv)
    results = [validate_file(path) for path in paths]

    for error in expansion_errors:
        result = ValidationResult(path=Path("<input>"))
        result.add_error(error)
        results.append(result)

    summary = build_summary(results)
    output = format_results(results, summary)
    stream = sys.stdout if summary.failed == 0 else sys.stderr
    stream.write(output)

    # hook/CI 只关心退出码：0 表示放行，1 表示阻止后续流程。
    return 0 if summary.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
