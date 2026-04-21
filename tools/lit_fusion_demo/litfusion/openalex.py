import json
import os
import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

import requests


OPENALEX_API = "https://api.openalex.org/works"


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _reconstruct_abstract(abstract_inverted_index: Optional[Dict[str, Any]]) -> str:
    if not isinstance(abstract_inverted_index, dict) or not abstract_inverted_index:
        return ""
    max_pos = -1
    for positions in abstract_inverted_index.values():
        if isinstance(positions, list) and positions:
            try:
                max_pos = max(max_pos, max(int(p) for p in positions))
            except Exception:
                continue
    if max_pos < 0:
        return ""

    words = [""] * (max_pos + 1)
    for word, positions in abstract_inverted_index.items():
        if not isinstance(word, str):
            continue
        if not isinstance(positions, list):
            continue
        for p in positions:
            try:
                pi = int(p)
            except Exception:
                continue
            if 0 <= pi < len(words):
                words[pi] = word

    return _clean(" ".join([w for w in words if w]))


def _extract_arxiv_id_from_doi(doi: str) -> Optional[str]:
    if not doi:
        return None
    # Examples:
    # - https://doi.org/10.48550/arxiv.2005.11401
    # - 10.48550/arXiv.2005.11401
    m = re.search(r"arxiv[./](\d{4}\.\d{4,5})(v\d+)?", doi, flags=re.I)
    if not m:
        return None
    return m.group(1) + (m.group(2) or "")


def search_openalex(query: str, max_results: int = 8, timeout_s: int = 30, cache: bool = True) -> List[Dict[str, Any]]:
    """
    Returns a list of dicts:
      - id (openalex url)
      - title, abstract, authors[], year, url, doi, arxiv_id?
      - source='openalex'
    """

    query = _clean(query)
    if not query:
        return []

    cache_dir = os.environ.get("LITFUSION_CACHE_DIR") or "outputs/lit_fusion_demo/.cache"
    cache_path = None
    if cache and cache_dir:
        try:
            key = re.sub(r"[^a-z0-9_-]+", "_", query.lower())[:80] + "_%d" % int(max_results)
            cache_path = os.path.join(cache_dir, "openalex_%s.json" % key)
            if os.path.exists(cache_path):
                return json.loads(open(cache_path, "r").read())
        except Exception:
            cache_path = None

    email = os.environ.get("OPENALEX_EMAIL") or os.environ.get("ARXIV_CONTACT_EMAIL") or "demo@example.com"
    url = "%s?search=%s&per_page=%d&mailto=%s" % (OPENALEX_API, quote_plus(query), int(max_results), quote_plus(email))

    r = requests.get(url, timeout=timeout_s, headers={"User-Agent": "litfusion-demo/0.1"})
    r.raise_for_status()
    data = r.json() or {}
    results = data.get("results") or []

    items: List[Dict[str, Any]] = []
    for it in results:
        if not isinstance(it, dict):
            continue
        title = _clean(it.get("title") or it.get("display_name") or "")
        if not title:
            continue
        doi = _clean(it.get("doi") or "")
        year = it.get("publication_year")
        try:
            year = int(year) if year is not None else None
        except Exception:
            year = None

        authors = []
        for a in (it.get("authorships") or [])[:10]:
            if not isinstance(a, dict):
                continue
            author = a.get("author") or {}
            name = _clean(author.get("display_name") or a.get("raw_author_name") or "")
            if name:
                authors.append(name)

        abstract = _reconstruct_abstract(it.get("abstract_inverted_index"))

        primary_location = it.get("primary_location") or {}
        best_oa = it.get("best_oa_location") or {}
        url0 = _clean(primary_location.get("landing_page_url") or best_oa.get("landing_page_url") or "")
        pdf_url = _clean(primary_location.get("pdf_url") or best_oa.get("pdf_url") or "")
        if not url0 and doi:
            url0 = doi

        arxiv_id = _extract_arxiv_id_from_doi(doi)

        items.append(
            {
                "id": it.get("id"),
                "title": title,
                "abstract": abstract,
                "authors": authors,
                "year": year,
                "url": url0 or None,
                "pdf_url": pdf_url or None,
                "doi": doi or None,
                "arxiv_id": arxiv_id,
                "cited_by_count": it.get("cited_by_count"),
                "source": "openalex",
            }
        )

    if cache_path:
        try:
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            with open(cache_path, "w") as f:
                f.write(json.dumps(items, ensure_ascii=False, indent=2, sort_keys=True))
        except Exception:
            pass

    return items
