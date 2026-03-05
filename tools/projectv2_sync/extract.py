from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from tools.projectv2_sync.markdown import MarkdownSection, extract_fenced_code_blocks, iter_inline_code_spans, parse_sections
from tools.projectv2_sync.models import Item, SourceRef


# Run ids in this repo are typically underscore-delimited and include an 8-digit date.
# Avoid matching filenames like *_20260224.md by excluding dots.
RUN_ID_RE = re.compile(r"\b[a-zA-Z0-9][a-zA-Z0-9_-]*_\d{8}[a-zA-Z0-9_-]*\b")


def _relpath(repo_root: Path, p: Path) -> str:
    try:
        return p.resolve().relative_to(repo_root.resolve()).as_posix()
    except Exception:
        return p.as_posix()


def _uid(prefix: str, key: str) -> str:
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}:{digest}"


def _classify_code_spans(spans: Iterable[str]) -> Dict[str, List[str]]:
    docs: Set[str] = set()
    tools: Set[str] = set()
    artifacts: Set[str] = set()
    configs: Set[str] = set()
    run_ids: Set[str] = set()

    for s in spans:
        if not s or any(ch in s for ch in ["\n", "\r"]):
            continue
        # Drop "template" pseudo-paths like outputs/<run_id>/...
        if "<" in s or ">" in s:
            continue

        if s.endswith(".md") and "/" in s and not s.startswith("http"):
            docs.add(s)
            continue
        if s.startswith("tools/") and s.endswith(".py"):
            tools.add(s)
            continue
        if s.startswith("configs/") or s.startswith("config/"):
            configs.add(s)
            continue
        if s.startswith("outputs/") or s.startswith("data/") or s.startswith("HEAL/") or s.startswith("benchmarks/"):
            artifacts.add(s)
            continue

        # Some run_ids are shown in backticks without a path.
        if "/" not in s and RUN_ID_RE.fullmatch(s):
            run_ids.add(s)

    return {
        "doc_paths": sorted(docs),
        "tool_paths": sorted(tools),
        "artifact_paths": sorted(artifacts),
        "config_paths": sorted(configs),
        "run_ids": sorted(run_ids),
    }


def _classify_paths_from_text(text: str) -> Dict[str, List[str]]:
    """
    Best-effort path extraction from free-form text (including fenced code blocks).

    This complements inline-code extraction because many operational docs contain
    tool paths inside bash snippets without backticks.
    """
    docs: Set[str] = set()
    tools: Set[str] = set()
    artifacts: Set[str] = set()
    configs: Set[str] = set()

    for m in re.finditer(r"((?:docs/operations|HEAL/docs)/[^\s'\"`]+?\.md)\b", text):
        docs.add(m.group(1).rstrip(").,;:"))

    for m in re.finditer(r"(tools/[^\s'\"`]+?\.py)\b", text):
        tools.add(m.group(1).rstrip(").,;:"))

    for m in re.finditer(r"((?:outputs|data|HEAL|benchmarks)/[^\s'\"`]+)", text):
        artifacts.add(m.group(1).rstrip(").,;:"))

    for m in re.finditer(r"((?:configs|config)/[^\s'\"`]+)", text):
        configs.add(m.group(1).rstrip(").,;:"))

    return {
        "doc_paths": sorted(docs),
        "tool_paths": sorted(tools),
        "artifact_paths": sorted(artifacts),
        "config_paths": sorted(configs),
        "run_ids": [],
    }


def _extract_run_ids(text: str) -> List[str]:
    run_ids: Set[str] = set()

    # 1) Explicit CLI flags inside fenced code blocks.
    for m in re.finditer(r"--run-id\s+([A-Za-z0-9][A-Za-z0-9_-]+)", text):
        run_ids.add(m.group(1))

    # 2) Free-form tokens (e.g. shown in prose or embedded in paths).
    for m in RUN_ID_RE.finditer(text):
        tok = m.group(0)
        # Avoid treating doc stems like "..._20260224.md" as run ids.
        tail = text[m.end() : m.end() + 16]
        if tail.startswith(".md") or tail.startswith(".py") or tail.startswith(".json") or tail.startswith(".yaml") or tail.startswith(".yml"):
            continue
        # Directory naming convention: outputs/full_bench_<run_id>/...
        if tok.startswith("full_bench_"):
            run_ids.add(tok[len("full_bench_") :])
            continue
        run_ids.add(tok)

    return sorted(run_ids)


def _infer_priority(title: str, parent_epic: Optional[str]) -> Optional[str]:
    t = title.strip()
    if t.startswith("P0"):
        return "P0"
    if t.startswith("P1"):
        return "P1"
    if t.startswith("P2"):
        return "P2"
    if t.startswith("A)") and parent_epic and "待跑实验" in parent_epic:
        return "P0"
    if t.startswith("B)") and parent_epic and "待跑实验" in parent_epic:
        return "P1"
    if t.startswith("C)") and parent_epic and "待跑实验" in parent_epic:
        return "P2"
    if parent_epic and "Next" in parent_epic:
        return "P1"
    return None


