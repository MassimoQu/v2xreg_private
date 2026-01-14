import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional, Tuple

from .arxiv import search_arxiv
from .llm import LLMClient
from .openalex import search_openalex


class ResearchProgress(object):
    def __init__(self, total_depth: int, total_breadth: int) -> None:
        self.current_depth = total_depth
        self.total_depth = total_depth
        self.current_breadth = total_breadth
        self.total_breadth = total_breadth
        self.current_query = None  # type: Optional[str]
        self.completed_queries = 0
        self.total_queries = 0


SERP_QUERIES_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "queries": {
            "type": "array",
            "minItems": 2,
            "maxItems": 10,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "query": {"type": "string"},
                    "goal": {"type": "string"},
                },
                "required": ["query", "goal"],
            },
        }
    },
    "required": ["queries"],
}


PROCESS_BRANCH_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "learnings": {
            "type": "array",
            "minItems": 1,
            "maxItems": 8,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"insight": {"type": "string"}, "paper_ids": {"type": "array", "items": {"type": "string"}}},
                "required": ["insight", "paper_ids"],
            },
        },
        "follow_up_questions": {"type": "array", "minItems": 0, "maxItems": 6, "items": {"type": "string"}},
        "recommended_papers": {"type": "array", "minItems": 0, "maxItems": 8, "items": {"type": "string"}},
    },
    "required": ["learnings", "follow_up_questions", "recommended_papers"],
}


