from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from tools.projectv2_sync.extract import extract_items


def _default_sources(repo_root: Path) -> List[Path]:
    return [
        repo_root / "docs" / "operations" / "benchmark_pending_runs_and_plan_20260224.md",
        repo_root / "docs" / "operations" / "WORKTREE_STATE.md",
    ]


def main(argv: List[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parents[2]

    ap = argparse.ArgumentParser(description="Extract ProjectV2 items (dry-run) from docs/operations markdown.")
    ap.add_argument(
        "--sources",
        nargs="*",
        default=None,
        help="Markdown sources to extract from (default: a minimal ops checklist set).",
    )
    ap.add_argument("--out", default="-", help="Output JSON path, or '-' for stdout.")
    ap.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")
    ap.add_argument("--no-docs", action="store_true", help="Do not emit doc items.")
    ap.add_argument("--no-tasks", action="store_true", help="Do not emit task items.")
    args = ap.parse_args(argv)

    source_paths: List[Path] = []
    if args.sources:
        for s in args.sources:
            p = Path(s)
            if not p.is_absolute():
                p = repo_root / p
            source_paths.append(p)
    else:
        source_paths = _default_sources(repo_root)

    items = extract_items(
        source_paths,
        repo_root=repo_root,
        include_tasks=not args.no_tasks,
        include_docs=not args.no_docs,
    )

    # Stable ordering makes diffs and future sync deterministic.
    def _prio_key(p: Any) -> int:
        if p == "P0":
            return 0
        if p == "P1":
            return 1
        if p == "P2":
            return 2
        return 9

    items_sorted = sorted(
        items,
        key=lambda it: (
            0 if it.item_type == "task" else 1,
            _prio_key(it.priority),
            (it.parent_epic or ""),
            it.title,
            it.uid,
        ),
    )

    def _rel(p: Path) -> str:
        try:
            return p.resolve().relative_to(repo_root.resolve()).as_posix()
        except Exception:
            return p.as_posix()

    payload: Dict[str, Any] = {
        "schema_version": "v2xreg_projectv2_items/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": repo_root.as_posix(),
        "sources": [_rel(p) for p in source_paths],
        "items": [it.to_dict() for it in items_sorted],
    }

    dump_kwargs = {
        "ensure_ascii": False,
        "indent": 2 if args.pretty else None,
        "sort_keys": True,
    }

    if args.out == "-" or args.out.strip() == "":
        print(json.dumps(payload, **dump_kwargs))
        return 0

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = repo_root / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, **dump_kwargs) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
