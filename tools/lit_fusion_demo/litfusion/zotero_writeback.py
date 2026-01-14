import json
import re
from typing import Any, Dict, List, Optional, Tuple

import requests

from .zotero import ZOTERO_API, search_zotero_items


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _norm_doi(doi: Optional[str]) -> Optional[str]:
    if not doi:
        return None
    doi = doi.strip()
    doi = doi.replace("https://doi.org/", "").replace("http://doi.org/", "")
    doi = doi.replace("doi:", "")
    doi = doi.strip().lower()
    return doi or None


def _norm_title(title: str) -> str:
    t = (title or "").lower()
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"[^a-z0-9 ]+", "", t)
    return t


class ZoteroClient(object):
    def __init__(self, *, api_key: str, library_type: str, library_id: str, timeout_s: int = 30) -> None:
        self.api_key = api_key
        self.library_type = (library_type or "user").strip().lower()
        self.library_id = (library_id or "").strip()
        self.timeout_s = timeout_s
        if self.library_type not in ("user", "group"):
            raise ValueError("library_type must be 'user' or 'group'")
        if not self.library_id:
            raise ValueError("library_id is required")

    def _base(self) -> str:
        return "%s/%ss/%s" % (ZOTERO_API, self.library_type, self.library_id)

    def _headers(self, if_unmodified_since_version: Optional[int] = None) -> Dict[str, str]:
        h = {"Zotero-API-Key": self.api_key, "Content-Type": "application/json", "User-Agent": "litfusion-demo/0.2"}
        if if_unmodified_since_version is not None:
            h["If-Unmodified-Since-Version"] = str(int(if_unmodified_since_version))
        return h

    def get_item(self, key: str) -> Dict[str, Any]:
        url = self._base() + "/items/%s" % key
        r = requests.get(url, params={"include": "data"}, headers=self._headers(), timeout=self.timeout_s)
        r.raise_for_status()
        return r.json()

    def update_item(self, *, key: str, version: int, data: Dict[str, Any]) -> bool:
        url = self._base() + "/items/%s" % key
        r = requests.put(url, data=json.dumps(data), headers=self._headers(if_unmodified_since_version=version), timeout=self.timeout_s)
        if r.status_code in (200, 204):
            return True
        # if conflict, surface error
        r.raise_for_status()
        return False

    def create_items(self, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        url = self._base() + "/items"
        r = requests.post(url, data=json.dumps(items), headers=self._headers(), timeout=self.timeout_s)
        r.raise_for_status()
        return r.json()

    def create_collection(self, name: str) -> str:
        url = self._base() + "/collections"
        payload = [{"name": name}]
        r = requests.post(url, data=json.dumps(payload), headers=self._headers(), timeout=self.timeout_s)
        r.raise_for_status()
        data = r.json() or {}
        # Response: {"successful": {"0": {"key": "...", "version": ...}}, ...}
        succ = data.get("successful") or {}
        if isinstance(succ, dict) and succ:
            first = succ.get("0") or list(succ.values())[0]
            if isinstance(first, dict) and first.get("key"):
                return first["key"]
        raise RuntimeError("Failed to create collection: %s" % data)


def _ensure_tag_objects(tags: Any) -> List[Dict[str, Any]]:
    out = []
    if isinstance(tags, list):
        for t in tags:
            if isinstance(t, dict) and t.get("tag"):
                out.append({"tag": _clean(t.get("tag")), "type": int(t.get("type") or 0)})
            elif isinstance(t, str) and t.strip():
                out.append({"tag": _clean(t), "type": 0})
    return out


def _merge_tags(existing: Any, new_tags: List[str]) -> List[Dict[str, Any]]:
    cur = _ensure_tag_objects(existing)
    seen = set([t.get("tag") for t in cur if t.get("tag")])
    for t in new_tags:
        t0 = _clean(t)
        if not t0 or t0 in seen:
            continue
        cur.append({"tag": t0, "type": 0})
        seen.add(t0)
    return cur


def find_best_match_in_zotero(
    client: ZoteroClient,
    *,
    candidate: Dict[str, Any],
    prefer_doi: bool = True,
    limit: int = 20,
) -> Optional[str]:
    """
    Try to find a Zotero item key for a candidate paper.
    Uses DOI -> arXiv id -> title fuzzy match.
    """

    if candidate.get("zotero_key"):
        return candidate.get("zotero_key")

    doi = _norm_doi(candidate.get("doi"))
    arxiv_id = (candidate.get("arxiv_id") or "").strip()
    title = _clean(candidate.get("title") or "")

    def search(q: str) -> List[Dict[str, Any]]:
        try:
            return search_zotero_items(
                api_key=client.api_key,
                library_type=client.library_type,
                library_id=client.library_id,
                query=q,
                limit=limit,
            )
        except Exception:
            return []

    if prefer_doi and doi:
        hits = search(doi)
        for h in hits:
            if _norm_doi(h.get("doi")) == doi and h.get("zotero_key"):
                return h.get("zotero_key")

    if arxiv_id:
        hits = search(arxiv_id)
        for h in hits:
            # Zotero DOI sometimes stores 10.48550/arXiv....
            if h.get("zotero_key") and (arxiv_id in (h.get("url") or "") or arxiv_id in (_norm_doi(h.get("doi")) or "")):
                return h.get("zotero_key")

    if title:
        hits = search(title)
        tgt = _norm_title(title)
        best = None
        best_score = -1
        for h in hits:
            ht = _norm_title(h.get("title") or "")
            if not ht:
                continue
            # simple overlap score
            a = set(tgt.split())
            b = set(ht.split())
            if not a or not b:
                continue
            score = int(100 * (len(a & b) / float(len(a | b))))
            if score > best_score and h.get("zotero_key"):
                best = h.get("zotero_key")
                best_score = score
        if best and best_score >= 60:
            return best

    return None


def annotate_from_curation(
    client: ZoteroClient,
    *,
    topic: str,
    candidates: List[Dict[str, Any]],
    curation: Dict[str, Any],
    collection_name: Optional[str] = None,
    apply: bool = False,
    tag_prefix: str = "litfusion",
    add_notes: bool = True,
) -> Dict[str, Any]:
    """
    Add tags/notes (and optional collection) back to Zotero for curated papers.

    Safety: `apply=False` does a dry-run plan only.
    """

    topic_slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", (topic or "").strip().lower()).strip("-") or "topic"
    topic_tag = "%s:topic=%s" % (tag_prefix, topic_slug)

    cand_by_id = {}
    for c in candidates or []:
        pid = c.get("paper_id")
        if pid:
            cand_by_id[pid] = c

    def ids(key: str) -> List[str]:
        return [x for x in (curation.get(key) or []) if x in cand_by_id]

    categories = [
        ("key_papers", "%s:key_paper" % tag_prefix),
        ("surveys", "%s:survey" % tag_prefix),
        ("benchmarks", "%s:benchmark" % tag_prefix),
        ("datasets", "%s:dataset" % tag_prefix),
    ]

    plan = []
    for cat_key, cat_tag in categories:
        for pid in ids(cat_key):
            plan.append((pid, [topic_tag, cat_tag]))

    # Dedup by pid, merge tags
    tag_plan = {}
    for pid, tags in plan:
        tag_plan.setdefault(pid, set()).update(tags)

    collection_key = None
    if collection_name:
        if apply:
            collection_key = client.create_collection(collection_name)
        else:
            collection_key = "<dry-run>"

    actions = []
    for pid, tags in sorted(tag_plan.items()):
        cand = cand_by_id.get(pid) or {}
        zot_key = find_best_match_in_zotero(client, candidate=cand)
        actions.append(
            {
                "paper_id": pid,
                "title": cand.get("title"),
                "zotero_key": zot_key,
                "tags": sorted(list(tags)),
                "note": (curation.get("paper_notes") or {}).get(pid),
            }
        )

    if not apply:
        return {"apply": False, "collection_key": collection_key, "actions": actions}

    # Apply tags/notes
    applied = []
    failed = []
    for a in actions:
        zot_key = a.get("zotero_key")
        if not zot_key:
            failed.append({**a, "error": "no_match"})
            continue
        try:
            raw = client.get_item(zot_key)
            version = raw.get("version")
            data = raw.get("data") or {}
            data["tags"] = _merge_tags(data.get("tags"), a.get("tags") or [])
            if collection_key and collection_key not in ("<dry-run>", None):
                cols = data.get("collections") or []
                if isinstance(cols, list) and collection_key not in cols:
                    cols.append(collection_key)
                    data["collections"] = cols

            ok = client.update_item(key=zot_key, version=int(version or 0), data=data)
            if not ok:
                raise RuntimeError("update_failed")

            if add_notes and a.get("note"):
                note_html = "<p><b>LitFusion</b> (%s)</p><p>%s</p>" % (
                    _clean(topic),
                    _clean(a.get("note")),
                )
                client.create_items(
                    [
                        {
                            "itemType": "note",
                            "note": note_html,
                            "parentItem": zot_key,
                            "tags": [{"tag": topic_tag, "type": 0}],
                        }
                    ]
                )

            applied.append(a)
        except Exception as e:
            failed.append({**a, "error": str(e)})

    return {"apply": True, "collection_key": collection_key, "applied": applied, "failed": failed}

