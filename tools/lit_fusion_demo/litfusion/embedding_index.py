import hashlib
import json
import math
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .llm import LLMClient
from .fulltext import paper_id_to_stem


def _clean_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _sha256(s: str) -> str:
    h = hashlib.sha256()
    h.update((s or "").encode("utf-8", errors="ignore"))
    return h.hexdigest()


def chunk_text(text: str, chunk_size: int = 1800, overlap: int = 200) -> List[str]:
    text = (text or "").replace("\x00", " ")
    text = _clean_ws(text)
    if not text:
        return []
    chunk_size = max(200, int(chunk_size))
    overlap = max(0, min(int(overlap), chunk_size // 2))

    out = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_size)
        out.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(0, end - overlap)
    return [c for c in out if c]


def _cache_path(model: str) -> Path:
    cache_dir = os.environ.get("LITFUSION_CACHE_DIR") or "outputs/lit_fusion_demo/.cache"
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", (model or "embed").strip())[:80]
    return Path(cache_dir) / ("embeddings_%s.json" % safe)


def load_embedding_cache(model: str) -> Dict[str, Any]:
    path = _cache_path(model)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_embedding_cache(model: str, cache: Dict[str, Any]) -> None:
    path = _cache_path(model)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True))


def _norm(vec: List[float]) -> float:
    s = 0.0
    for x in vec:
        try:
            s += float(x) * float(x)
        except Exception:
            continue
    return math.sqrt(s) if s > 0 else 0.0


_STOPWORDS = set(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "to",
        "was",
        "were",
        "with",
        "we",
        "our",
        "you",
        "your",
    ]
)


def _tokenize(text: str) -> List[str]:
    toks = re.findall(r"[a-z0-9]+", (text or "").lower())
    out = []
    for t in toks:
        if len(t) <= 1:
            continue
        if t in _STOPWORDS:
            continue
        out.append(t)
    return out


def _build_bm25(chunks: List[Dict[str, Any]], k1: float = 1.5, b: float = 0.75) -> Dict[str, Any]:
    """
    Build a lightweight BM25 inverted index over chunk texts.
    """

    # First pass: doc lengths and term frequencies
    doc_lens = []
    dfs = {}  # term -> df
    postings = {}  # term -> list of [doc_idx, tf]

    for i, ch in enumerate(chunks):
        tokens = _tokenize(ch.get("text") or "")
        dl = len(tokens)
        doc_lens.append(dl)
        if dl == 0:
            continue
        tf = {}
        for t in tokens:
            tf[t] = tf.get(t, 0) + 1
        for t, c in tf.items():
            dfs[t] = dfs.get(t, 0) + 1
            postings.setdefault(t, []).append([i, c])

    n_docs = len(chunks)
    avgdl = float(sum(doc_lens)) / float(n_docs) if n_docs > 0 else 0.0

    # Prune very common terms to reduce index size
    max_df = int(0.8 * n_docs) if n_docs else 0
    if max_df > 0:
        for t in list(dfs.keys()):
            if dfs[t] > max_df:
                dfs.pop(t, None)
                postings.pop(t, None)

    return {
        "k1": float(k1),
        "b": float(b),
        "n_docs": int(n_docs),
        "avgdl": avgdl,
        "doc_len": doc_lens,
        "df": dfs,
        "postings": postings,
    }


def build_embedding_index(
    llm: LLMClient,
    *,
    papers: List[Dict[str, Any]],
    out_dir: Path,
    embed_model: str,
    chunk_size: int = 1800,
    overlap: int = 200,
    max_papers: int = 12,
    max_chunks_per_paper: int = 80,
    batch_size: int = 16,
) -> Dict[str, Any]:
    """
    Build a lightweight search index for RAG.

    Preferred: OpenAI-compatible embeddings (`index_type=embedding`).
    Fallback: BM25 lexical index (`index_type=bm25`) when embeddings are unavailable.

    Reads full text from <out_dir>/texts when available; otherwise uses abstracts.
    Writes: <out_dir>/index.json
    """

    if not embed_model:
        if getattr(llm, "provider", "").strip().lower() == "ollama":
            embed_model = (os.environ.get("OLLAMA_EMBED_MODEL") or "nomic-embed-text").strip()
        else:
            embed_model = (os.environ.get("OPENAI_EMBED_MODEL") or "text-embedding-3-small").strip()
    else:
        embed_model = embed_model.strip()
    idx = {"index_version": 1, "created_at": int(__import__("time").time()), "chunks": []}

    by_id = {}
    for p in papers or []:
        pid = p.get("paper_id")
        if pid:
            by_id[pid] = p

    picked = []
    for p in papers or []:
        if len(picked) >= int(max_papers):
            break
        pid = p.get("paper_id")
        if pid:
            picked.append(p)

    pending = []  # list of (chunk_key, chunk_dict, text_for_embedding)
    for p in picked:
        pid = p.get("paper_id")
        title = p.get("title") or ""
        url = p.get("url") or p.get("pdf_url") or ""
        fulltext_path = out_dir / "texts" / (paper_id_to_stem(pid) + ".txt")
        text = None
        if fulltext_path.exists():
            try:
                text = fulltext_path.read_text()
            except Exception:
                text = None
        if not text:
            text = p.get("abstract") or ""
        chunks = chunk_text(text, chunk_size=chunk_size, overlap=overlap)[: int(max_chunks_per_paper)]
        for i, ch in enumerate(chunks):
            ch = ch.strip()
            if not ch:
                continue
            key = _sha256(embed_model + "\n" + pid + "\n" + ch)
            row = {
                "chunk_id": "%s#%d" % (pid, i + 1),
                "paper_id": pid,
                "title": title,
                "year": p.get("year"),
                "url": url,
                "source": "fulltext" if fulltext_path.exists() else "abstract",
                "text": ch,
            }
            idx["chunks"].append(row)
            pending.append((key, row, ch))

    # Try embeddings first (best effect). If provider doesn't support embeddings, fall back to BM25.
    cache = load_embedding_cache(embed_model)
    use_embeddings = True
    try:
        # Fill cache hits
        still = []
        for key, row, ch in pending:
            if key in cache:
                emb = cache[key]
                row["embedding"] = emb
                row["norm"] = _norm(emb)
            else:
                still.append((key, row, ch))
        pending = still

        # Embed pending chunks in batches
        if pending:
            batch = []
            batch_meta = []
            for key, row, ch in pending:
                batch.append(ch)
                batch_meta.append((key, row))
                if len(batch) >= int(batch_size):
                    embs = llm.embed_texts(batch, model=embed_model)
                    for (k, r0), e in zip(batch_meta, embs):
                        cache[k] = e
                        r0["embedding"] = e
                        r0["norm"] = _norm(e)
                    batch = []
                    batch_meta = []
            if batch:
                embs = llm.embed_texts(batch, model=embed_model)
                for (k, r0), e in zip(batch_meta, embs):
                    cache[k] = e
                    r0["embedding"] = e
                    r0["norm"] = _norm(e)

        idx["index_type"] = "embedding"
        idx["embed_model"] = embed_model
        save_embedding_cache(embed_model, cache)
    except Exception as e:
        use_embeddings = False
        idx["index_type"] = "bm25"
        idx["embed_error"] = str(e)[:500]

    if not use_embeddings:
        # Ensure chunks have no embedding fields
        for row in idx["chunks"]:
            row.pop("embedding", None)
            row.pop("norm", None)
        # Build BM25 index over chunk texts
        idx["bm25"] = _build_bm25(idx["chunks"])

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.json").write_text(json.dumps(idx, ensure_ascii=False, indent=2, sort_keys=True))
    return idx
