import re
from typing import Any, Dict, List, Optional


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _bib_escape(s: str) -> str:
    s = _clean(s)
    # very lightweight escaping
    s = s.replace("{", "\\{").replace("}", "\\}")
    return s


def _last_name(author: str) -> str:
    a = _clean(author)
    if not a:
        return "anon"
    parts = a.split()
    return re.sub(r"[^a-zA-Z0-9]+", "", parts[-1].lower()) or "anon"


def _key_for_entry(item: Dict[str, Any]) -> str:
    year = item.get("year") or ""
    try:
        year = str(int(year))
    except Exception:
        year = ""
    authors = item.get("authors") or []
    first = _last_name(authors[0]) if authors else "anon"
    title = _clean(item.get("title") or "")
    word = re.sub(r"[^a-zA-Z0-9]+", "", (title.split() or ["paper"])[0].lower()) if title else "paper"
    return "%s%s%s" % (first, year, word[:20])


def candidate_to_bibtex(item: Dict[str, Any]) -> str:
    title = _bib_escape(item.get("title") or "")
    authors = item.get("authors") or []
    year = item.get("year")
    doi = item.get("doi")
    url = item.get("url") or item.get("pdf_url")

    key = _key_for_entry(item)
    fields = []
    if title:
        fields.append("  title = {%s}" % title)
    if authors:
        fields.append("  author = {%s}" % _bib_escape(" and ".join([_clean(a) for a in authors])))
    if year:
        try:
            fields.append("  year = {%s}" % int(year))
        except Exception:
            pass
    if doi:
        doi0 = _clean(str(doi)).replace("https://doi.org/", "").replace("http://doi.org/", "")
        fields.append("  doi = {%s}" % _bib_escape(doi0))
    if url:
        fields.append("  url = {%s}" % _bib_escape(url))

    entry = "@misc{%s,\n%s\n}\n" % (key, ",\n".join(fields))
    return entry


def export_bibtex(candidates: List[Dict[str, Any]], selected_paper_ids: List[str]) -> str:
    by_id = {c.get("paper_id"): c for c in (candidates or []) if c.get("paper_id")}
    out = []
    seen = set()
    for pid in selected_paper_ids or []:
        if pid in seen:
            continue
        seen.add(pid)
        it = by_id.get(pid)
        if not it:
            continue
        out.append(candidate_to_bibtex(it))
    return "\n".join(out).strip() + "\n"

