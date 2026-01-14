#!/usr/bin/env python3
import argparse
import os
import re
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from litfusion.importers import import_csl_json  # noqa: E402
from litfusion.library import load_library, save_library, simple_search, upsert_many  # noqa: E402
from litfusion.llm import LLMClient  # noqa: E402
from litfusion.embedding_index import build_embedding_index  # noqa: E402
from litfusion.fulltext import prepare_fulltext_assets  # noqa: E402
from litfusion.pipeline import run_research  # noqa: E402
from litfusion.rag import answer_question, load_index, rewrite_query, search  # noqa: E402
from litfusion.render import render_markdown  # noqa: E402
from litfusion.study import generate_study_pack, render_study_pack_md  # noqa: E402
from litfusion.zotero import fetch_zotero_items  # noqa: E402
from litfusion.zotero_writeback import ZoteroClient, annotate_from_curation  # noqa: E402
from litfusion.export import export_bibtex  # noqa: E402


def _slug(s: str) -> str:
    out = []
    for ch in (s or "").strip().lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in (" ", "-", "_", "."):
            out.append("-")
    slug = "".join(out)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "topic"


def _default_library_path() -> Path:
    return Path("outputs/lit_fusion_demo/library.json")


def cmd_research(args: argparse.Namespace) -> int:
    out_root = Path(args.out_dir).expanduser().resolve()
    out_dir = out_root / _slug(args.topic)

    def on_progress(p):
        try:
            msg = "[deep] depth %s/%s | %s/%s | %s" % (
                getattr(p, "current_depth", "?"),
                getattr(p, "total_depth", "?"),
                getattr(p, "completed_queries", 0),
                getattr(p, "total_queries", "?"),
                getattr(p, "current_query", "") or "",
            )
            sys.stderr.write(msg.strip() + "\n")
            sys.stderr.flush()
        except Exception:
            pass

    result = run_research(
        topic=args.topic,
        out_dir=out_dir,
        mode=args.mode,
        deep_breadth=args.breadth,
        deep_depth=args.depth,
        deep_concurrency=args.concurrency,
        on_progress=on_progress if args.mode == "deep" else None,
        use_llm_planner=not args.no_llm_plan,
        arxiv_k=args.arxiv_k,
        include_zotero=not args.no_zotero,
        zotero_search_k=args.zotero_k,
        library_path=Path(args.library).expanduser().resolve() if args.library else None,
        library_k=args.library_k,
    )

    md = render_markdown(args.topic, result["plan"], result["candidates"], result["curation"])
    (out_dir / "report.md").write_text(md)

    if args.download_pdfs or args.build_index:
        cand_by_id = {}
        for c in result.get("candidates") or []:
            pid = c.get("paper_id")
            if pid:
                cand_by_id[pid] = c

        cur = result.get("curation") or {}
        ids = cur.get("reading_order") or []
        if not ids:
            ids = (cur.get("key_papers") or []) + (cur.get("surveys") or []) + (cur.get("benchmarks") or []) + (
                cur.get("datasets") or []
            )
        picked = []
        seen = set()
        for pid in ids:
            if pid in seen:
                continue
            seen.add(pid)
            if pid in cand_by_id:
                picked.append(cand_by_id[pid])

        ft = prepare_fulltext_assets(
            picked,
            out_dir=out_dir,
            max_papers=args.pdf_max_papers,
            concurrency=args.io_concurrency,
        )
        (out_dir / "fulltext.json").write_text(__import__("json").dumps(ft, ensure_ascii=False, indent=2, sort_keys=True))

        if args.build_index:
            llm = LLMClient()
            idx = build_embedding_index(
                llm,
                papers=picked,
                out_dir=out_dir,
                embed_model=args.embed_model,
                chunk_size=args.chunk_size,
                overlap=args.chunk_overlap,
                max_papers=args.index_max_papers,
                max_chunks_per_paper=args.max_chunks_per_paper,
            )
            print("Index: %s" % (out_dir / "index.json"))

    print("OK")
    print("Report: %s" % (out_dir / "report.md"))
    print("Curation JSON: %s" % (out_dir / "curation.json"))
    print("Candidates JSON: %s" % (out_dir / "candidates.json"))
    return 0


