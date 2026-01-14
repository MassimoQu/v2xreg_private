import json
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .llm import LLMClient


def load_index(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError("index.json must be an object")
    if "chunks" not in data or not isinstance(data.get("chunks"), list):
        raise ValueError("index.json missing chunks[]")
    return data


def _tokenize(text: str) -> List[str]:
    # simple latin tokenization for BM25; for Chinese queries use rewrite_query().
    toks = re.findall(r"[a-z0-9]+", (text or "").lower())
    out = []
    for t in toks:
        if len(t) <= 1:
            continue
        out.append(t)
    return out


def _bm25_scores(index: Dict[str, Any], query: str) -> Dict[int, float]:
    bm = index.get("bm25") or {}
    postings = bm.get("postings") or {}
    df = bm.get("df") or {}
    doc_len = bm.get("doc_len") or []
    n_docs = int(bm.get("n_docs") or len(doc_len) or len(index.get("chunks") or []))
    avgdl = float(bm.get("avgdl") or 0.0)
    k1 = float(bm.get("k1") or 1.5)
    b = float(bm.get("b") or 0.75)

    if not isinstance(postings, dict) or not isinstance(df, dict):
        return {}
    if n_docs <= 0 or avgdl <= 0:
        return {}

    terms = _tokenize(query)
    if not terms:
        return {}

    scores = {}
    for t in terms:
        plist = postings.get(t)
        if not plist:
            continue
        dft = float(df.get(t) or 0.0)
        if dft <= 0:
            continue
        # standard BM25 idf (with +1 to keep positive)
        idf = math.log((n_docs - dft + 0.5) / (dft + 0.5) + 1.0)
        for doc_idx, tf in plist:
            try:
                di = int(doc_idx)
                tf = float(tf)
            except Exception:
                continue
            dl = float(doc_len[di]) if 0 <= di < len(doc_len) else 0.0
            denom = tf + k1 * (1.0 - b + b * (dl / avgdl))
            if denom <= 0:
                continue
            s = idf * (tf * (k1 + 1.0) / denom)
            scores[di] = scores.get(di, 0.0) + s
    return scores


def _embedding_scores(llm: LLMClient, index: Dict[str, Any], query: str) -> Dict[int, float]:
    # Requires index_type=embedding and working embeddings endpoint.
    chunks = index.get("chunks") or []
    q_emb = llm.embed_texts([query], model=index.get("embed_model"))[0]
    q_norm = 0.0
    for x in q_emb:
        q_norm += float(x) * float(x)
    q_norm = math.sqrt(q_norm) if q_norm > 0 else 1.0

    scores = {}
    for i, ch in enumerate(chunks):
        emb = ch.get("embedding")
        if not isinstance(emb, list) or not emb:
            continue
        dot = 0.0
        for a, b0 in zip(q_emb, emb):
            dot += float(a) * float(b0)
        denom = q_norm * float(ch.get("norm") or 1.0)
        scores[i] = dot / denom if denom else 0.0
    return scores


def search(
    llm: Optional[LLMClient],
    *,
    index: Dict[str, Any],
    query: str,
    top_k: int = 6,
    mode: str = "hybrid",
) -> List[Dict[str, Any]]:
    mode = (mode or "hybrid").strip().lower()
    if mode not in ("naive", "local", "global", "hybrid"):
        raise ValueError("mode must be naive/local/global/hybrid")

    index_type = (index.get("index_type") or "bm25").strip().lower()
    if index_type == "embedding":
        if not llm:
            raise ValueError("LLMClient required for embedding search")
        scores = _embedding_scores(llm, index, query)
    else:
        scores = _bm25_scores(index, query)

    chunks = index.get("chunks") or []
    if not scores:
        # fallback: return first chunks
        return [{**chunks[i], "score": 0.0} for i in range(min(int(top_k), len(chunks)))]

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)

    def chunk(i, s):
        out = dict(chunks[i])
        out["score"] = float(s)
        return out

    if mode in ("naive", "local"):
        return [chunk(i, s) for i, s in ranked[: int(top_k)]]

    # global/hybrid: aggregate by paper_id
    per_paper = {}
    for i, s in ranked:
        pid = (chunks[i].get("paper_id") or "").strip()
        if not pid:
            continue
        per_paper[pid] = max(per_paper.get(pid, 0.0), float(s))
    top_papers = sorted(per_paper.items(), key=lambda kv: kv[1], reverse=True)[: max(3, int(top_k) // 2)]
    top_paper_ids = set([pid for pid, _ in top_papers])

    if mode == "global":
        # one best chunk per top paper
        out = []
        seen = set()
        for i, s in ranked:
            pid = (chunks[i].get("paper_id") or "").strip()
            if pid in top_paper_ids and pid not in seen:
                out.append(chunk(i, s))
                seen.add(pid)
            if len(out) >= int(top_k):
                break
        return out

    # hybrid: mix top chunks overall + coverage over top papers
    out = []
    used = set()
    for i, s in ranked[: int(top_k)]:
        out.append(chunk(i, s))
        used.add(i)

    for i, s in ranked:
        if i in used:
            continue
        pid = (chunks[i].get("paper_id") or "").strip()
        if pid in top_paper_ids:
            out.append(chunk(i, s))
            used.add(i)
        if len(out) >= int(top_k) + max(2, int(top_k) // 2):
            break
    return out


def rewrite_query(llm: LLMClient, question: str, topic_hint: Optional[str] = None) -> str:
    system = "Rewrite the question into a concise English search query (keywords + abbreviations). Output plain text only."
    user = "Question: %s\nTopic hint: %s" % (question, topic_hint or "")
    q = llm.complete_text(system=system, user=user, max_output_tokens=80, temperature=0.2)
    q = (q or "").strip()
    # strip code fences if any
    q = q.strip("`").strip()
    return q or question


def answer_question(llm: LLMClient, question: str, chunks: List[Dict[str, Any]]) -> str:
    system = (
        "You are a careful research tutor.\n"
        "Use ONLY the provided excerpts.\n"
        "Cite the supporting excerpt ids using backticks like `doi:...#n` / `arxiv:...#n` after each bullet/claim.\n"
        "If the excerpts are insufficient, say what is missing."
    )

    blocks = []
    allowed_ids = []
    for ch in chunks[:12]:
        cid = ch.get("chunk_id") or ""
        pid = ch.get("paper_id") or ""
        title = ch.get("title") or ""
        url = ch.get("url") or ""
        if cid:
            allowed_ids.append(cid)
        blocks.append("[%s] (%s) %s\nurl: %s\ntext: %s" % (cid, pid, title[:160], url, (ch.get("text") or "")[:1200]))

    user = "Question: %s\n\nExcerpts:\n%s" % (question, "\n\n".join(blocks))
    ans = llm.complete_text(system=system, user=user, max_output_tokens=800)

    allowed_set = set([x for x in allowed_ids if x])

    def cited_ids(text: str) -> List[str]:
        return re.findall(r"`([^`]+#[0-9]+)`", text or "")

    def has_only_allowed_citations(text: str) -> bool:
        cits = cited_ids(text)
        if not cits:
            return False
        for c in cits:
            if c not in allowed_set:
                return False
        return True

    if not has_only_allowed_citations(ans or ""):
        allow_hint = ", ".join(["`%s`" % cid for cid in allowed_ids[:40]])
        if len(allowed_ids) > 40:
            allow_hint += " …"
        ans = llm.complete_text(
            system=system,
            user=user
            + "\n\nRewrite your answer.\n"
            + "- Use ONLY these excerpt ids for citations (exactly as shown): %s\n" % allow_hint
            + "- Put at least one citation after each bullet/claim.\n",
            max_output_tokens=900,
        )
    return (ans or "").strip()
