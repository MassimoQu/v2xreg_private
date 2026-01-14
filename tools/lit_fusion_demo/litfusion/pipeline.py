import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .arxiv import search_arxiv
from .deep_research import deep_research
from .library import load_library, simple_search, upsert_many
from .llm import LLMClient
from .openalex import search_openalex
from .zotero import search_zotero_items


DEFAULT_PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "topic_summary": {"type": "string"},
        "queries": {"type": "array", "items": {"type": "string"}, "minItems": 4, "maxItems": 10},
        "subtopics": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 3,
            "maxItems": 10,
        },
    },
    "required": ["topic_summary", "queries", "subtopics"],
}


DEFAULT_CURATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "topic": {"type": "string"},
        "one_sentence_summary": {"type": "string"},
        "key_papers": {"type": "array", "items": {"type": "string"}},
        "surveys": {"type": "array", "items": {"type": "string"}},
        "benchmarks": {"type": "array", "items": {"type": "string"}},
        "datasets": {"type": "array", "items": {"type": "string"}},
        "reading_order": {"type": "array", "items": {"type": "string"}},
        "paper_notes": {
            "type": "object",
            "additionalProperties": {"type": "string"},
        },
        "learning_plan": {"type": "array", "items": {"type": "string"}},
        "practice_questions": {"type": "array", "items": {"type": "string"}},
        "mermaid_graph": {"type": "string"},
    },
    "required": [
        "topic",
        "one_sentence_summary",
        "key_papers",
        "surveys",
        "benchmarks",
        "datasets",
        "reading_order",
        "paper_notes",
        "learning_plan",
        "practice_questions",
        "mermaid_graph",
    ],
}


def _truncate(s: str, n: int = 500) -> str:
    s = (s or "").strip()
    if len(s) <= n:
        return s
    return s[: n - 1].rstrip() + "…"


def _candidate_lines(candidates: List[Dict[str, Any]], max_abstract_chars: int = 380) -> str:
    lines = []
    for c in candidates:
        pid = c.get("paper_id")
        title = c.get("title") or ""
        year = c.get("year") or ""
        authors = ", ".join((c.get("authors") or [])[:4])
        src = c.get("source") or ""
        url = c.get("url") or c.get("id") or ""
        abstract = _truncate(c.get("abstract") or "", max_abstract_chars)
        lines.append(
            "[%s] %s (%s)\n  authors: %s\n  source: %s\n  url: %s\n  abstract: %s"
            % (pid, title, year, authors, src, url, abstract)
        )
    return "\n\n".join(lines)