def _openalex_to_candidates(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    candidates = []
    for it in items or []:
        paper_id = None
        if it.get("arxiv_id"):
            paper_id = "arxiv:%s" % it.get("arxiv_id")
        elif it.get("doi"):
            paper_id = "doi:%s" % it.get("doi").replace("https://doi.org/", "")
        else:
            paper_id = "openalex:%s" % (it.get("id") or it.get("title") or "")

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
    return candidates


def _anchor_terms(root_topic: str) -> List[str]:
    topic = (root_topic or "").strip()
    if not topic:
        return []
    # Keep short list of anchors: uppercase tokens + meaningful words
    words = re.findall(r"[A-Za-z0-9]+", topic)
    anchors = []
    for w in words:
        if len(w) <= 2:
            continue
        if w.isupper():
            anchors.append(w)
    for w in words:
        wl = w.lower()
        if wl in ("and", "or", "the", "a", "an", "of", "for", "to", "in", "on", "with"):
            continue
        if len(w) <= 3:
            continue
        anchors.append(w)
    # de-dup keep order
    out = []
    seen = set()
    for a in anchors:
        if a.lower() in seen:
            continue
        seen.add(a.lower())
        out.append(a)
    return out[:8]


def _topic_filter_terms(topic: str) -> List[str]:
    """
    Generate a few keywords to filter obviously irrelevant candidates.
    Heuristic, demo-scoped (primarily improves V2X/cooperative perception topics).
    """

    topic = (topic or "").strip()
    if not topic:
        return []
    t = topic.lower()
    extras = []
    if "协同感知" in topic or "cooperative perception" in t or "collaborative perception" in t:
        extras.extend(["v2x", "v2i", "v2v", "vehicle", "infrastructure", "3d object detection", "sensor fusion", "bev"])
    if "v2x" in t or "v2i" in t or "v2v" in t:
        extras.extend(["cooperative", "collaborative", "perception", "fusion"])

    toks = []
    for w in re.findall(r"[A-Za-z0-9]+", topic):
        wl = w.lower()
        if len(wl) <= 2:
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
    return out[:24]


def _contains_term(text: str, term: str) -> bool:
    term = (term or "").strip().lower()
    if not term:
        return False
    if not isinstance(text, str) or not text:
        return False
    if " " in term or "-" in term:
        return term in text
    if len(term) <= 4 and re.match(r"^[a-z0-9]+$", term):
        return re.search(r"\\b%s\\b" % re.escape(term), text) is not None
    return term in text


def _filter_candidates(topic: str, cands: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    terms = _topic_filter_terms(topic) or _anchor_terms(topic)
    if not terms:
        return cands

    kept = []
    for c in cands or []:
        blob = ((c.get("title") or "") + "\n" + (c.get("abstract") or "")).lower()
        if any(_contains_term(blob, t) for t in terms):
            kept.append(c)

    if len(kept) < max(4, int(len(cands or []) * 0.12)):
        return cands
    return kept


def _arxiv_to_candidates(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    candidates = []
    for it in items or []:
        year = None
        if it.get("published"):
            try:
                year = int(it["published"][:4])
            except Exception:
                year = None
        candidates.append(
            {
                "paper_id": "arxiv:%s" % (it.get("arxiv_id") or it.get("id") or ""),
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
    return candidates


def generate_serp_queries(llm: LLMClient, query: str, breadth: int, root_topic: Optional[str] = None) -> List[Dict[str, str]]:
    system = (
        "You are an expert researcher generating diverse search queries.\n"
        "Return ONLY valid JSON."
    )
    anchors = _anchor_terms(root_topic or query)
    anchor_hint = ", ".join(anchors) if anchors else ""
    user = (
        "Given the following research topic/prompt, generate {breadth} unique search queries to explore different facets.\n"
        "For each query, provide a short research goal.\n"
        "Constraint: each query should include at least one anchor term from: {anchors}\n"
        'Prompt: "{query}"\n'
    ).format(breadth=int(breadth), anchors=(anchor_hint or "(no anchors)"), query=query)
    out = []
    try:
        data = llm.complete_json(system=system, user=user, json_schema=SERP_QUERIES_SCHEMA, max_output_tokens=900)
        for it in data.get("queries") or []:
            q = (it.get("query") or "").strip()
            g = (it.get("goal") or "").strip()
            if q and g:
                out.append({"query": q, "goal": g})
    except Exception:
        # Fallback: parse "Query: ... / Goal: ..." text format (gpt-researcher style)
        txt = llm.complete_text(system=system, user=user + "\nFormat as repeated pairs of:\nQuery: ...\nGoal: ...", max_output_tokens=900)
        current = {}
        for raw in (txt or "").splitlines():
            line = raw.strip()
            if not line:
                continue
            # Handle "Query: ... Goal: ..." in one line
            if re.search(r"\\bQuery\\s*:", line, flags=re.I) and re.search(r"\\bGoal\\s*:", line, flags=re.I):
                parts = re.split(r"\\bGoal\\s*:", line, flags=re.I, maxsplit=1)
                q_part = parts[0]
                g_part = parts[1] if len(parts) > 1 else ""
                q_part = re.sub(r"^[-*\\d.)\\s]*Query\\s*:\\s*", "", q_part, flags=re.I).strip()
                g_part = g_part.strip()
                if q_part and g_part:
                    out.append({"query": q_part, "goal": g_part})
                current = {}
                continue
            m = re.match(r"^[-*\\d.)\\s]*Query\\s*:\\s*(.+)$", line, flags=re.I)
            if m:
                if current.get("query") and current.get("goal"):
                    out.append({"query": current["query"], "goal": current["goal"]})
                current = {"query": m.group(1).strip(), "goal": ""}
                continue
            m = re.match(r"^[-*\\d.)\\s]*Goal\\s*:\\s*(.+)$", line, flags=re.I)
            if m and current.get("query"):
                current["goal"] = m.group(1).strip()
                continue
        if current.get("query") and current.get("goal"):
            out.append({"query": current["query"], "goal": current["goal"]})

        if not out:
            # Last resort: split lines as queries, generic goal
            for raw in (txt or "").splitlines():
                q = raw.strip()
                if not q:
                    continue
                if re.match(r"^\\s*(goal|question)\\s*:", q, flags=re.I):
                    continue
                q = re.sub(r"^[-*\\d.)\\s]*Query\\s*:\\s*", "", q, flags=re.I).strip()
                if q:
                    out.append({"query": q, "goal": "Explore this aspect"})

    out = [x for x in out if x.get("query") and x.get("goal")]
    return out[: max(2, min(10, int(breadth)))]


def process_branch(
    llm: LLMClient,
    *,
    branch_query: str,
    branch_goal: str,
    candidates: List[Dict[str, Any]],
) -> Dict[str, Any]:
    system = (
        "You are an expert researcher analyzing candidate papers.\n"
        "Rules:\n"
        "- Use ONLY the provided candidate papers.\n"
        "- Cite papers only by their paper_id.\n"
        "- Do NOT invent papers.\n"
        "Return ONLY valid JSON."
    )
    lines = []
    for c in candidates[:30]:
        lines.append(
            "[%s] %s (%s)\n  authors: %s\n  url: %s\n  abstract: %s"
            % (
                c.get("paper_id"),
                (c.get("title") or "")[:180],
                c.get("year") or "",
                ", ".join((c.get("authors") or [])[:4]),
                c.get("url") or "",
                (c.get("abstract") or "")[:500],
            )
        )
    user = (
        "Branch query: %s\n"
        "Branch research goal: %s\n\n"
        "Candidate papers:\n%s\n\n"
        "Extract:\n"
        "- learnings: 3-8 key insights, each with 1-3 supporting paper_ids\n"
        "- follow_up_questions: up to 6 questions to go deeper\n"
        "- recommended_papers: up to 8 paper_ids worth prioritizing for this branch\n"
        % (branch_query, branch_goal, "\n\n".join(lines))
    )
    try:
        return llm.complete_json(system=system, user=user, json_schema=PROCESS_BRANCH_SCHEMA, max_output_tokens=1400)
    except Exception:
        # Fallback to parse a constrained text format.
        txt = llm.complete_text(
            system=system,
            user=user
            + "\n\nIf JSON is hard, use this format:\n"
            + "Learning (<paper_id,...>): <insight>\n"
            + "Question: <question>\n"
            + "Recommended: <paper_id,...>\n",
            max_output_tokens=1400,
        )

        learnings = []
        questions = []
        recommended = []
        for raw in (txt or "").splitlines():
            line = raw.strip()
            if not line:
                continue
            if re.match(r"^[-*\\d.)\\s]*Question\\s*:\\s*", line, flags=re.I):
                q = re.split(r":", line, 1)[1].strip() if ":" in line else ""
                if q:
                    questions.append(q)
                continue
            if re.match(r"^[-*\\d.)\\s]*Recommended\\s*:\\s*", line, flags=re.I):
                rest = re.split(r":", line, 1)[1] if ":" in line else ""
                ids = re.findall(r"(?:arxiv|doi|openalex|zotero|csl):[^,\\s)]+", rest)
                recommended.extend(ids)
                continue
            if re.match(r"^[-*\\d.)\\s]*Learning\\s*", line, flags=re.I):
                ids = re.findall(r"(?:arxiv|doi|openalex|zotero|csl):[^,\\s)]+", line)
                insight = None
                if ":" in line:
                    insight = line.split(":", 1)[1].strip()
                if insight:
                    learnings.append({"insight": insight, "paper_ids": ids})
                continue

        if not recommended:
            recommended = [c.get("paper_id") for c in candidates[:5] if c.get("paper_id")]
        if not learnings and recommended:
            learnings = [{"insight": "See recommended papers for this branch.", "paper_ids": recommended[:3]}]

        return {
            "learnings": learnings[:8],
            "follow_up_questions": questions[:6],
            "recommended_papers": list(dict.fromkeys(recommended))[:8],
        }


def deep_research(
    llm: LLMClient,
    *,
    query: str,
    breadth: int = 4,
    depth: int = 2,
    concurrency: int = 2,
    per_query_k: int = 6,
    max_total_queries: int = 20,
    root_topic: Optional[str] = None,
    _budget: Optional[Dict[str, int]] = None,
    on_progress: Optional[Callable[[ResearchProgress], None]] = None,
) -> Dict[str, Any]:
    """
    GPT-Researcher-style recursive deep research.
    Returns:
      - learnings: list[{insight, paper_ids}]
      - follow_ups: list[str] (aggregated)
      - candidates: deduped candidate list
      - branches: list[branch results]
    """

    root_topic = root_topic or query
    if _budget is None:
        _budget = {"remaining": int(max_total_queries)}

    progress = ResearchProgress(depth, breadth)
    if on_progress:
        on_progress(progress)

    seen_paper_ids = set()  # type: set
    all_candidates = []  # type: List[Dict[str, Any]]
    all_learnings = []  # type: List[Dict[str, Any]]
    all_followups = []  # type: List[str]
    branches = []  # type: List[Dict[str, Any]]

    def add_candidates(cands: List[Dict[str, Any]]) -> None:
        for c in cands or []:
            pid = c.get("paper_id")
            if not pid or pid in seen_paper_ids:
                continue
            seen_paper_ids.add(pid)
            all_candidates.append(c)

    serp = generate_serp_queries(llm, query, breadth=breadth, root_topic=root_topic)
    # budget guard
    if _budget.get("remaining", 0) <= 0:
        serp = []
    else:
        serp = serp[: int(_budget["remaining"])]
        _budget["remaining"] -= len(serp)
    progress.total_queries = len(serp)

    def run_one(branch: Dict[str, str]) -> Optional[Dict[str, Any]]:
        try:
            bq = branch["query"]
            bg = branch["goal"]

            progress.current_query = bq
            if on_progress:
                on_progress(progress)

            ox_items = search_openalex(bq, max_results=per_query_k)
            cands = _openalex_to_candidates(ox_items)

            if os.environ.get("LITFUSION_USE_ARXIV", "").strip() in ("1", "true", "yes"):
                try:
                    ax_items = search_arxiv(bq, max_results=max(3, int(per_query_k)))
                except Exception:
                    ax_items = []
                cands.extend(_arxiv_to_candidates(ax_items))

            cands = _filter_candidates(root_topic, cands)

            # Deduplicate within this branch
            seen_local = set()
            deduped = []
            for c in cands:
                pid = c.get("paper_id")
                if not pid or pid in seen_local:
                    continue
                seen_local.add(pid)
                deduped.append(c)
            cands = deduped

            add_candidates(cands)

            analyzed = process_branch(llm, branch_query=bq, branch_goal=bg, candidates=cands)

            progress.completed_queries += 1
            if on_progress:
                on_progress(progress)

            return {
                "query": bq,
                "goal": bg,
                "candidates": cands,
                "analysis": analyzed,
            }
        except Exception:
            progress.completed_queries += 1
            if on_progress:
                on_progress(progress)
            return None

    with ThreadPoolExecutor(max_workers=max(1, int(concurrency))) as ex:
        futs = [ex.submit(run_one, b) for b in serp]
        for f in as_completed(futs):
            r = f.result()
            if not r:
                continue
            branches.append(r)
            for l in (r.get("analysis") or {}).get("learnings") or []:
                if isinstance(l, dict) and (l.get("insight") or "").strip():
                    all_learnings.append(l)
            for q in (r.get("analysis") or {}).get("follow_up_questions") or []:
                if isinstance(q, str) and q.strip():
                    all_followups.append(q.strip())

            # recurse for each branch (anchored to root_topic, budget-aware)
            if depth > 1:
                followups = " ".join((r.get("analysis") or {}).get("follow_up_questions") or [])
                next_query = "%s. Focus: %s. Questions: %s" % (root_topic, r.get("goal") or "", followups)
                deeper = deep_research(
                    llm,
                    query=next_query,
                    breadth=max(2, breadth // 2),
                    depth=depth - 1,
                    concurrency=concurrency,
                    per_query_k=max(4, per_query_k // 2),
                    max_total_queries=max_total_queries,
                    root_topic=root_topic,
                    _budget=_budget,
                    on_progress=on_progress,
                )
                for l in deeper.get("learnings") or []:
                    all_learnings.append(l)
                for q in deeper.get("follow_ups") or []:
                    all_followups.append(q)
                add_candidates(deeper.get("candidates") or [])
                branches.extend(deeper.get("branches") or [])

    # Dedup learnings by insight text
    dedup = {}
    for l in all_learnings:
        key = (l.get("insight") or "").strip()
        if not key:
            continue
        if key not in dedup:
            dedup[key] = l
        else:
            # merge paper ids
            cur = dedup[key]
            p = set(cur.get("paper_ids") or [])
            p.update(l.get("paper_ids") or [])
            cur["paper_ids"] = sorted([x for x in p if x])
            dedup[key] = cur

    return {
        "query": query,
        "breadth": breadth,
        "depth": depth,
        "learnings": list(dedup.values()),
        "follow_ups": list(dict.fromkeys(all_followups))[:20],
        "candidates": all_candidates,
        "branches": branches,
    }
