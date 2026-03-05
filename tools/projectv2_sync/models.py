from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Literal, Optional


ItemType = Literal["task", "doc"]


@dataclass(frozen=True)
class SourceRef:
    path: str
    line: int
    heading: Optional[str] = None


@dataclass
class Item:
    # Stable local id; used as the join-key when later syncing to GH Project items.
    uid: str
    title: str
    item_type: ItemType

    priority: Optional[str] = None  # e.g. "P0", "P1", "P2"
    status: str = "todo"  # e.g. "todo", "in_progress", "done", "reference"
    parent_epic: Optional[str] = None
    depends_on: List[str] = field(default_factory=list)
    next_action: Optional[str] = None

    # Convenience single-value fields (useful for GH ProjectV2 custom fields).
    artifact_link: Optional[str] = None
    config_path: Optional[str] = None
    run_id: Optional[str] = None

    # Optional structured links extracted from markdown.
    doc_paths: List[str] = field(default_factory=list)
    tool_paths: List[str] = field(default_factory=list)
    artifact_paths: List[str] = field(default_factory=list)
    config_paths: List[str] = field(default_factory=list)
    run_ids: List[str] = field(default_factory=list)

    source: Optional[SourceRef] = None
    referenced_by: List[str] = field(default_factory=list)  # only meaningful for doc items

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # Drop empty/None fields to keep the JSON compact and "schema forward".
        compact: Dict[str, Any] = {}
        for k, v in d.items():
            if v is None:
                continue
            if isinstance(v, list) and not v:
                continue
            compact[k] = v
        return compact
