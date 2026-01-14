import json
import re
from typing import Any, Dict, List, Optional

from .llm import LLMClient


STUDY_PACK_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "topic": {"type": "string"},
        "glossary": {
            "type": "array",
            "minItems": 6,
            "maxItems": 18,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "term": {"type": "string"},
                    "definition": {"type": "string"},
                    "paper_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["term", "definition", "paper_ids"],
            },
        },
        "flashcards": {
            "type": "array",
            "minItems": 8,
            "maxItems": 20,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "question": {"type": "string"},
                    "answer": {"type": "string"},
                    "paper_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["question", "answer", "paper_ids"],
            },
        },
        "mcq": {
            "type": "array",
            "minItems": 6,
            "maxItems": 15,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "question": {"type": "string"},
                    "options": {"type": "array", "minItems": 4, "maxItems": 5, "items": {"type": "string"}},
                    "answer_index": {"type": "integer", "minimum": 0, "maximum": 4},
                    "explanation": {"type": "string"},
                    "paper_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["question", "options", "answer_index", "explanation", "paper_ids"],
            },
        },
    },
    "required": ["topic", "glossary", "flashcards", "mcq"],
}


def _extract_paper_ids_from_report(report: str) -> List[str]:
    return sorted(set(re.findall(r"`((?:arxiv|doi|zotero|csl):[^`]+)`", report or "")))


def generate_study_pack(llm: LLMClient, *, report_md: str, topic_hint: Optional[str] = None) -> Dict[str, Any]:
    ids = _extract_paper_ids_from_report(report_md)
    ids_hint = ", ".join(["`%s`" % i for i in ids[:60]])
    if len(ids) > 60:
        ids_hint += " …"

    system = (
        "You are a study coach.\n"
        "Use ONLY the provided report context.\n"
        "Every item must cite 1-3 paper_ids that appear in the report.\n"
        "Return ONLY valid JSON."
    )
    user = (
        "Topic hint: %s\n"
        "Available paper ids (subset): %s\n\n"
        "Report context:\n\n%s\n\n"
        "Create a study pack JSON with:\n"
        "- topic\n"
        "- glossary: 10-15 key terms with crisp definitions\n"
        "- flashcards: 10-16 Q/A pairs\n"
        "- mcq: 8-12 multiple-choice questions (4-5 options) with answer_index and explanation\n"
        % (topic_hint or "", ids_hint, report_md[:20000])
    )
    pack = llm.complete_json(system=system, user=user, json_schema=STUDY_PACK_SCHEMA, max_output_tokens=2400)

    allowed = set(ids)

    def filter_ids(x):
        return [pid for pid in (x or []) if pid in allowed][:3]

    for item in pack.get("glossary") or []:
        item["paper_ids"] = filter_ids(item.get("paper_ids"))
    for item in pack.get("flashcards") or []:
        item["paper_ids"] = filter_ids(item.get("paper_ids"))
    for item in pack.get("mcq") or []:
        item["paper_ids"] = filter_ids(item.get("paper_ids"))

    return pack


def render_study_pack_md(pack: Dict[str, Any]) -> str:
    md = []
    md.append("# Study Pack: %s" % (pack.get("topic") or ""))
    md.append("")
    md.append("## Glossary")
    md.append("")
    for g in pack.get("glossary") or []:
        md.append("- **%s**: %s (%s)" % (g.get("term"), g.get("definition"), ", ".join(g.get("paper_ids") or [])))
    md.append("")
    md.append("## Flashcards")
    md.append("")
    for fc in pack.get("flashcards") or []:
        md.append("- Q: %s" % (fc.get("question") or ""))
        md.append("  - A: %s (%s)" % ((fc.get("answer") or "").strip(), ", ".join(fc.get("paper_ids") or [])))
    md.append("")
    md.append("## MCQ")
    md.append("")
    for i, q in enumerate(pack.get("mcq") or [], 1):
        md.append("%d. %s" % (i, q.get("question") or ""))
        for j, opt in enumerate(q.get("options") or []):
            md.append("   - %s) %s" % (chr(ord("A") + j), opt))
        ans_i = q.get("answer_index")
        ans_letter = chr(ord("A") + int(ans_i)) if isinstance(ans_i, int) and 0 <= ans_i < 5 else "?"
        md.append("   - Answer: %s — %s (%s)" % (ans_letter, (q.get("explanation") or "").strip(), ", ".join(q.get("paper_ids") or [])))
        md.append("")
    return "\n".join(md).strip() + "\n"