def _select_candidates_for_curation(topic: str, candidates: List[Dict[str, Any]], max_n: int = 40) -> List[Dict[str, Any]]:
    """
    Keep the LLM prompt within a reasonable size by selecting a high-signal subset.
    """

    max_n = max(12, int(max_n))
    if not candidates:
        return []
    if len(candidates) <= max_n:
        return candidates

    topic_l = (topic or "").lower()
    is_cp = _is_cooperative_perception_topic(topic)

    def title(it):
        return (it.get("title") or "").strip()

    def tl(it):
        return title(it).lower()

    def cited(it):
        try:
            return int(it.get("cited_by_count") or 0)
        except Exception:
            return 0

    def year(it):
        try:
            return int(it.get("year") or 0)
        except Exception:
            return 0

    def is_survey(it):
        s = tl(it)
        return ("survey" in s) or ("review" in s) or ("overview" in s) or ("tutorial" in s)

    def is_dataset(it):
        s = tl(it)
        if ("dataset" in s) or ("benchmark" in s):
            return True
        if not is_cp:
            return False
        # common CP datasets/frameworks
        for k in ["dair", "opv2v", "v2x-sim", "v2xsim", "v2xset", "tumtraf", "v2x-seq", "opencood", "opencda", "v2v4real"]:
            if k in s:
                return True
        return False

    def is_method(it):
        s = tl(it)
        if is_survey(it) or is_dataset(it):
            return False
        if is_cp:
            # Encourage core method terms
            return any(k in s for k in ["cooperative", "collaborative", "v2x", "v2v", "v2i", "fusion", "transformer", "bev", "object detection"])
        return True

    def score(it):
        s = 0.0
        if is_survey(it):
            s += 8.0
        if is_dataset(it):
            s += 9.0
        if is_cp:
            s2 = tl(it)
            if "v2x" in s2 or "v2v" in s2 or "v2i" in s2:
                s += 4.0
            if "cooperative perception" in s2 or "collaborative perception" in s2:
                s += 6.0
        s += min(6.0, (cited(it) ** 0.5) / 3.0)
        s += max(0.0, min(3.0, (year(it) - 2018) / 2.0))
        return s

    picked = []
    seen = set()

    def add_many(items, limit):
        for it in items:
            pid = it.get("paper_id") or it.get("id") or title(it)
            if not pid or pid in seen:
                continue
            seen.add(pid)
            picked.append(it)
            if len(picked) >= limit:
                return

    surveys = sorted([it for it in candidates if is_survey(it)], key=score, reverse=True)
    datasets = sorted([it for it in candidates if is_dataset(it)], key=score, reverse=True)
    methods = sorted([it for it in candidates if is_method(it)], key=score, reverse=True)
    top_cited = sorted(candidates, key=cited, reverse=True)

    add_many(surveys, min(max_n, 10))
    add_many(datasets, min(max_n, len(picked) + 14))
    add_many(methods, min(max_n, len(picked) + 18))
    add_many(top_cited, max_n)

    return picked[:max_n]


def _heuristic_queries(topic: str) -> Dict[str, Any]:
    base = topic.strip()
    return {
        "topic_summary": base,
        "queries": [
            base,
            base + " survey",
            base + " benchmark",
            base + " dataset",
            base + " review",
        ],
        "subtopics": [
            "Foundations / problem setup",
            "Representative methods",
            "Evaluation & benchmarks",
            "Open problems",
        ],
    }


def _select_arxiv_queries(queries: List[str], max_n: int = 3) -> List[str]:
    """
    ArXiv will rate-limit if we fire many queries quickly.
    Select a small, diverse subset.
    """

    queries = [q for q in (queries or []) if isinstance(q, str) and q.strip()]
    if not queries:
        return []

    picked = []

    def pick_if(pred):
        for q in queries:
            if q in picked:
                continue
            if pred(q.lower()):
                picked.append(q)
                return

    # Always include the first query (usually the topic).
    picked.append(queries[0])
    pick_if(lambda s: "survey" in s or "review" in s)
    pick_if(lambda s: "benchmark" in s or "dataset" in s or "evaluation" in s)

    for q in queries:
        if len(picked) >= max_n:
            break
        if q not in picked:
            picked.append(q)

    return picked[:max_n]


_STOPWORDS = set(["and", "or", "the", "a", "an", "of", "for", "to", "in", "on", "with"])
_GENERIC_QUERY_HINTS = ("survey", "review", "benchmark", "dataset", "evaluation", "overview", "tutorial")


def _is_cooperative_perception_topic(topic: str) -> bool:
    t = (topic or "").lower()
    return ("协同感知" in (topic or "")) or ("cooperative perception" in t) or ("collaborative perception" in t)


def _seed_queries_for_topic(topic: str) -> List[str]:
    """
    Add a few high-signal queries for known technical domains to improve recall
    when the planner/deep-research queries drift.
    """

    if not _is_cooperative_perception_topic(topic):
        return []

    return [
        "V2X cooperative perception",
        "collaborative perception autonomous driving",
        "vehicle infrastructure cooperative perception",
        "cooperative 3D object detection V2X",
        "OpenCOOD cooperative perception benchmark",
        "DAIR-V2X dataset cooperative perception",
        "OPV2V dataset cooperative perception",
        "V2XSet dataset cooperative perception",
        "V2X-ViT cooperative perception",
        "Where2comm cooperative perception",
    ]


