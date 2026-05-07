"""Local MCP server for searching knowledge base articles.

This server implements a small subset of the Model Context Protocol over
JSON-RPC 2.0 stdio. It exposes local knowledge articles as MCP tools without
using third-party dependencies.
"""

from __future__ import annotations

import json
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Any

JSONRPC_VERSION = "2.0"
SERVER_NAME = "local-knowledge-base"
SERVER_VERSION = "0.1.0"

# MCP 协议版本。这里用于 initialize 响应，告诉客户端本服务按哪个版本交互。
PROTOCOL_VERSION = "2024-11-05"

# 知识库文章目录：默认读取项目根目录下 knowledge/articles/*.json。
ARTICLES_DIR = Path(__file__).resolve().parent / "knowledge" / "articles"

LOGGER = logging.getLogger(SERVER_NAME)


def setup_logging() -> None:
    """Configure logging for stderr.

    JSON-RPC messages must be written only to stdout, so logs go to stderr.
    """
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def read_json_file(path: Path) -> dict[str, Any] | None:
    """Read one article JSON file.

    Args:
        path: JSON file path.

    Returns:
        Parsed article dictionary, or None when the file is invalid.
    """
    try:
        # 每篇文章都是一个 JSON 文件，统一按 UTF-8 读取。
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        # 单个文件坏了不让整个 MCP server 崩掉，只跳过并记日志。
        LOGGER.warning("Skip invalid article file: %s - %s", path, error)
        return None

    if not isinstance(data, dict):
        # 文章必须是 JSON object，数组/字符串这类结构不符合知识条目格式。
        LOGGER.warning("Skip non-object article file: %s", path)
        return None
    return data


def load_articles() -> list[dict[str, Any]]:
    """Load all article JSON files from the knowledge base.

    Returns:
        A list of article dictionaries.
    """
    if not ARTICLES_DIR.exists():
        LOGGER.warning("Articles directory does not exist: %s", ARTICLES_DIR)
        return []

    articles: list[dict[str, Any]] = []

    # 每次工具调用时重新扫描目录，这样新增/修改 JSON 后不用重启 server。
    for path in sorted(ARTICLES_DIR.glob("*.json")):
        article = read_json_file(path)
        if article is not None:
            articles.append(article)
    return articles


