from __future__ import annotations

import os
from typing import Any
from urllib.parse import urljoin

import httpx

DEFAULT_SEARXNG_URL = "http://localhost:8080"
DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_MAX_RESULTS = 5
DEFAULT_LANGUAGE = "en"


def search_web(
    query: str,
    *,
    max_results: int = DEFAULT_MAX_RESULTS,
    language: str | None = None,
    categories: str | None = None,
    time_range: str | None = None,
    searxng_url: str | None = None,
) -> dict[str, Any]:
    """Search the web through a SearXNG JSON endpoint."""
    normalized_query = query.strip()
    if not normalized_query:
        raise ValueError("query must not be empty")

    limit = clamp_int(max_results, minimum=1, maximum=50)
    base_url = (searxng_url or os.getenv("SEARXNG_URL") or DEFAULT_SEARXNG_URL).rstrip("/")
    params: dict[str, str] = {
        "q": normalized_query,
        "format": "json",
        "language": language or os.getenv("SEARXNG_LANGUAGE") or DEFAULT_LANGUAGE,
    }
    if categories:
        params["categories"] = categories
    if time_range:
        params["time_range"] = time_range

    response = httpx.get(
        urljoin(f"{base_url}/", "search"),
        params=params,
        timeout=httpx.Timeout(DEFAULT_TIMEOUT_SECONDS),
    )
    response.raise_for_status()
    payload = response.json()
    raw_results = payload.get("results", [])
    results = [normalize_result(item) for item in raw_results if isinstance(item, dict)]
    results = [item for item in results if item.get("url")][:limit]

    return {
        "query": normalized_query,
        "engine": "searxng",
        "searxng_url": base_url,
        "result_count": len(results),
        "results": results,
    }


def multi_search(
    queries: list[str],
    *,
    max_results_per_query: int = DEFAULT_MAX_RESULTS,
    language: str | None = None,
    categories: str | None = None,
    time_range: str | None = None,
    searxng_url: str | None = None,
) -> dict[str, Any]:
    """Run multiple SearXNG searches and return deduplicated results for deep search."""
    normalized_queries = [query.strip() for query in queries if query.strip()]
    if not normalized_queries:
        raise ValueError("queries must contain at least one non-empty query")
    if len(normalized_queries) > 20:
        raise ValueError("queries must contain at most 20 items")

    searches = [
        search_web(
            query,
            max_results=max_results_per_query,
            language=language,
            categories=categories,
            time_range=time_range,
            searxng_url=searxng_url,
        )
        for query in normalized_queries
    ]

    deduped: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for search in searches:
        for result in search["results"]:
            url = result.get("url", "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            deduped.append({**result, "source_query": search["query"]})

    return {
        "queries": normalized_queries,
        "engine": "searxng",
        "search_count": len(searches),
        "result_count": len(deduped),
        "results": deduped,
        "searches": searches,
    }


def normalize_result(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": string_value(item.get("title")),
        "url": string_value(item.get("url")),
        "content": string_value(item.get("content")),
        "engine": string_value(item.get("engine")),
        "score": item.get("score"),
        "published_date": string_value(item.get("publishedDate") or item.get("published_date")),
    }


def string_value(value: Any) -> str:
    return value if isinstance(value, str) else ""


def clamp_int(value: int, *, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value)))