def cmd_library_import_csl(args: argparse.Namespace) -> int:
    lib_path = Path(args.library).expanduser().resolve()
    incoming = import_csl_json(Path(args.input).expanduser().resolve())
    existing = load_library(lib_path)
    merged = upsert_many(existing, incoming)
    save_library(lib_path, merged)
    print("OK")
    print("Library: %s" % lib_path)
    print("Imported: %d" % len(incoming))
    print("Total: %d" % len(merged))
    return 0


def cmd_zotero_sync(args: argparse.Namespace) -> int:
    api_key = args.api_key or os.environ.get("ZOTERO_API_KEY")
    library_id = args.library_id or os.environ.get("ZOTERO_LIBRARY_ID")
    library_type = args.library_type or os.environ.get("ZOTERO_LIBRARY_TYPE", "user")
    if not api_key or not library_id:
        raise SystemExit("Missing Zotero config. Set ZOTERO_API_KEY + ZOTERO_LIBRARY_ID or pass --api-key/--library-id.")

    lib_path = Path(args.library).expanduser().resolve()
    existing = load_library(lib_path)

    pulled = fetch_zotero_items(
        api_key=api_key,
        library_type=library_type,
        library_id=library_id,
        limit=args.limit,
        page_size=args.page_size,
    )
    merged = upsert_many(existing, pulled)
    save_library(lib_path, merged)

    print("OK")
    print("Library: %s" % lib_path)
    print("Pulled: %d" % len(pulled))
    print("Total: %d" % len(merged))
    return 0


def cmd_zotero_annotate(args: argparse.Namespace) -> int:
    api_key = args.api_key or os.environ.get("ZOTERO_API_KEY")
    library_id = args.library_id or os.environ.get("ZOTERO_LIBRARY_ID")
    library_type = args.library_type or os.environ.get("ZOTERO_LIBRARY_TYPE", "user")
    if not api_key or not library_id:
        raise SystemExit("Missing Zotero config. Set ZOTERO_API_KEY + ZOTERO_LIBRARY_ID or pass --api-key/--library-id.")

    cand = __import__("json").loads(Path(args.candidates).expanduser().read_text())
    cur = __import__("json").loads(Path(args.curation).expanduser().read_text())

    client = ZoteroClient(api_key=api_key, library_type=library_type, library_id=library_id)
    res = annotate_from_curation(
        client,
        topic=args.topic or (cur.get("topic") or ""),
        candidates=cand,
        curation=cur,
        collection_name=args.collection,
        apply=bool(args.apply),
        tag_prefix=args.tag_prefix,
        add_notes=not args.no_notes,
    )
    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(__import__("json").dumps(res, ensure_ascii=False, indent=2, sort_keys=True))
    print("OK")
    print("Result: %s" % out_path)
    if not args.apply:
        print("Dry-run only. Re-run with --apply to write to Zotero.")
    return 0


def cmd_library_search(args: argparse.Namespace) -> int:
    lib_path = Path(args.library).expanduser().resolve()
    items = load_library(lib_path)
    hits = simple_search(items, args.query, limit=args.limit)
    for it in hits:
        print("%s\t%s\t%s" % (it.get("paper_id") or "", it.get("year") or "", it.get("title") or ""))
    return 0


