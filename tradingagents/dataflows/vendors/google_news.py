"""Company headlines from Google News' public RSS feed (India edition): free, no key."""

from __future__ import annotations

import email.utils
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from urllib.parse import quote_plus

import requests

_URL = "https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"


def headlines(query: str, days: int = 7, limit: int = 15) -> list[dict]:
    """Recent headlines matching ``query``, newest first: title, source, published (UTC), link."""
    q = quote_plus(f"{query} when:{max(1, days)}d")
    response = requests.get(_URL.format(q=q), timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    root = ET.fromstring(response.content)
    cutoff = datetime.now(UTC) - timedelta(days=days)
    items = []
    for item in root.iter("item"):
        try:
            published = email.utils.parsedate_to_datetime(item.findtext("pubDate", "")).astimezone(UTC)
        except (TypeError, ValueError):
            continue
        if published < cutoff:
            continue
        source = item.find("source")
        items.append({
            "title": (item.findtext("title") or "").strip(),
            "source": source.text.strip() if source is not None and source.text else "",
            "published": published,
            "link": item.findtext("link") or "",
        })
    items.sort(key=lambda x: x["published"], reverse=True)
    return items[:limit]
