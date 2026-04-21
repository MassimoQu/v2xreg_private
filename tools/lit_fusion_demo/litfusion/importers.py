import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _year_from_csl(it: Dict[str, Any]) -> Optional[int]:
    issued = it.get("issued") or {}
    parts = (issued.get("date-parts") or [])
    if isinstance(parts, list) and parts:
        first = parts[0]
        if isinstance(first, list) and first:
            try:
                y = int(first[0])
                if 1800 <= y <= 2100:
                    return y
            except Exception:
                return None
    # Fallback to "issued": {"raw": "..."} if present
    raw = issued.get("raw") if isinstance(issued, dict) else None
    if isinstance(raw, str):
        m = re.search(r"(19|20)\d{2}", raw)
        if m:
            try:
                return int(m.group(0))
            except Exception:
                return None
    return None


def _authors_from_csl(it: Dict[str, Any]) -> List[str]:
    out = []
    for a in it.get("author") or []:
        if not isinstance(a, dict):
            continue
        if a.get("literal"):
            out.append(_clean(a.get("literal")))
            continue
        name = " ".join([_clean(a.get("given") or ""), _clean(a.get("family") or "")]).strip()
        if name:
            out.append(name)
    return out


def import_csl_json(path: Path) -> List[Dict[str, Any]]:
    """
    Import a CSL-JSON export (e.g., Zotero export format).

    Returns items compatible with LitFusion candidate schema.
    """

    data = json.loads(path.read_text())
    if isinstance(data, dict):
        # Some exporters wrap as {"items":[...]}
        data = data.get("items") or []
    if not isinstance(data, list):
        raise ValueError("CSL JSON must be a list (or an object with 'items').")

    items = []
    for it in data:
        if not isinstance(it, dict):
            continue
        title = _clean(it.get("title") or "")
        if not title:
            continue
        authors = _authors_from_csl(it)
        year = _year_from_csl(it)
        doi = _clean(it.get("DOI") or "")
        url = _clean(it.get("URL") or "")
        abstract = _clean(it.get("abstract") or it.get("note") or "")
        container = _clean(it.get("container-title") or "")

        items.append(
            {
                "paper_id": "csl:%s" % (_clean(it.get("id") or "") or title),
                "title": title,
                "authors": authors,
                "year": year,
                "abstract": abstract,
                "doi": doi or None,
                "url": url or None,
                "venue": container or None,
                "source": "csl-json",
            }
        )

    return items

