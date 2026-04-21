import datetime as _dt
import json
import os
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus
import xml.etree.ElementTree as ET

import requests


ARXIV_APIS = [
    "https://export.arxiv.org/api/query",
    "https://arxiv.org/api/query",
]


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _cache_key(query: str, max_results: int) -> str:
    q = re.sub(r"\s+", " ", (query or "").strip().lower())
    return re.sub(r"[^a-z0-9_-]+", "_", q)[:80] + "_%d" % int(max_results)


def _default_cache_dir() -> Optional[str]:
    d = os.environ.get("LITFUSION_CACHE_DIR")
    if d:
        return d
    # keep artifacts under ignored outputs/
    return "outputs/lit_fusion_demo/.cache"


def search_arxiv(
    query: str,
    max_results: int = 8,
    timeout_s: int = 30,
    retries: int = 3,
    cache: bool = True,
) -> List[Dict[str, Any]]:
    """
    Returns a list of dicts:
      - id (arxiv abs url)
      - arxiv_id (e.g., 2401.01234)
      - title, abstract, authors[], published (YYYY-MM-DD), pdf_url
      - categories[]
      - source='arxiv'
    """

    cache_dir = _default_cache_dir()
    cache_path = None
    if cache and cache_dir:
        try:
            cache_path = os.path.join(cache_dir, "arxiv_%s.json" % _cache_key(query, max_results))
            if os.path.exists(cache_path):
                return json.loads(open(cache_path, "r").read())
        except Exception:
            cache_path = None

    params = "search_query=all:%s&start=0&max_results=%d&sortBy=relevance&sortOrder=descending" % (
        quote_plus(query),
        int(max_results),
    )

    contact = os.environ.get("ARXIV_CONTACT_EMAIL") or "demo@example.com"
    headers = {"User-Agent": "litfusion-demo/0.1 (mailto:%s)" % contact}

    xml = None
    last_err = None
    saw_429 = False
    for base in ARXIV_APIS:
        url = "%s?%s" % (base, params)
        for attempt in range(retries + 1):
            try:
                r = requests.get(url, timeout=timeout_s, headers=headers)
                if r.status_code == 429:
                    saw_429 = True
                    retry_after = r.headers.get("Retry-After")
                    try:
                        wait_s = int(retry_after) if retry_after else 2
                    except Exception:
                        wait_s = 2
                    wait_s = min(30, max(2, wait_s)) * (attempt + 1)
                    time.sleep(wait_s)
                    continue
                r.raise_for_status()
                xml = r.text
                break
            except Exception as e:
                last_err = e
                time.sleep(min(10, 1.2 * (attempt + 1)))
        if xml:
            break
    if not xml:
        if last_err is None and saw_429:
            last_err = RuntimeError("ArXiv rate-limited (HTTP 429) for query: %s" % query)
        if last_err is None:
            last_err = RuntimeError("ArXiv request failed for query: %s" % query)
        raise last_err

    root = ET.fromstring(xml)
    ns = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

    items = []
    for entry in root.findall("a:entry", ns):
        abs_url = _clean(entry.findtext("a:id", default="", namespaces=ns))
        title = _clean(entry.findtext("a:title", default="", namespaces=ns))
        abstract = _clean(entry.findtext("a:summary", default="", namespaces=ns))
        published_raw = _clean(entry.findtext("a:published", default="", namespaces=ns))
        published = None
        if published_raw:
            try:
                published = _dt.datetime.fromisoformat(published_raw.replace("Z", "+00:00")).date().isoformat()
            except Exception:
                published = None

        authors = []
        for a in entry.findall("a:author/a:name", ns):
            if a.text:
                authors.append(_clean(a.text))

        categories = []
        for c in entry.findall("a:category", ns):
            term = c.attrib.get("term")
            if term:
                categories.append(term)

        pdf_url = None
        for link in entry.findall("a:link", ns):
            if link.attrib.get("type") == "application/pdf":
                pdf_url = link.attrib.get("href")
                break

        arxiv_id = None
        if abs_url:
            m = re.search(r"/abs/([^/]+)$", abs_url)
            if m:
                arxiv_id = m.group(1)

        if not title:
            continue

        items.append(
            {
                "id": abs_url or arxiv_id or title,
                "arxiv_id": arxiv_id,
                "title": title,
                "abstract": abstract,
                "authors": authors,
                "published": published,
                "pdf_url": pdf_url,
                "categories": categories,
                "source": "arxiv",
            }
        )

    if cache_path:
        try:
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)  # py3.2+
            with open(cache_path, "w") as f:
                f.write(json.dumps(items, ensure_ascii=False, indent=2, sort_keys=True))
        except Exception:
            pass

    return items
