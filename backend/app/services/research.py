import copy
import threading
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from app.config import TAVILY_API_KEY

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
REQUEST_TIMEOUT_SECONDS = 12.0
CACHE_TTL_SECONDS = 900
MAX_RESULTS = 6

RESEARCH_TOPICS = {
    "solar": "Recent solar energy developments and solar generation in India",
    "storage": "Recent battery and energy storage research and innovations",
    "grid": "Recent electricity grid advisories and grid management updates in India",
    "india_policy": "Recent Indian renewable energy and electricity policy regulations",
    "community_energy": "Recent community energy and local energy projects",
    "climate_risks": "Recent climate and weather risks affecting energy availability",
    "renewables": "Recent renewable energy developments in India",
}

_cache: dict[str, tuple[float, dict]] = {}
_cache_lock = threading.Lock()


class ResearchError(Exception):
    pass


class ResearchNotConfigured(ResearchError):
    pass


class ResearchRateLimited(ResearchError):
    pass


class ResearchTimeout(ResearchError):
    pass


class ResearchUnavailable(ResearchError):
    pass


class ResearchInvalidResponse(ResearchError):
    pass


def _clean_url(value) -> tuple[str, str] | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    domain = parsed.hostname.lower()
    filtered_query = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid"}
    ]
    canonical = urlunsplit(
        (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), urlencode(filtered_query), "")
    )
    return canonical, domain


def parse_tavily_results(payload: dict, topic: str) -> dict:
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ResearchInvalidResponse("Tavily returned an invalid search response.")

    results = []
    seen_urls = set()
    for item in payload["results"]:
        if not isinstance(item, dict):
            continue
        title, content = item.get("title"), item.get("content")
        parsed_url = _clean_url(item.get("url"))
        if (
            not isinstance(title, str)
            or not title.strip()
            or not isinstance(content, str)
            or not content.strip()
            or parsed_url is None
        ):
            continue
        canonical_url, domain = parsed_url
        if canonical_url in seen_urls:
            continue
        seen_urls.add(canonical_url)
        published_date = item.get("published_date")
        results.append(
            {
                "title": title.strip()[:300],
                "summary": content.strip()[:900],
                "source_url": item["url"].strip(),
                "source_domain": domain,
                "published_date": published_date if isinstance(published_date, str) else None,
            }
        )
        if len(results) >= MAX_RESULTS:
            break
    return {
        "available": True,
        "source": "Tavily Search",
        "topic": topic,
        "query": RESEARCH_TOPICS[topic],
        "fetched_at": None,
        "results": results,
    }


def search_research(topic: str) -> dict:
    if topic not in RESEARCH_TOPICS:
        raise ValueError("Unsupported research topic.")
    if not TAVILY_API_KEY:
        raise ResearchNotConfigured("Energy research is not configured.")

    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(topic)
        if cached and cached[0] > now:
            return copy.deepcopy(cached[1])

    body = {
        "api_key": TAVILY_API_KEY,
        "query": RESEARCH_TOPICS[topic],
        "topic": "news",
        "search_depth": "basic",
        "max_results": MAX_RESULTS,
        "time_range": "month",
        "include_answer": False,
        "include_raw_content": False,
        "include_published_date": True,
    }
    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = client.post(TAVILY_SEARCH_URL, json=body)
    except httpx.TimeoutException as exc:
        raise ResearchTimeout("Energy research request timed out.") from exc
    except httpx.RequestError as exc:
        raise ResearchUnavailable("Energy research service is temporarily unavailable.") from exc

    if response.status_code == 429:
        raise ResearchRateLimited("Energy research request quota is currently unavailable.")
    if response.status_code in {401, 403}:
        raise ResearchNotConfigured("Energy research credentials were rejected.")
    if response.status_code >= 400:
        raise ResearchUnavailable("Energy research service returned an error.")
    try:
        payload = response.json()
    except (ValueError, TypeError) as exc:
        raise ResearchInvalidResponse("Energy research service returned malformed JSON.") from exc
    if not isinstance(payload, dict) or payload.get("error"):
        raise ResearchUnavailable("Energy research service returned an error response.")

    result = parse_tavily_results(payload, topic)
    from datetime import datetime, timezone

    result["fetched_at"] = datetime.now(timezone.utc).isoformat()
    with _cache_lock:
        _cache[topic] = (time.monotonic() + CACHE_TTL_SECONDS, copy.deepcopy(result))
    return result


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()