def _topic_filter_terms(topic: str) -> List[str]:
    """
    Produce a small set of substrings/keywords to filter obviously irrelevant candidates.
    This is intentionally heuristic and conservative: if the filter becomes too strict,
    we fall back to the unfiltered candidate list.
    """

    topic = (topic or "").strip()
    if not topic:
        return []

    t = topic.lower()
    extras = []
    # Lightweight CN -> EN hints for common cases (demo scope)
    if "协同感知" in topic or "车路协同" in topic or "车车协同" in topic:
        extras.extend(
            [
                "cooperative perception",
                "collaborative perception",
                "vehicle-infrastructure",
                "vehicle infrastructure",
                "v2x",
                "v2i",
                "v2v",
                "cooperative 3d object detection",
                "multi-agent",
                "sensor fusion",
                "bev",
            ]
        )
    if "cooperative perception" in t or "collaborative perception" in t:
        extras.extend(
            [
                "v2x",
                "v2i",
                "v2v",
                "vehicle",
                "infrastructure",
                "3d object detection",
                "object detection",
                "sensor fusion",
                "multi-agent",
                "bev",
                "bird's eye view",
                "dair-v2x",
                "opv2v",
                "v2xset",
                "opencood",
            ]
        )
    if "v2x" in t or "v2v" in t or "v2i" in t:
        extras.extend(["vehicle", "infrastructure", "cooperative", "collaborative", "perception", "fusion"])

    # Basic token extraction (English-like)
    toks = []
    for w in re.findall(r"[A-Za-z0-9]+", topic):
        wl = w.lower()
        if len(wl) <= 2:
            continue
        if wl in _STOPWORDS:
            continue
        toks.append(wl)

    out = []
    seen = set()
    for term in toks + [e.lower() for e in extras]:
        term = (term or "").strip()
        if not term or term in seen:
            continue
        seen.add(term)
        out.append(term)
    return out[:30]


def _contains_term(text: str, term: str) -> bool:
    if not term:
        return False
    term = term.strip().lower()
    if not term:
        return False
    if not isinstance(text, str) or not text:
        return False
    if " " in term or "-" in term:
        return term in text
    if len(term) <= 4 and re.match(r"^[a-z0-9]+$", term):
        return re.search(r"\\b%s\\b" % re.escape(term), text) is not None
    return term in text


