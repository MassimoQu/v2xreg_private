import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


def _norm_title(title: str) -> str:
    title = (title or "").lower()
    title = re.sub(r"\s+", " ", title).strip()
    title = re.sub(r"[^a-z0-9 ]+", "", title)
    return title


def load_library(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    if not isinstance(data, list):
        raise ValueError("library json must be a list")
    return [x for x in data if isinstance(x, dict)]


def save_library(path: Path, items: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2, sort_keys=True))


def upsert_many(existing: List[Dict[str, Any]], incoming: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Merge by strongest key available: DOI > arxiv_id > normalized title.
    """

    by_doi = {}
    by_arxiv = {}
    by_title = {}
    ordered = []

    def add(item: Dict[str, Any]) -> None:
        doi = (item.get("doi") or "").strip().lower()
        arxiv_id = (item.get("arxiv_id") or "").strip().lower()
        title_key = _norm_title(item.get("title") or "")
        if doi:
            by_doi[doi] = item
        elif arxiv_id:
            by_arxiv[arxiv_id] = item
        elif title_key:
            by_title[title_key] = item
        ordered.append(item)

    for it in existing:
        add(it)

    def merge(dst: Dict[str, Any], src: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(dst)
        for k, v in src.items():
            if v is None:
                continue
            if isinstance(v, str) and not v.strip():
                continue
            if k not in out or out.get(k) in (None, "", [], {}):
                out[k] = v
        # Merge tags if present
        if isinstance(out.get("tags"), list) or isinstance(src.get("tags"), list):
            tags = set()
            for t in (out.get("tags") or []) + (src.get("tags") or []):
                if isinstance(t, str) and t.strip():
                    tags.add(t.strip())
            out["tags"] = sorted(tags)
        return out

    for it in incoming:
        if not isinstance(it, dict):
            continue
        doi = (it.get("doi") or "").strip().lower()
        arxiv_id = (it.get("arxiv_id") or "").strip().lower()
        title_key = _norm_title(it.get("title") or "")

        if doi and doi in by_doi:
            merged = merge(by_doi[doi], it)
            by_doi[doi] = merged
            continue
        if arxiv_id and arxiv_id in by_arxiv:
            merged = merge(by_arxiv[arxiv_id], it)
            by_arxiv[arxiv_id] = merged
            continue
        if title_key and title_key in by_title:
            merged = merge(by_title[title_key], it)
            by_title[title_key] = merged
            continue

        add(it)

    # Rebuild in original order, replacing merged entries where needed
    out_items = []
    seen = set()
    for it in ordered:
        doi = (it.get("doi") or "").strip().lower()
        arxiv_id = (it.get("arxiv_id") or "").strip().lower()
        title_key = _norm_title(it.get("title") or "")

        key = None
        if doi:
            key = ("doi", doi)
            cur = by_doi.get(doi, it)
        elif arxiv_id:
            key = ("arxiv", arxiv_id)
            cur = by_arxiv.get(arxiv_id, it)
        elif title_key:
            key = ("title", title_key)
            cur = by_title.get(title_key, it)
        else:
            key = ("id", it.get("id") or id(it))
            cur = it

        if key in seen:
            continue
        seen.add(key)
        out_items.append(cur)

    return out_items


def simple_search(items: List[Dict[str, Any]], query: str, limit: int = 20) -> List[Dict[str, Any]]:
    """
    Very lightweight scoring over title+abstract+tags.
    """

    q = (query or "").strip().lower()
    if not q:
        return items[:limit]
    terms = [t for t in re.split(r"\s+", q) if t]

    def score(it: Dict[str, Any]) -> int:
        hay = " ".join(
            [
                (it.get("title") or ""),
                (it.get("abstract") or ""),
                " ".join(it.get("tags") or []),
            ]
        ).lower()
        s = 0
        for t in terms:
            if t in hay:
                s += 1
        return s

    ranked = sorted(items, key=score, reverse=True)
    return [it for it in ranked if score(it) > 0][:limit]

