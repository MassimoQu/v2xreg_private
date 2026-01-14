from typing import Any, Dict, List, Optional


def _paper_index(candidates: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    idx = {}
    for it in candidates or []:
        pid = it.get("paper_id")
        if pid:
            idx[pid] = it
    return idx


def _fmt_paper_line(it: Dict[str, Any]) -> str:
    title = it.get("title") or ""
    year = it.get("year") or ""
    authors = ", ".join((it.get("authors") or [])[:6])
    url = it.get("url") or it.get("pdf_url") or ""
    src = it.get("source") or ""
    extra = []
    if it.get("doi"):
        extra.append("doi:%s" % it.get("doi"))
    if it.get("arxiv_id"):
        extra.append("arxiv:%s" % it.get("arxiv_id"))
    if extra:
        src = (src + " / " + ", ".join(extra)).strip(" /")
    line = "- `%s` %s (%s) — %s" % (it.get("paper_id") or "", title, year, authors)
    if url:
        line += " — %s" % url
    if src:
        line += " (`%s`)" % src
    return line


def render_markdown(topic: str, plan: Dict[str, Any], candidates: List[Dict[str, Any]], curation: Dict[str, Any]) -> str:
    idx = _paper_index(candidates)

    def section(title: str, ids: List[str]) -> str:
        lines = ["## %s" % title, ""]
        for pid in ids or []:
            it = idx.get(pid)
            if not it:
                lines.append("- `%s` (missing from candidates)" % pid)
                continue
            lines.append(_fmt_paper_line(it))
            note = (curation.get("paper_notes") or {}).get(pid)
            if note:
                lines.append("  - %s" % note.strip())
        lines.append("")
        return "\n".join(lines)

    md = []
    md.append("# %s" % topic)
    md.append("")
    md.append("## TL;DR")
    md.append("")
    md.append((curation.get("one_sentence_summary") or plan.get("topic_summary") or "").strip())
    md.append("")

    md.append(section("Key Papers", curation.get("key_papers") or []))
    md.append(section("Surveys / Reviews", curation.get("surveys") or []))
    md.append(section("Benchmarks", curation.get("benchmarks") or []))
    md.append(section("Datasets", curation.get("datasets") or []))

    md.append("## Reading Order")
    md.append("")
    for i, pid in enumerate(curation.get("reading_order") or [], 1):
        it = idx.get(pid)
        title = it.get("title") if it else ""
        md.append("%d. `%s` %s" % (i, pid, title))
    md.append("")

    md.append("## Learning Plan (7 days)")
    md.append("")
    for d in curation.get("learning_plan") or []:
        md.append("- %s" % d.strip())
    md.append("")

    md.append("## Practice Questions")
    md.append("")
    for q in curation.get("practice_questions") or []:
        md.append("- %s" % q.strip())
    md.append("")

    md.append("## Map (Mermaid)")
    md.append("")
    md.append("```mermaid")
    md.append((curation.get("mermaid_graph") or "graph TD").strip())
    md.append("```")
    md.append("")

    md.append("## Candidate Pool (for traceability)")
    md.append("")
    for it in candidates:
        md.append(_fmt_paper_line(it))
    md.append("")

    return "\n".join(md)