def cmd_export_bibtex(args: argparse.Namespace) -> int:
    candidates = __import__("json").loads(Path(args.candidates).expanduser().read_text())
    curation = __import__("json").loads(Path(args.curation).expanduser().read_text())
    ids = curation.get("reading_order") or []
    if not ids:
        ids = (curation.get("key_papers") or []) + (curation.get("surveys") or []) + (curation.get("benchmarks") or []) + (
            curation.get("datasets") or []
        )
    bib = export_bibtex(candidates, ids)
    out = Path(args.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(bib)
    print("OK")
    print("BibTeX: %s" % out)
    return 0


def cmd_tutor_ask(args: argparse.Namespace) -> int:
    report_path = Path(args.report).expanduser().resolve()
    report = report_path.read_text()
    ids = sorted(set(re.findall(r"`((?:arxiv|doi|zotero|csl):[^`]+)`", report)))
    ids_hint = ", ".join(["`%s`" % i for i in ids[:40]])
    if len(ids) > 40:
        ids_hint += " …"

    system = (
        "You are a careful tutor helping a researcher understand a field.\n"
        "Use ONLY the provided report context. If the report does not contain the answer, say so.\n"
        "When you make a claim, cite at least one paper id from the report, like `arxiv:xxxx.xxxxx` or `doi:...`.\n"
        "Only cite ids that appear in the report.\n"
        "Answer in concise Markdown."
    )
    user = "Available paper ids (subset): %s\n\nReport context:\n\n%s\n\nQuestion: %s" % (ids_hint, report, args.question)
    llm = LLMClient()
    ans = llm.complete_text(system=system, user=user, max_output_tokens=args.max_tokens)

    allowed = set(ids)
    allow_hint2 = ", ".join(["`%s`" % i for i in ids[:120]])
    if len(ids) > 120:
        allow_hint2 += " …"

    def cited_ids(text: str):
        return set(re.findall(r"`((?:arxiv|doi|zotero|csl):[^`]+)`", text or ""))

    # Retry loop: enforce (1) has citations, (2) citations are from the report.
    for _ in range(2):
        cited = cited_ids(ans)
        if not cited:
            ans = llm.complete_text(
                system=system,
                user=user
                + "\n\nRewrite the answer and include citations like `arxiv:...`/`doi:...` on each bullet.\n"
                + "Use ONLY citations from this allowed list:\n%s\n" % allow_hint2,
                max_output_tokens=args.max_tokens,
            )
            continue
        if not cited.issubset(allowed):
            bad = sorted([c for c in cited if c not in allowed])[:20]
            ans = llm.complete_text(
                system=system,
                user=user
                + "\n\nYour previous answer cited ids NOT present in the report: %s\n" % ", ".join(["`%s`" % b for b in bad])
                + "Rewrite and use ONLY citations from this allowed list:\n%s\n" % allow_hint2,
                max_output_tokens=args.max_tokens,
            )
            continue
        break
    print(ans.strip())
    return 0


def cmd_rag_ask(args: argparse.Namespace) -> int:
    index_path = Path(args.index).expanduser().resolve()
    idx = load_index(index_path)

    llm = LLMClient()
    q = args.question
    if args.rewrite:
        q = rewrite_query(llm, args.question, topic_hint=args.topic)

    chunks = search(llm if idx.get("index_type") == "embedding" else None, index=idx, query=q, top_k=args.top_k, mode=args.mode)
    if args.show_context:
        for ch in chunks:
            print("%s\t%.4f\t%s" % (ch.get("chunk_id"), ch.get("score", 0.0), (ch.get("title") or "")[:120]))

    ans = answer_question(llm, args.question, chunks)
    print(ans)
    return 0


def cmd_study_pack(args: argparse.Namespace) -> int:
    report_path = Path(args.report).expanduser().resolve()
    report = report_path.read_text()
    llm = LLMClient()
    pack = generate_study_pack(llm, report_md=report, topic_hint=args.topic)

    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "study_pack.json").write_text(__import__("json").dumps(pack, ensure_ascii=False, indent=2, sort_keys=True))
    (out_dir / "study_pack.md").write_text(render_study_pack_md(pack))

    print("OK")
    print("Study pack JSON: %s" % (out_dir / "study_pack.json"))
    print("Study pack MD: %s" % (out_dir / "study_pack.md"))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="LitFusion demo: DeepTutor-style learning + gpt-researcher-style research report (OpenAlex + Zotero; optional ArXiv)."
    )
    sub = p.add_subparsers(dest="cmd")

    r = sub.add_parser("research", help="Generate a reading list/report for a topic.")
    r.add_argument("--topic", required=True, help="e.g., 'retrieval augmented generation'")
    r.add_argument("--out-dir", default="outputs/lit_fusion_demo", help="output root directory")
    r.add_argument("--arxiv-k", type=int, default=6, help="max OpenAlex results per query (and ArXiv if enabled)")
    r.add_argument("--zotero-k", type=int, default=25, help="max Zotero results")
    r.add_argument("--no-zotero", action="store_true", help="disable Zotero search even if env is set")
    r.add_argument("--no-llm-plan", action="store_true", help="use heuristic queries instead of LLM planning")
    r.add_argument(
        "--mode",
        default="standard",
        choices=["standard", "deep"],
        help="standard: plan->collect->curate; deep: recursive deep-research (breadth/depth/concurrency)",
    )
    r.add_argument("--breadth", type=int, default=4, help="deep mode: branches per depth")
    r.add_argument("--depth", type=int, default=2, help="deep mode: recursion depth")
    r.add_argument("--concurrency", type=int, default=2, help="deep mode: concurrent branches")
    r.add_argument("--library", default=str(_default_library_path()), help="local library json path")
    r.add_argument("--library-k", type=int, default=20, help="max local-library matches per query")
    r.add_argument("--download-pdfs", action="store_true", help="download PDFs for curated reading list (best effort)")
    r.add_argument("--pdf-max-papers", type=int, default=12)
    r.add_argument("--io-concurrency", type=int, default=4)
    r.add_argument(
        "--build-index",
        action="store_true",
        help="build embedding index.json for RAG (default: OLLAMA_EMBED_MODEL for ollama provider; otherwise OPENAI_EMBED_MODEL)",
    )
    r.add_argument(
        "--embed-model",
        default=None,
        help="override embedding model (ollama: e.g., nomic-embed-text; openai: e.g., text-embedding-3-small)",
    )
    r.add_argument("--chunk-size", type=int, default=1800)
    r.add_argument("--chunk-overlap", type=int, default=200)
    r.add_argument("--index-max-papers", type=int, default=12)
    r.add_argument("--max-chunks-per-paper", type=int, default=80)
    r.set_defaults(func=cmd_research)

    lib = sub.add_parser("library", help="Manage local literature library (JSON).")
    lib_sub = lib.add_subparsers(dest="library_cmd")

    lib_import = lib_sub.add_parser("import-csl", help="Import CSL-JSON (e.g., Zotero export).")
    lib_import.add_argument("--input", required=True, help="path to CSL-JSON file")
    lib_import.add_argument("--library", default=str(_default_library_path()), help="local library json path")
    lib_import.set_defaults(func=cmd_library_import_csl)

    lib_search = lib_sub.add_parser("search", help="Search local library.")
    lib_search.add_argument("--query", required=True, help="search query")
    lib_search.add_argument("--library", default=str(_default_library_path()), help="local library json path")
    lib_search.add_argument("--limit", type=int, default=20)
    lib_search.set_defaults(func=cmd_library_search)

    z = sub.add_parser("zotero", help="Zotero helpers (read-only).")
    z_sub = z.add_subparsers(dest="zotero_cmd")
    z_sync = z_sub.add_parser("sync", help="Sync Zotero items into local library.")
    z_sync.add_argument("--library", default=str(_default_library_path()), help="local library json path")
    z_sync.add_argument("--limit", type=int, default=500, help="max items to pull (demo safety cap)")
    z_sync.add_argument("--page-size", type=int, default=100)
    z_sync.add_argument("--api-key", default=None)
    z_sync.add_argument("--library-id", default=None)
    z_sync.add_argument("--library-type", default=None, choices=["user", "group"])
    z_sync.set_defaults(func=cmd_zotero_sync)

    z_ann = z_sub.add_parser("annotate", help="Write back tags/notes for a LitFusion curation (SAFE: dry-run by default).")
    z_ann.add_argument("--candidates", required=True, help="path to candidates.json")
    z_ann.add_argument("--curation", required=True, help="path to curation.json")
    z_ann.add_argument("--topic", default=None, help="override topic tag")
    z_ann.add_argument("--collection", default=None, help="create/add to collection (requires --apply)")
    z_ann.add_argument("--tag-prefix", default="litfusion")
    z_ann.add_argument("--no-notes", action="store_true", help="skip creating Zotero notes")
    z_ann.add_argument("--apply", action="store_true", help="actually write to Zotero (default is dry-run)")
    z_ann.add_argument("--out", default="outputs/lit_fusion_demo/zotero_annotate_result.json")
    z_ann.add_argument("--api-key", default=None)
    z_ann.add_argument("--library-id", default=None)
    z_ann.add_argument("--library-type", default=None, choices=["user", "group"])
    z_ann.set_defaults(func=cmd_zotero_annotate)

    t = sub.add_parser("tutor", help="DeepTutor-like Q&A over a generated report.")
    t_sub = t.add_subparsers(dest="tutor_cmd")
    t_ask = t_sub.add_parser("ask", help="Ask a question based on an existing report.md.")
    t_ask.add_argument("--report", required=True, help="path to report.md")
    t_ask.add_argument("--question", required=True, help="your question")
    t_ask.add_argument("--max-tokens", type=int, default=800)
    t_ask.set_defaults(func=cmd_tutor_ask)

    rag = sub.add_parser("rag", help="RAG over extracted full-text (index.json).")
    rag_sub = rag.add_subparsers(dest="rag_cmd")
    rag_ask = rag_sub.add_parser("ask", help="Ask a question over an index.json (BM25 or embeddings).")
    rag_ask.add_argument("--index", required=True, help="path to index.json")
    rag_ask.add_argument("--question", required=True)
    rag_ask.add_argument("--topic", default=None, help="optional topic hint for query rewrite")
    rag_ask.add_argument("--top-k", type=int, default=6)
    rag_ask.add_argument("--mode", default="hybrid", choices=["naive", "local", "global", "hybrid"])
    rag_ask.add_argument("--rewrite", action="store_true", help="rewrite question into English keywords for better retrieval")
    rag_ask.add_argument("--show-context", action="store_true", help="print retrieved chunk ids/scores")
    rag_ask.set_defaults(func=cmd_rag_ask)

    study = sub.add_parser("study", help="Learning reinforcement: glossary/flashcards/MCQ from a report.")
    study_sub = study.add_subparsers(dest="study_cmd")
    study_pack = study_sub.add_parser("pack", help="Generate study_pack.{json,md} from report.md.")
    study_pack.add_argument("--report", required=True, help="path to report.md")
    study_pack.add_argument("--topic", default=None, help="optional topic hint")
    study_pack.add_argument("--out-dir", default="outputs/lit_fusion_demo/study", help="output directory")
    study_pack.set_defaults(func=cmd_study_pack)

    exp = sub.add_parser("export", help="Export helpers (e.g., BibTeX).")
    exp_sub = exp.add_subparsers(dest="export_cmd")
    exp_bib = exp_sub.add_parser("bibtex", help="Export curated list to BibTeX.")
    exp_bib.add_argument("--candidates", required=True, help="path to candidates.json")
    exp_bib.add_argument("--curation", required=True, help="path to curation.json")
    exp_bib.add_argument("--out", default="outputs/lit_fusion_demo/references.bib")
    exp_bib.set_defaults(func=cmd_export_bibtex)

    return p


def main(argv: list) -> int:
    p = build_parser()
    args = p.parse_args(argv)
    if not getattr(args, "cmd", None):
        p.print_help()
        return 2
    if not hasattr(args, "func"):
        p.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