def _filter_candidates_by_topic(topic: str, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    terms = _topic_filter_terms(topic)
    if not terms:
        return candidates

    topic_l = (topic or "").lower()
    is_cp = ("协同感知" in (topic or "")) or ("cooperative perception" in topic_l) or ("collaborative perception" in topic_l)
    if is_cp:
        kept = []
        explicit_phrases = [
            "cooperative perception",
            "collaborative perception",
            "cooperative infrastructure perception",
            "infrastructure perception",
            "vehicle-infrastructure cooperative",
            "vehicle infrastructure cooperative",
            "vehicle infrastructure cooperation",
        ]
        v2x_terms = [
            "v2x",
            "v2v",
            "v2i",
            "c-v2x",
            "lte-v2x",
            "nr v2x",
            "cellular v2x",
            "vehicle-to-everything",
            "vehicle to everything",
            "vehicle-to-infrastructure",
            "vehicle to infrastructure",
            "vehicle-to-vehicle",
            "vehicle to vehicle",
        ]
        vehicle_terms = [
            "vehicle",
            "vehicular",
            "connected vehicle",
            "autonomous driving",
            "roadside",
            "intersection",
            "traffic",
            "platoon",
            "infrastructure-vehicle",
            "infrastructure vehicle",
        ]
        coop_terms = ["cooperative", "collaborative", "cooperation", "coordination"]
        perception_terms = [
            "perception",
            "object detection",
            "3d object",
            "3d detection",
            "detection",
            "sensor fusion",
            "fusion",
            "bev",
            "bird's eye",
            "bird's-eye",
            "lidar",
            "radar",
            "camera",
        ]
        key_names = [
            "dair-v2x",
            "opv2v",
            "v2xset",
            "v2x-sim",
            "v2xsim",
            "opencood",
            "where2comm",
            "cobevt",
            "cobe",
            "v2x-vit",
        ]

        for c in candidates or []:
            blob = ((c.get("title") or "") + "\n" + (c.get("abstract") or "")).lower()
            if _contains_term(blob, "vggt"):
                kept.append(c)
                continue
            if any(_contains_term(blob, n) for n in key_names):
                kept.append(c)
                continue
            if any(_contains_term(blob, p) for p in explicit_phrases):
                kept.append(c)
                continue

            has_v2x = any(_contains_term(blob, t) for t in v2x_terms)
            has_vehicle = any(_contains_term(blob, t) for t in vehicle_terms)
            has_coop = any(_contains_term(blob, t) for t in coop_terms)
            has_perc = any(_contains_term(blob, t) for t in perception_terms)

            if has_v2x or (has_vehicle and has_coop and has_perc):
                kept.append(c)
        if len(kept) >= max(3, int(len(candidates or []) * 0.06)):
            return kept
        return candidates

    weak = set(["cooperative", "collaborative"])
    strong_terms = [t for t in terms if t not in weak]
    if not strong_terms:
        strong_terms = terms

    kept = []
    for c in candidates or []:
        title = (c.get("title") or "")
        abstract = (c.get("abstract") or "")
        blob = (title + "\n" + abstract).lower()
        strong_hit = any(_contains_term(blob, term) for term in strong_terms)
        weak_hits = 0
        for w in weak:
            if _contains_term(blob, w):
                weak_hits += 1
        if strong_hit or weak_hits >= 2:
            kept.append(c)

    # If filter is too aggressive, fall back to original list.
    if len(kept) < max(6, int(len(candidates or []) * 0.12)):
        return candidates
    return kept


def plan_research(llm: LLMClient, topic: str, use_llm: bool = True) -> Dict[str, Any]:
    if not use_llm:
        return _heuristic_queries(topic)

    system = (
        "You are a research planner. Create search queries and subtopics for a literature survey.\n"
        "If the topic contains non-English terms or acronyms, include alternative English queries and synonyms.\n"
        "Return ONLY valid JSON."
    )
    user = (
        'Topic: "%s"\n'
        "Output JSON with fields:\n"
        "  - topic_summary: one sentence\n"
        "  - queries: 6-10 short search queries (include survey/review/benchmark/dataset)\n"
        "  - subtopics: 5-10 subtopic strings\n"
        % topic
    )
    return llm.complete_json(system=system, user=user, json_schema=DEFAULT_PLAN_SCHEMA)


def plan_from_learnings(llm: LLMClient, topic: str, learnings: List[Dict[str, Any]]) -> Dict[str, Any]:
    system = (
        "You are a research planner.\n"
        "Given a topic and preliminary learnings, produce a good search plan.\n"
        "Include synonyms and alternative query phrasings.\n"
        "Return ONLY valid JSON."
    )
    bullets = []
    for l in learnings or []:
        if not isinstance(l, dict):
            continue
        insight = (l.get("insight") or "").strip()
        if not insight:
            continue
        pids = ", ".join((l.get("paper_ids") or [])[:3])
        if pids:
            bullets.append("- %s (e.g., %s)" % (insight, pids))
        else:
            bullets.append("- %s" % insight)
    user = (
        'Topic: "%s"\n'
        "Preliminary learnings:\n%s\n\n"
        "Output JSON with fields:\n"
        "  - topic_summary: one sentence\n"
        "  - queries: 6-10 short search queries (include survey/review/benchmark/dataset)\n"
        "  - subtopics: 5-10 subtopic strings\n"
        % (topic, "\n".join(bullets[:20]) or "- (none)")
    )
    return llm.complete_json(system=system, user=user, json_schema=DEFAULT_PLAN_SCHEMA, max_output_tokens=900)


def collect_candidates(
    *,
    topic: str,
    queries: List[str],
    arxiv_k: int = 6,
    web_query_max_n: int = 6,
    library_items: Optional[List[Dict[str, Any]]] = None,
    library_k: int = 20,
    zotero_search_k: int = 25,
    zotero: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    candidates = []

    # Web candidates (OpenAlex primary; ArXiv optional)
    web_queries = _select_arxiv_queries(queries, max_n=int(web_query_max_n))
    # Boost recall with a few domain-specific seed queries when applicable.
    for q0 in _seed_queries_for_topic(topic):
        if q0 not in web_queries:
            web_queries.append(q0)
    web_queries = web_queries[: int(web_query_max_n)]
    for q in web_queries:
        try:
            ox_items = search_openalex(q, max_results=arxiv_k)
        except Exception:
            ox_items = []
        for it in ox_items:
            paper_id = None
            if it.get("arxiv_id"):
                paper_id = "arxiv:%s" % it.get("arxiv_id")
            elif it.get("doi"):
                paper_id = "doi:%s" % it.get("doi").replace("https://doi.org/", "")
            else:
                paper_id = "openalex:%s" % (it.get("id") or it.get("title"))

            candidates.append(
                {
                    "paper_id": paper_id,
                    "title": it.get("title"),
                    "authors": it.get("authors") or [],
                    "year": it.get("year"),
                    "abstract": it.get("abstract"),
                    "url": it.get("url") or it.get("id"),
                    "pdf_url": it.get("pdf_url"),
                    "doi": it.get("doi"),
                    "arxiv_id": it.get("arxiv_id"),
                    "cited_by_count": it.get("cited_by_count"),
                    "source": it.get("source") or "openalex",
                }
            )

        if os.environ.get("LITFUSION_USE_ARXIV", "").strip() in ("1", "true", "yes"):
            try:
                arxiv_items = search_arxiv(q, max_results=arxiv_k)
            except Exception:
                arxiv_items = []
            for it in arxiv_items:
                year = None
                if it.get("published"):
                    try:
                        year = int(it["published"][:4])
                    except Exception:
                        year = None
                candidates.append(
                    {
                        "paper_id": "arxiv:%s" % (it.get("arxiv_id") or it.get("id")),
                        "title": it.get("title"),
                        "authors": it.get("authors") or [],
                        "year": year,
                        "abstract": it.get("abstract"),
                        "url": it.get("id"),
                        "pdf_url": it.get("pdf_url"),
                        "arxiv_id": it.get("arxiv_id"),
                        "source": "arxiv",
                    }
                )

    # Local library candidates (optional)
    if library_items:
        seen = set()
        # Only search by topic (avoid generic 'survey'/'benchmark' queries pulling unrelated papers).
        for it in simple_search(library_items, topic, limit=library_k):
            pid = it.get("paper_id") or it.get("id") or it.get("title")
            if pid in seen:
                continue
            seen.add(pid)
            candidates.append(dict(it))

    # Zotero candidates (optional)
    if zotero:
        z_items = search_zotero_items(
            api_key=zotero["api_key"],
            library_type=zotero["library_type"],
            library_id=zotero["library_id"],
            query=topic,
            limit=zotero_search_k,
        )
        for it in z_items:
            candidates.append(
                {
                    "paper_id": "zotero:%s" % (it.get("zotero_key") or it.get("id")),
                    "title": it.get("title"),
                    "authors": it.get("authors") or [],
                    "year": it.get("year"),
                    "abstract": it.get("abstract"),
                    "url": it.get("url"),
                    "doi": it.get("doi"),
                    "zotero_key": it.get("zotero_key"),
                    "source": "zotero",
                    "tags": it.get("tags") or [],
                }
            )

    # Deduplicate via upsert_many using a temporary library list.
    merged = upsert_many([], candidates)

    # Filter obvious cross-domain noise (still best-effort / conservative).
    merged = _filter_candidates_by_topic(topic, merged)

    # Assign stable paper_id after merge (keep existing paper_id if present)
    out = []
    for i, it in enumerate(merged):
        if not it.get("paper_id"):
            it = dict(it)
            it["paper_id"] = "p%d" % (i + 1)
        out.append(it)
    return out


def curate(
    llm: LLMClient,
    *,
    topic: str,
    topic_summary: str,
    subtopics: List[str],
    candidates: List[Dict[str, Any]],
    max_picks: int = 8,
) -> Dict[str, Any]:
    prompt_candidates = _select_candidates_for_curation(topic, candidates, max_n=40)

    # De-duplicate prompt candidates by normalized title to reduce confusion (arXiv vs DOI duplicates, versioned IDs).
    def _norm_title(t):
        t = (t or "").lower()
        t = re.sub(r"\s+", " ", t).strip()
        t = re.sub(r"[^a-z0-9 ]+", "", t)
        return t

    deduped = []
    seen_titles = set()
    for it in prompt_candidates:
        key = _norm_title(it.get("title") or "")
        if not key or key in seen_titles:
            continue
        seen_titles.add(key)
        deduped.append(it)
    prompt_candidates = deduped

    def _is_survey(it):
        t = (it.get("title") or "").lower()
        return ("survey" in t) or ("review" in t) or ("overview" in t) or ("tutorial" in t)

    def _is_dataset(it):
        t = (it.get("title") or "").lower()
        return "dataset" in t

    def _is_benchmark(it):
        t = (it.get("title") or "").lower()
        return "benchmark" in t

    surveys_cand = [c for c in prompt_candidates if _is_survey(c)]
    datasets_cand = [c for c in prompt_candidates if _is_dataset(c)]
    benchmarks_cand = [c for c in prompt_candidates if _is_benchmark(c)]
    methods_cand = [c for c in prompt_candidates if c not in surveys_cand and c not in datasets_cand and c not in benchmarks_cand]

    # ---- Stage 1: Pick ids per category (small JSON, more reliable) ----
    PICK_IDS_SCHEMA = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"ids": {"type": "array", "items": {"type": "string"}, "minItems": 0, "maxItems": 12}},
        "required": ["ids"],
    }

    def _pool_lines(pool):
        lines = []
        for it in (pool or [])[:50]:
            pid = it.get("paper_id") or ""
            ttl = (it.get("title") or "").replace("\n", " ")[:180]
            y = it.get("year") or ""
            cbc = it.get("cited_by_count")
            cbc = str(cbc) if cbc is not None else ""
            lines.append("[%s] %s (%s) cited_by: %s" % (pid, ttl, y, cbc))
        return "\n".join([x for x in lines if x.strip()])

    def _fallback_top(pool, limit):
        def key(it):
            return (int(it.get("cited_by_count") or 0), int(it.get("year") or 0))

        out = []
        for it in sorted(pool or [], key=key, reverse=True):
            pid = it.get("paper_id")
            if pid and pid not in out:
                out.append(pid)
            if len(out) >= int(limit):
                break
        return out

    def _pick_ids(category_name, pool, limit):
        pool = pool or []
        if not pool:
            return []
        allowed = set([it.get("paper_id") for it in pool if it.get("paper_id")])
        system_sel = "You are a strict selector. Return ONLY valid JSON."
        user_sel = (
            'Topic: "%s"\n'
            "Category: %s\n"
            "Pick up to %d paper_ids from the list. Use ONLY ids that appear in the list. No commentary.\n\n"
            "Candidates:\n%s"
            % (topic, category_name, int(limit), _pool_lines(pool))
        )
        data = llm.complete_json(system=system_sel, user=user_sel, json_schema=PICK_IDS_SCHEMA, max_output_tokens=600, retries=1)
        ids = []
        for pid in data.get("ids") or []:
            if pid in allowed and pid not in ids:
                ids.append(pid)
        if not ids:
            ids = _fallback_top(pool, limit)
        return ids[: int(limit)]

    surveys = _pick_ids("surveys/reviews", surveys_cand, max_picks)
    datasets = _pick_ids("datasets", datasets_cand, max_picks)
    benchmarks = _pick_ids("benchmarks", benchmarks_cand, max_picks)
    key_papers = _pick_ids("key papers (methods/systems)", methods_cand, max_picks)

    reading_order = []
    for seq in [surveys, datasets, benchmarks, key_papers]:
        for pid in seq:
            if pid and pid not in reading_order:
                reading_order.append(pid)

    # ---- Stage 2: Generate notes/plan/graph for the selected list ----
    selected = []
    by_id = {c.get("paper_id"): c for c in candidates if c.get("paper_id")}
    for pid in reading_order:
        if pid in by_id:
            selected.append(by_id[pid])

    DETAILS_SCHEMA = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "topic": {"type": "string"},
            "one_sentence_summary": {"type": "string"},
            "paper_notes": {"type": "object", "additionalProperties": {"type": "string"}},
            "learning_plan": {"type": "array", "items": {"type": "string"}, "minItems": 5, "maxItems": 10},
            "practice_questions": {"type": "array", "items": {"type": "string"}, "minItems": 6, "maxItems": 14},
            "mermaid_graph": {"type": "string"},
        },
        "required": ["topic", "one_sentence_summary", "paper_notes", "learning_plan", "practice_questions", "mermaid_graph"],
    }

    system_det = (
        "You are a meticulous research assistant.\n"
        "Use ONLY the provided selected papers. Cite papers ONLY by paper_id.\n"
        "Do NOT invent papers.\n"
        "Return ONLY valid JSON."
    )
    user_det = (
        'Topic: "%s"\n'
        "Planner summary: %s\n"
        "Subtopics: %s\n\n"
        "Selected reading list:\n%s\n\n"
        "Output JSON with:\n"
        "- topic (string)\n"
        "- one_sentence_summary\n"
        "- paper_notes: {paper_id: 1-2 sentences why it matters + what to read}\n"
        "- learning_plan: 7 day-by-day bullet strings\n"
        "- practice_questions: 8-12 questions\n"
        "- mermaid_graph: Mermaid graph TD linking subtopics -> paper_ids\n"
        % (
            topic,
            topic_summary,
            ", ".join(subtopics or []),
            _candidate_lines(selected, max_abstract_chars=260),
        )
    )

    details = llm.complete_json(system=system_det, user=user_det, json_schema=DETAILS_SCHEMA, max_output_tokens=2200)

    allowed_note_keys = set([pid for pid in reading_order if pid])
    notes = details.get("paper_notes")
    if not isinstance(notes, dict):
        notes = {}
    # Some models emit numeric keys ("1","2",...) instead of paper_ids; treat as missing.
    if not (set(notes.keys()) & allowed_note_keys):
        notes = {}

    if (not notes) and selected:
        NOTES_SCHEMA = {
            "type": "object",
            "additionalProperties": False,
            "properties": {"paper_notes": {"type": "object", "additionalProperties": {"type": "string"}}},
            "required": ["paper_notes"],
        }
        lines = []
        for it in selected:
            pid = it.get("paper_id") or ""
            ttl = (it.get("title") or "").replace("\n", " ")[:200]
            y = it.get("year") or ""
            lines.append("[%s] %s (%s)" % (pid, ttl, y))
        system_notes = "Write concise paper notes. Return ONLY valid JSON."
        user_notes = (
            "For each paper_id below, write 1-2 sentences: why it matters + what to read for.\n"
            "Use ONLY these ids as keys.\n\n"
            "Papers:\n%s" % "\n".join(lines)
        )
        notes_data = llm.complete_json(system=system_notes, user=user_notes, json_schema=NOTES_SCHEMA, max_output_tokens=1600, retries=1)
        notes = (notes_data.get("paper_notes") or {}) if isinstance(notes_data, dict) else {}
        if not isinstance(notes, dict):
            notes = {}
        # Keep only valid keys
        notes = {pid: notes[pid] for pid in notes if pid in allowed_note_keys and isinstance(notes[pid], str) and notes[pid].strip()}

    if not notes:
        # Last-resort fallback to avoid empty notes in downstream renderers.
        notes = {}
        for pid in reading_order:
            it = by_id.get(pid) or {}
            ttl = (it.get("title") or "").strip()
            if ttl:
                notes[pid] = "Read for: %s" % ttl[:220]

    curated = {
        "topic": details.get("topic") or topic,
        "one_sentence_summary": details.get("one_sentence_summary") or "",
        "key_papers": key_papers,
        "surveys": surveys,
        "benchmarks": benchmarks,
        "datasets": datasets,
        "reading_order": reading_order,
        "paper_notes": notes,
        "learning_plan": details.get("learning_plan") or [],
        "practice_questions": details.get("practice_questions") or [],
        "mermaid_graph": details.get("mermaid_graph") or "graph TD",
    }

    # Enforce "only from candidate list" post-hoc (defense-in-depth).
    candidate_ids = set([c.get("paper_id") for c in candidates if c.get("paper_id")])

    def filter_ids(ids):
        return [pid for pid in (ids or []) if pid in candidate_ids]

    curated["key_papers"] = filter_ids(curated.get("key_papers"))
    curated["surveys"] = filter_ids(curated.get("surveys"))
    curated["benchmarks"] = filter_ids(curated.get("benchmarks"))
    curated["datasets"] = filter_ids(curated.get("datasets"))
    curated["reading_order"] = filter_ids(curated.get("reading_order"))

    notes = curated.get("paper_notes") or {}
    curated["paper_notes"] = {pid: notes[pid] for pid in notes if pid in candidate_ids}

    if not curated.get("reading_order"):
        order = []
        for k in ["key_papers", "surveys", "benchmarks", "datasets"]:
            for pid in curated.get(k) or []:
                if pid not in order:
                    order.append(pid)
        curated["reading_order"] = order

    return curated


