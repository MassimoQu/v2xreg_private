from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Iterator, List, Optional, Sequence, Tuple


HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
FENCE_RE = re.compile(r"^\s*```")
INLINE_CODE_RE = re.compile(r"`([^`]+)`")


@dataclass(frozen=True)
class MarkdownSection:
    level: int
    heading: str
    parents: Tuple[str, ...]
    start_line: int  # 1-based
    body_start_line: int  # 1-based
    end_line: int  # 1-based, inclusive
    body_lines: Tuple[str, ...]


def parse_sections(lines: Sequence[str]) -> List[MarkdownSection]:
    """
    Parses Markdown headings into "sections".

    A section spans from its heading line until the next heading of the same or
    higher level (i.e. it includes nested sub-sections).
    """
    sections: List[MarkdownSection] = []
    stack: List[dict] = []

    def _close_until(level: int, cur_line_idx_0b: int) -> None:
        nonlocal sections, stack
        while stack and stack[-1]["level"] >= level:
            sec = stack.pop()
            start = sec["body_start_idx"]
            end = cur_line_idx_0b
            body = tuple(lines[start:end])
            # end is a 0-based exclusive index. The last line in the section is
            # end-1 (0b), so the inclusive 1-based line number is `end`.
            end_inclusive_1b = max(sec["start_idx"] + 1, end)
            sections.append(
                MarkdownSection(
                    level=sec["level"],
                    heading=sec["heading"],
                    parents=tuple(sec["parents"]),
                    start_line=sec["start_idx"] + 1,
                    body_start_line=sec["body_start_idx"] + 1,
                    end_line=end_inclusive_1b,
                    body_lines=body,
                )
            )

    in_fence = False
    for i0, line in enumerate(lines):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        m = HEADING_RE.match(line)
        if not m:
            continue
        level = len(m.group(1))
        heading = m.group(2).strip()

        _close_until(level, i0)
        parents = [s["heading"] for s in stack]
        stack.append(
            {
                "level": level,
                "heading": heading,
                "parents": parents,
                "start_idx": i0,
                "body_start_idx": i0 + 1,
            }
        )

    _close_until(0, len(lines))

    # Preserve document order to keep downstream extraction deterministic.
    return sorted(sections, key=lambda s: (s.start_line, s.level, s.heading))


def iter_inline_code_spans(lines: Iterable[str]) -> Iterator[str]:
    in_fence = False
    for line in lines:
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for m in INLINE_CODE_RE.finditer(line):
            yield m.group(1).strip()


def extract_fenced_code_blocks(lines: Sequence[str]) -> List[Tuple[Optional[str], List[str]]]:
    """
    Returns a list of (lang, code_lines).
    """
    blocks: List[Tuple[Optional[str], List[str]]] = []
    in_block = False
    cur_lang: Optional[str] = None
    cur_lines: List[str] = []

    for line in lines:
        if not in_block:
            m = re.match(r"^\s*```(\w+)?\s*$", line)
            if not m:
                continue
            in_block = True
            cur_lang = m.group(1) or None
            cur_lines = []
            continue
        # in_block
        if FENCE_RE.match(line):
            blocks.append((cur_lang, cur_lines))
            in_block = False
            cur_lang = None
            cur_lines = []
            continue
        cur_lines.append(line.rstrip("\n"))

    return blocks