def normalize_text(value: Any) -> str:
    """Convert a value to lowercase searchable text.

    Args:
        value: Source value.

    Returns:
        Lowercase text representation.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.lower()
    return str(value).lower()


def article_to_search_result(article: dict[str, Any]) -> dict[str, Any]:
    """Convert an article to a compact search result.

    Args:
        article: Article dictionary.

    Returns:
        Compact article summary for search results.
    """
    # 搜索结果只返回常用摘要字段，避免列表页一次吐出过大的完整 JSON。
    return {
        "id": article.get("id"),
        "title": article.get("title"),
        "source": article.get("source"),
        "source_url": article.get("source_url"),
        "summary": article.get("summary"),
        "score": article.get("score") or article.get("analysis", {}).get("relevance_score"),
        "tags": article.get("tags", []),
        "status": article.get("status"),
    }


def search_articles(keyword: str, limit: int = 5) -> dict[str, Any]:
    """Search article titles and summaries by keyword.

    Args:
        keyword: Keyword to search in title and summary.
        limit: Maximum number of results to return.

    Returns:
        Search result payload.
    """
    # 简单大小写无关搜索：只查 title 和 summary，满足本地知识库快速检索。
    query = normalize_text(keyword).strip()
    if not query:
        return {"keyword": keyword, "total": 0, "results": []}

    results: list[dict[str, Any]] = []
    for article in load_articles():
        title = normalize_text(article.get("title"))
        summary = normalize_text(article.get("summary"))
        if query in title or query in summary:
            results.append(article_to_search_result(article))

    # 防止 limit 传 0 或负数导致返回不符合预期。
    safe_limit = max(1, int(limit))
    return {
        "keyword": keyword,
        "total": len(results),
        "results": results[:safe_limit],
    }


def get_article(article_id: str) -> dict[str, Any]:
    """Get a complete article by ID.

    Args:
        article_id: Article ID.

    Returns:
        Article payload or an error object.
    """
    # 这里精确匹配 id，适合 AI 工具先 search_articles 再 get_article。
    for article in load_articles():
        if article.get("id") == article_id:
            return {"found": True, "article": article}
    return {"found": False, "article_id": article_id, "error": "Article not found."}


def knowledge_stats() -> dict[str, Any]:
    """Calculate knowledge base statistics.

    Returns:
        Statistics including article count, source distribution, and top tags.
    """
    articles = load_articles()
    source_counter: Counter[str] = Counter()
    tag_counter: Counter[str] = Counter()

    for article in articles:
        # 来源为空时归为 unknown，避免统计结果里出现 None。
        source = article.get("source") or "unknown"
        source_counter[str(source)] += 1

        tags = article.get("tags", [])
        if isinstance(tags, list):
            # 只统计列表形式的 tags，脏数据不会影响整个统计。
            for tag in tags:
                tag_counter[str(tag)] += 1

    return {
        "total_articles": len(articles),
        "sources": dict(source_counter.most_common()),
        "top_tags": [
            {"tag": tag, "count": count}
            for tag, count in tag_counter.most_common(10)
        ],
    }


def tool_definitions() -> list[dict[str, Any]]:
    """Return MCP tool definitions.

    Returns:
        Tool metadata for tools/list.
    """
    # tools/list 返回 MCP 客户端可见的工具声明和参数 JSON Schema。
    return [
        {
            "name": "search_articles",
            "description": "Search local knowledge articles by keyword in title and summary.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "Keyword to search for.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results to return.",
                        "default": 5,
                        "minimum": 1,
                    },
                },
                "required": ["keyword"],
            },
        },
        {
            "name": "get_article",
            "description": "Get a complete local knowledge article by article ID.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "article_id": {
                        "type": "string",
                        "description": "Article ID to retrieve.",
                    },
                },
                "required": ["article_id"],
            },
        },
        {
            "name": "knowledge_stats",
            "description": "Return local knowledge base statistics.",
            "inputSchema": {
                "type": "object",
                "properties": {},
            },
        },
    ]


def make_text_content(payload: dict[str, Any]) -> dict[str, Any]:
    """Wrap a Python payload as MCP text content.

    Args:
        payload: Tool result payload.

    Returns:
        MCP tools/call content result.
    """
    # MCP 工具调用结果使用 content 数组；这里把结构化结果序列化成文本 JSON。
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(payload, ensure_ascii=False, indent=2),
            }
        ]
    }


def call_tool(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    """Dispatch an MCP tool call.

    Args:
        name: Tool name.
        arguments: Tool arguments.

    Returns:
        MCP tools/call result.

    Raises:
        ValueError: If the tool name or arguments are invalid.
    """
    # tools/call 入口会到这里，根据工具名分发到具体 Python 函数。
    args = arguments or {}
    if name == "search_articles":
        keyword = args.get("keyword")
        if not isinstance(keyword, str):
            raise ValueError("search_articles requires string argument: keyword.")
        limit = args.get("limit", 5)
        return make_text_content(search_articles(keyword, int(limit)))

    if name == "get_article":
        article_id = args.get("article_id")
        if not isinstance(article_id, str):
            raise ValueError("get_article requires string argument: article_id.")
        return make_text_content(get_article(article_id))

    if name == "knowledge_stats":
        return make_text_content(knowledge_stats())

    # 未注册工具统一抛错，由 JSON-RPC 层转换成错误响应。
    raise ValueError(f"Unknown tool: {name}")


def make_response(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    """Create a JSON-RPC success response.

    Args:
        request_id: JSON-RPC request ID.
        result: Response result.

    Returns:
        JSON-RPC response.
    """
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result}


def make_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    """Create a JSON-RPC error response.

    Args:
        request_id: JSON-RPC request ID, or None for parse errors.
        code: JSON-RPC error code.
        message: Error message.

    Returns:
        JSON-RPC error response.
    """
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def handle_request(request: dict[str, Any]) -> dict[str, Any] | None:
    """Handle one JSON-RPC request.

    Args:
        request: Parsed JSON-RPC request object.

    Returns:
        JSON-RPC response, or None for notifications.
    """
    # MCP stdio 传进来的每一行都是一个 JSON-RPC 请求或通知。
    request_id = request.get("id")
    method = request.get("method")
    params = request.get("params") or {}

    # JSON-RPC notifications have no id. MCP sends initialized this way.
    if request_id is None:
        LOGGER.info("Received notification: %s", method)
        return None

    if method == "initialize":
        # 客户端启动时首先调用 initialize，server 在这里声明能力。
        return make_response(
            request_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": SERVER_NAME,
                    "version": SERVER_VERSION,
                },
            },
        )

    if method == "tools/list":
        # 返回当前 server 暴露的工具列表。
        return make_response(request_id, {"tools": tool_definitions()})

    if method == "tools/call":
        # MCP 工具调用统一走 tools/call，具体工具名在 params.name 里。
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(tool_name, str):
            return make_error(request_id, -32602, "tools/call requires params.name.")
        if not isinstance(arguments, dict):
            return make_error(request_id, -32602, "tools/call params.arguments must be an object.")

        try:
            result = call_tool(tool_name, arguments)
        except (TypeError, ValueError) as error:
            return make_error(request_id, -32602, str(error))
        return make_response(request_id, result)

    return make_error(request_id, -32601, f"Method not found: {method}")


def write_message(message: dict[str, Any]) -> None:
    """Write one JSON-RPC message to stdout.

    Args:
        message: JSON-RPC message.
    """
    # stdio MCP 要求响应写到 stdout；每条 JSON-RPC 消息占一行。
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def serve() -> int:
    """Run the stdio JSON-RPC server loop.

    Returns:
        Process exit code.
    """
    setup_logging()
    LOGGER.info("MCP knowledge server started. Articles dir: %s", ARTICLES_DIR)

    # 主循环：持续从 stdin 读客户端发来的 JSON-RPC 消息。
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            # JSON 格式错误时按 JSON-RPC 规范返回 -32700 Parse error。
            request = json.loads(line)
        except json.JSONDecodeError as error:
            write_message(make_error(None, -32700, f"Parse error: {error}"))
            continue

        if not isinstance(request, dict):
            write_message(make_error(None, -32600, "Invalid Request."))
            continue

        try:
            response = handle_request(request)
        except Exception as error:
            # 理论上大部分错误都会在 handle_request 内处理；
            # 这里兜底，避免 server 因为异常退出。
            LOGGER.exception("Unhandled request error")
            response = make_error(request.get("id"), -32603, f"Internal error: {error}")

        if response is not None:
            write_message(response)

    LOGGER.info("MCP knowledge server stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(serve())