def run_research(
    *,
    topic: str,
    out_dir: Path,
    mode: str = "standard",
    deep_breadth: int = 4,
    deep_depth: int = 2,
    deep_concurrency: int = 2,
    on_progress=None,
    use_llm_planner: bool = True,
    arxiv_k: int = 6,
    include_zotero: bool = True,
    zotero_search_k: int = 25,
    library_path: Optional[Path] = None,
    library_k: int = 20,
) -> Dict[str, Any]:
    llm = LLMClient()

    deep = None
    mode = (mode or "standard").strip().lower()
    if mode not in ("standard", "deep"):
        raise ValueError("mode must be 'standard' or 'deep'")

    if mode == "deep":
        deep = deep_research(
            llm,
            query=topic,
            breadth=int(deep_breadth),
            depth=int(deep_depth),
            concurrency=int(deep_concurrency),
            per_query_k=int(arxiv_k),
            on_progress=on_progress,
        )
        plan = plan_from_learnings(llm, topic, deep.get("learnings") or [])
    else:
        plan = plan_research(llm, topic, use_llm=use_llm_planner)

    zotero = None
    if include_zotero:
        api_key = os.environ.get("ZOTERO_API_KEY")
        library_id = os.environ.get("ZOTERO_LIBRARY_ID")
        library_type = os.environ.get("ZOTERO_LIBRARY_TYPE", "user")
        if api_key and library_id:
            zotero = {"api_key": api_key, "library_id": library_id, "library_type": library_type}

    library_items = None
    if library_path and library_path.exists():
        library_items = load_library(library_path)

    candidates = collect_candidates(
        topic=topic,
        queries=plan.get("queries") or [topic],
        arxiv_k=arxiv_k,
        web_query_max_n=10 if mode == "deep" else 6,
        library_items=library_items,
        library_k=library_k,
        zotero_search_k=zotero_search_k,
        zotero=zotero,
    )

    curated = curate(
        llm,
        topic=topic,
        topic_summary=plan.get("topic_summary") or topic,
        subtopics=plan.get("subtopics") or [],
        candidates=candidates,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "candidates.json").write_text(
        json.dumps(candidates, ensure_ascii=False, indent=2, sort_keys=True)
    )
    (out_dir / "curation.json").write_text(
        json.dumps(curated, ensure_ascii=False, indent=2, sort_keys=True)
    )

    if deep:
        (out_dir / "deep_research.json").write_text(json.dumps(deep, ensure_ascii=False, indent=2, sort_keys=True))

    return {"plan": plan, "candidates": candidates, "curation": curated, "deep_research": deep}