def _infer_next_action(refs: Dict[str, List[str]], body_lines: Sequence[str]) -> Optional[str]:
    if refs.get("tool_paths"):
        # Prefer the tool that looks like the first actionable step.
        for kw in ["precompute", "run_", "summarize", "build_", "validate", "merge_"]:
            for p in refs["tool_paths"]:
                if kw in p:
                    return "Run {}".format(p)
        return "Run {}".format(refs["tool_paths"][0])
    if refs.get("run_ids"):
        return "Execute run_id {}".format(refs["run_ids"][0])

    blocks = extract_fenced_code_blocks(list(body_lines))
    for lang, code in blocks:
        # We only want a single representative command line.
        for line in code:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            # Skip env-var assignments; prefer actual invocations.
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", s):
                continue
            if "python" in s or s.startswith("tmux ") or s.startswith(".micromamba") or s.startswith("bash "):
                return s
            # Fallback: still return something deterministic.
            return s

    if refs.get("artifact_paths"):
        return "Inspect {}".format(refs["artifact_paths"][0])
    if refs.get("doc_paths"):
        return "Read {}".format(refs["doc_paths"][0])
    return None


def _make_task_item(
    *,
    repo_root: Path,
    source_path: Path,
    title: str,
    parent_epic: Optional[str],
    priority: Optional[str],
    status: str,
    body_lines: Sequence[str],
    source_line: int,
    source_heading: Optional[str],
) -> Item:
    text = "\n".join(body_lines)

    spans = list(iter_inline_code_spans(body_lines))
    refs_inline = _classify_code_spans(spans)
    refs_text = _classify_paths_from_text(text)

    merged: Dict[str, List[str]] = {}
    for k in ["doc_paths", "tool_paths", "artifact_paths", "config_paths"]:
        merged[k] = sorted(set(refs_inline.get(k, [])) | set(refs_text.get(k, [])))

    run_ids = _extract_run_ids(text)
    merged["run_ids"] = run_ids

    next_action = _infer_next_action(merged, body_lines)

    uid_key = "{}\n{}".format(_relpath(repo_root, source_path), title)
    return Item(
        uid=_uid("task", uid_key),
        title=title,
        item_type="task",
        priority=priority,
        status=status,
        parent_epic=parent_epic,
        depends_on=[],
        next_action=next_action,
        artifact_link=(merged["artifact_paths"][0] if merged["artifact_paths"] else None),
        config_path=(merged["config_paths"][0] if merged["config_paths"] else None),
        run_id=(run_ids[0] if run_ids else None),
        doc_paths=merged["doc_paths"],
        tool_paths=merged["tool_paths"],
        artifact_paths=merged["artifact_paths"],
        config_paths=merged["config_paths"],
        run_ids=run_ids,
        source=SourceRef(path=_relpath(repo_root, source_path), line=source_line, heading=source_heading),
    )


def _make_doc_item(*, repo_root: Path, doc_path: str, referenced_by: Sequence[str]) -> Item:
    uid = "doc:{}".format(doc_path)
    doc_parent = Path(doc_path).parent.as_posix()
    return Item(
        uid=uid,
        title=Path(doc_path).name,
        item_type="doc",
        priority=None,
        status="reference",
        parent_epic=doc_parent,
        depends_on=[],
        next_action="Read {}".format(doc_path),
        artifact_link=doc_path,
        doc_paths=[doc_path],
        artifact_paths=[doc_path],
        referenced_by=sorted(set(referenced_by)),
        source=None,
    )


def _extract_docs_from_file(path: Path, *, repo_root: Path) -> Dict[str, Set[str]]:
    # doc_path -> set(referenced_by_relpath)
    doc_map: Dict[str, Set[str]] = {}
    text = path.read_text(encoding="utf-8")
    for span in iter_inline_code_spans(text.splitlines(True)):
        if "<" in span or ">" in span:
            continue
        if span.endswith(".md") and "/" in span and not span.startswith("http"):
            doc_map.setdefault(span, set()).add(_relpath(repo_root, path))
    # Always include the doc itself as a "Doc" item.
    rel = _relpath(repo_root, path)
    doc_map.setdefault(rel, set()).add(rel)
    return doc_map


