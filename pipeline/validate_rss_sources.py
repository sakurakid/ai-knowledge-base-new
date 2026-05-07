"""Validate RSS source configuration and feed availability."""

from __future__ import annotations

import argparse
import logging
import ssl
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import yaml

LOGGER = logging.getLogger(__name__)

# 每个 RSS 源都必须具备这些字段，避免采集器后续读配置时遇到缺字段。
REQUIRED_FIELDS = {"name", "url", "category", "enabled"}

# 设置 User-Agent，减少部分站点因为默认 Python UA 拒绝请求的概率。
USER_AGENT = "ai-knowledge-base-rss-validator/0.1"


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Parsed command-line arguments.
    """
    # 默认验证同目录下的 rss_sources.yaml；需要临时检查其他配置时可传 --config。
    parser = argparse.ArgumentParser(
        description="Validate RSS source YAML and reachable feeds.",
    )
    parser.add_argument(
        "--config",
        default=Path(__file__).with_name("rss_sources.yaml"),
        type=Path,
        help="Path to RSS source YAML file.",
    )
    parser.add_argument(
        "--include-disabled",
        action="store_true",
        help="Also validate sources with enabled: false.",
    )
    parser.add_argument(
        "--timeout",
        default=20,
        type=int,
        help="HTTP request timeout in seconds.",
    )
    parser.add_argument(
        "--retries",
        default=2,
        type=int,
        help="Maximum request attempts for each source.",
    )
    return parser.parse_args()


def load_sources(config_path: Path) -> list[dict[str, Any]]:
    """Load and validate the RSS source YAML structure.

    Args:
        config_path: Path to the YAML configuration file.

    Returns:
        A list of RSS source dictionaries.

    Raises:
        ValueError: If the YAML structure or required fields are invalid.
    """
    # 统一按 UTF-8 读取配置，和项目文件编码规范保持一致。
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("YAML root must be a mapping.")

    # 配置约定使用顶层 sources 列表，后续采集器也可以直接复用这个结构。
    sources = data.get("sources")
    if not isinstance(sources, list):
        raise ValueError("YAML must contain a sources list.")

    for index, source in enumerate(sources, start=1):
        if not isinstance(source, dict):
            raise ValueError(f"Source #{index} must be a mapping.")

        # 提前做字段校验，让配置问题在采集前暴露出来。
        missing_fields = REQUIRED_FIELDS - source.keys()
        if missing_fields:
            missing = ", ".join(sorted(missing_fields))
            raise ValueError(f"Source #{index} is missing fields: {missing}.")

        # enabled 必须是 YAML 布尔值 true/false，不能写成字符串。
        if not isinstance(source["enabled"], bool):
            raise ValueError(f"Source #{index} enabled must be a boolean.")

    return sources


def open_feed_request(
    request: urllib.request.Request,
    timeout: int,
    verify_ssl: bool,
) -> bytes:
    """Open one feed request and return response bytes.

    Args:
        request: Prepared HTTP request.
        timeout: Request timeout in seconds.
        verify_ssl: Whether to verify HTTPS certificates.

    Returns:
        Feed response body bytes.
    """
    context = None if verify_ssl else ssl._create_unverified_context()
    with urllib.request.urlopen(
        request,
        timeout=timeout,
        context=context,
    ) as response:
        return response.read()


def fetch_feed(url: str, timeout: int, retries: int) -> bytes:
    """Fetch feed bytes from a URL.

    Args:
        url: RSS or Atom feed URL.
        timeout: Request timeout in seconds.
        retries: Maximum request attempts for transient network errors.

    Returns:
        Feed response body bytes.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    max_attempts = max(1, retries)
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            # 优先使用系统默认证书校验，保持正常 HTTPS 安全策略。
            return open_feed_request(request, timeout, verify_ssl=True)
        except urllib.error.URLError as error:
            reason = getattr(error, "reason", None)
            if isinstance(reason, ssl.SSLCertVerificationError):
                # arXiv 等源在某些 Windows/Python 环境下可能证书链校验失败。
                # 这里仅作为验证脚本的兜底重试，生产采集建议修复本机 CA 证书。
                LOGGER.warning(
                    "SSL certificate verification failed, retrying without verification: %s",
                    url,
                )
                return open_feed_request(request, timeout, verify_ssl=False)

            last_error = error
            if attempt < max_attempts:
                LOGGER.warning(
                    "请求失败，准备重试: %s (%d/%d) - %s",
                    url,
                    attempt,
                    max_attempts,
                    error,
                )
                time.sleep(1)

    if last_error is not None:
        raise last_error
    raise RuntimeError("Feed request failed without an explicit error.")


def count_feed_items(feed_body: bytes) -> int:
    """Count RSS item or Atom entry elements in a feed.

    Args:
        feed_body: Feed XML bytes.

    Returns:
        Number of feed items or entries.

    Raises:
        ValueError: If the response is not parseable RSS or Atom XML.
    """
    try:
        # RSS 和 Atom 本质都是 XML，先确认响应内容能被 XML 解析器读懂。
        root = ET.fromstring(feed_body)
    except ET.ParseError as error:
        raise ValueError(f"Invalid XML: {error}") from error

    root_tag = root.tag.lower()
    if root_tag.endswith("rss"):
        # RSS 2.0 使用 <item> 表示一条内容。
        return len(root.findall(".//item"))
    if root_tag.endswith("feed"):
        # Atom feed 使用带命名空间的 <entry> 表示一条内容。
        return len(root.findall(".//{http://www.w3.org/2005/Atom}entry"))
    raise ValueError(f"Unsupported feed root element: {root.tag}")


def validate_sources(
    sources: list[dict[str, Any]],
    include_disabled: bool,
    timeout: int,
    retries: int,
) -> bool:
    """Validate feed availability for selected sources.

    Args:
        sources: RSS source dictionaries.
        include_disabled: Whether to validate disabled sources too.
        timeout: Request timeout in seconds.
        retries: Maximum request attempts for each source.

    Returns:
        True when all selected sources are valid, otherwise False.
    """
    # 默认只验证 enabled: true 的源，避免大流量或待确认源影响日常检查。
    selected_sources = [
        source for source in sources if include_disabled or source["enabled"]
    ]
    LOGGER.info("总数据源: %d 个", len(sources))
    LOGGER.info("待验证: %d 个", len(selected_sources))

    success_count = 0
    for source in selected_sources:
        name = source["name"]
        category = source["category"]
        url = source["url"]
        LOGGER.info("验证: %s (%s) - %s", name, category, url)
        try:
            # 请求 feed 并解析条目数；任一环节失败都会记录错误并继续检查下一个源。
            item_count = count_feed_items(fetch_feed(url, timeout, retries))
        except (OSError, ValueError, urllib.error.URLError) as error:
            LOGGER.error("失败: %s - %s", name, error)
            continue

        success_count += 1
        LOGGER.info("成功: %s - %d 条条目", name, item_count)

    LOGGER.info("验证通过: %d/%d", success_count, len(selected_sources))
    return success_count == len(selected_sources)


def main() -> int:
    """Run RSS source validation.

    Returns:
        Process exit code.
    """
    # logging 输出带时间戳，方便放到定时任务或 CI 日志里排查问题。
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    args = parse_args()

    try:
        sources = load_sources(args.config)
    except (OSError, ValueError, yaml.YAMLError) as error:
        LOGGER.error("配置加载失败: %s", error)
        return 1

    # 返回码用于自动化判断：0 表示全部通过，1 表示配置或源可用性存在问题。
    if validate_sources(
        sources,
        args.include_disabled,
        args.timeout,
        args.retries,
    ):
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
