import re
from typing import Any, Dict, List, Optional, Tuple

import requests


ZOTERO_API = "https://api.zotero.org"


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _creators_to_authors(creators: List[Dict[str, Any]]) -> List[str]:
    out = []
    for c in creators or []:
        if not isinstance(c, dict):
            continue
        name = None
        if c.get("name"):
            name = c.get("name")
        else:
            parts = [c.get("firstName") or "", c.get("lastName") or ""]
            name = " ".join([p for p in parts if p]).strip()
        if name:
            out.append(_clean(name))
    return out


def _extract_year(date_str: Optional[str]) -> Optional[int]:
    if not date_str:
        return None
    m = re.search(r"(19|20)\d{2}", date_str)
    if not m:
        return None
    try:
        return int(m.group(0))
    except Exception:
        return None


def search_zotero_items(
    *,
    api_key: str,
    library_type: str,
    library_id: str,
    query: str,
    limit: int = 25,
    timeout_s: int = 30,
) -> List[Dict[str, Any]]:
    """
    Read-only search over Zotero library items.

    Returns list of dicts (same shape as arxiv items, plus zotero keys):
      - zotero_key, zotero_version
      - title, abstract, authors[], year, url, doi, tags[]
      - source='zotero'
    """

    library_type = (library_type or "user").strip().lower()
    if library_type not in ("user", "group"):
        raise ValueError("library_type must be 'user' or 'group'")

    path = "/%ss/%s/items" % (library_type, library_id)
    url = ZOTERO_API + path

    params = {
        "q": query,
        "qmode": "everything",
        "include": "data",
        "limit": int(limit),
    }
    headers = {"Zotero-API-Key": api_key, "User-Agent": "litfusion-demo/0.1"}
    r = requests.get(url, params=params, headers=headers, timeout=timeout_s)
    r.raise_for_status()
    items = r.json()
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        data = it.get("data") or {}
        title = _clean(data.get("title") or "")
        if not title:
            continue
        abstract = _clean(data.get("abstractNote") or "")
        authors = _creators_to_authors(data.get("creators") or [])
        year = _extract_year(data.get("date") or "")
        doi = _clean(data.get("DOI") or "")
        url0 = _clean(data.get("url") or "")
        tags = []
        for t in data.get("tags") or []:
            if isinstance(t, dict) and t.get("tag"):
                tags.append(_clean(t.get("tag")))

        out.append(
            {
                "id": it.get("key") or title,
                "zotero_key": it.get("key"),
                "zotero_version": it.get("version"),
                "title": title,
                "abstract": abstract,
                "authors": authors,
                "year": year,
                "doi": doi or None,
                "url": url0 or None,
                "tags": tags,
                "source": "zotero",
            }
        )
    return out


def fetch_zotero_items(
    *,
    api_key: str,
    library_type: str,
    library_id: str,
    limit: int = 500,
    page_size: int = 100,
    timeout_s: int = 30,
) -> List[Dict[str, Any]]:
    """
    Fetch (paginate) items from a Zotero library. Read-only.

    Notes:
      - This fetches all item types and filters out attachments/notes.
      - Use `limit` to avoid pulling huge libraries in a demo.
    """

    library_type = (library_type or "user").strip().lower()
    if library_type not in ("user", "group"):
        raise ValueError("library_type must be 'user' or 'group'")

    path = "/%ss/%s/items" % (library_type, library_id)
    url = ZOTERO_API + path
    headers = {"Zotero-API-Key": api_key, "User-Agent": "litfusion-demo/0.1"}

    out: List[Dict[str, Any]] = []
    start = 0
    page_size = max(1, min(int(page_size), 100))
    limit = max(1, int(limit))

    while start < limit:
        params = {
            "include": "data",
            "limit": min(page_size, limit - start),
            "start": start,
        }
        r = requests.get(url, params=params, headers=headers, timeout=timeout_s)
        r.raise_for_status()
        items = r.json() or []
        if not items:
            break
        for it in items:
            if not isinstance(it, dict):
                continue
            data = it.get("data") or {}
            item_type = (data.get("itemType") or "").strip().lower()
            if item_type in ("attachment", "note"):
                continue
            title = _clean(data.get("title") or "")
            if not title:
                continue
            abstract = _clean(data.get("abstractNote") or "")
            authors = _creators_to_authors(data.get("creators") or [])
            year = _extract_year(data.get("date") or "")
            doi = _clean(data.get("DOI") or "")
            url0 = _clean(data.get("url") or "")
            tags = []
            for t in data.get("tags") or []:
                if isinstance(t, dict) and t.get("tag"):
                    tags.append(_clean(t.get("tag")))

            out.append(
                {
                    "paper_id": "zotero:%s" % (it.get("key") or title),
                    "title": title,
                    "authors": authors,
                    "year": year,
                    "abstract": abstract,
                    "doi": doi or None,
                    "url": url0 or None,
                    "tags": tags,
                    "zotero_key": it.get("key"),
                    "zotero_version": it.get("version"),
                    "source": "zotero",
                }
            )
        start += len(items)
        if len(items) < params["limit"]:
            break

    return out