def extract_items_from_benchmark_pending(path: Path, *, repo_root: Path) -> List[Item]:
    lines = path.read_text(encoding="utf-8").splitlines(True)
    sections = parse_sections(lines)

    items: List[Item] = []

    for sec in sections:
        if sec.level != 3:
            continue
        parent_epic = sec.parents[-1] if sec.parents else None
        title = sec.heading
        priority = _infer_priority(title, parent_epic)
        items.append(
            _make_task_item(
                repo_root=repo_root,
                source_path=path,
                title=title,
                parent_epic=parent_epic,
                priority=priority,
                status="todo",
                body_lines=sec.body_lines,
                source_line=sec.start_line,
                source_heading=sec.heading,
            )
        )

    # "统一汇总与出图" tasks are numbered list items, not headings.
    summary_sec: Optional[MarkdownSection] = None
    for sec in sections:
        if sec.level == 2 and ("统一汇总与出图" in sec.heading):
            summary_sec = sec
            break

    if summary_sec is not None:
        starts: List[Tuple[int, str]] = []
        for idx0, raw in enumerate(summary_sec.body_lines):
            m = re.match(r"^\s*(\d+)\)\s*(.+?)\s*$", raw)
            if not m:
                continue
            starts.append((idx0, m.group(2).strip()))

        for k, (idx0, title) in enumerate(starts):
            idx1 = starts[k + 1][0] if (k + 1) < len(starts) else len(summary_sec.body_lines)
            block = summary_sec.body_lines[idx0:idx1]
            items.append(
                _make_task_item(
                    repo_root=repo_root,
                    source_path=path,
                    title=title,
                    parent_epic=summary_sec.heading,
                    priority="P1",
                    status="todo",
                    body_lines=block,
                    source_line=summary_sec.body_start_line + idx0,
                    source_heading=summary_sec.heading,
                )
            )

    # Add light dependency edges inside this document.
    a = next((it for it in items if it.title.startswith("A)")), None)
    b = next((it for it in items if it.title.startswith("B)")), None)
    c = next((it for it in items if it.title.startswith("C)")), None)
    p0s = [it for it in items if (it.priority == "P0" and it.title.startswith("P0-"))]

    if b is not None:
        deps = []
        if a is not None:
            deps.append(a.uid)
        deps.extend([it.uid for it in p0s])
        b.depends_on = sorted(set(deps))

    if c is not None and b is not None:
        c.depends_on = sorted(set(c.depends_on + [b.uid]))

    if b is not None:
        for it in items:
            if it.parent_epic and "统一汇总与出图" in it.parent_epic:
                it.depends_on = sorted(set(it.depends_on + [b.uid]))

    return items


def extract_items_from_worktree_state(path: Path, *, repo_root: Path) -> List[Item]:
    lines = path.read_text(encoding="utf-8").splitlines(True)
    sections = parse_sections(lines)

    items: List[Item] = []

    next_sec: Optional[MarkdownSection] = None
    for sec in sections:
        if sec.level == 2 and ("Next" in sec.heading or "TODO" in sec.heading or "Next" in "".join(sec.parents)):
            if "High-Value TODOs" in sec.heading or sec.heading.startswith("7)"):
                next_sec = sec
                break

    if next_sec is not None:
        i = 0
        body = list(next_sec.body_lines)
        while i < len(body):
            raw = body[i]
            m = re.match(r"^\s*-\s+(.*?)\s*$", raw)
            if not m:
                i += 1
                continue
            title = m.group(1).strip()
            if not title:
                i += 1
                continue

            # Collect indented sub-bullets as the "next action" hint.
            j = i + 1
            sub_actions: List[str] = []
            while j < len(body):
                msub = re.match(r"^\s{2,}-\s+(.*?)\s*$", body[j])
                if not msub:
                    break
                sub_actions.append(msub.group(1).strip())
                j += 1

            item = _make_task_item(
                repo_root=repo_root,
                source_path=path,
                title=title,
                parent_epic=next_sec.heading,
                priority=_infer_priority(title, next_sec.heading),
                status="todo",
                body_lines=body[i:j],
                source_line=next_sec.body_start_line + i,
                source_heading=next_sec.heading,
            )
            if sub_actions and not item.next_action:
                item.next_action = sub_actions[0]
            items.append(item)
            i = j

    return items


def extract_items(
    source_paths: Sequence[Path],
    *,
    repo_root: Path,
    include_tasks: bool = True,
    include_docs: bool = True,
) -> List[Item]:
    items: List[Item] = []

    # doc_path -> set(referenced_by)
    doc_refs: Dict[str, Set[str]] = {}
    for p in source_paths:
        for doc_path, refs in _extract_docs_from_file(p, repo_root=repo_root).items():
            doc_refs.setdefault(doc_path, set()).update(refs)

    if include_tasks:
        for p in source_paths:
            name = p.name
            if name == "WORKTREE_STATE.md":
                items.extend(extract_items_from_worktree_state(p, repo_root=repo_root))
                continue
            if name.startswith("benchmark_pending_runs_and_plan_") and name.endswith(".md"):
                items.extend(extract_items_from_benchmark_pending(p, repo_root=repo_root))
                continue

    if include_docs:
        for doc_path, refs in doc_refs.items():
            items.append(_make_doc_item(repo_root=repo_root, doc_path=doc_path, referenced_by=sorted(refs)))

    # Deduplicate by uid, and merge doc referenced_by if needed.
    by_uid: Dict[str, Item] = {}
    for it in items:
        if it.uid not in by_uid:
            by_uid[it.uid] = it
            continue
        existing = by_uid[it.uid]
        if it.item_type == "doc":
            existing.referenced_by = sorted(set(existing.referenced_by + it.referenced_by))

    return list(by_uid.values())
