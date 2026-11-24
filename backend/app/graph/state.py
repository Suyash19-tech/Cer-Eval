"""Typed workflow state and reducers."""

import operator
from typing import Annotated, TypedDict

# Sections of a vendor's result. Screening may legitimately change (after human review); downstream sections may not.
MUTABLE_SECTIONS = {"screening"}


class StateConflictError(RuntimeError):
    pass


def merge_vendor_results(old: dict[str, dict] | None, new: dict[str, dict] | None) -> dict[str, dict]:
    """Merge per-vendor results keyed by vendor_id. Parallel branches write different vendors, so keys never collide;
    a downstream section (technical/commercial) can never be silently replaced by a different value."""
    merged = {k: dict(v) for k, v in (old or {}).items()}
    for vendor_id, sections in (new or {}).items():
        cur = merged.setdefault(vendor_id, {})
        for name, value in sections.items():
            if name in cur and cur[name] != value and name not in MUTABLE_SECTIONS:
                raise StateConflictError(f"Conflicting '{name}' result for vendor {vendor_id}")
            cur[name] = value
    return merged


def union_unique(old: list[str] | None, new: list[str] | None) -> list[str]:
    out = list(old or [])
    out.extend(x for x in (new or []) if x not in out)
    return out


class WorkflowState(TypedDict, total=False):
    evaluation_id: str
    as_of: str | None
    vendor_ids: list[str]
    vendor_results: Annotated[dict[str, dict], merge_vendor_results]
    downstream_done: Annotated[list[str], union_unique]
    certification_reports: Annotated[list[str], operator.add]
    node_log: Annotated[list[dict], operator.add]
    errors: Annotated[list[str], operator.add]
    status: str


class VendorBranchState(TypedDict, total=False):
    """Input/state of one vendor branch. Contains ids only: a branch reads its own vendor's data and nothing else."""
    evaluation_id: str
    vendor_id: str
    as_of: str | None
    vendor_results: Annotated[dict[str, dict], merge_vendor_results]
    downstream_done: Annotated[list[str], union_unique]
    node_log: Annotated[list[dict], operator.add]
    errors: Annotated[list[str], operator.add]


class VendorBranchOutput(TypedDict, total=False):
    """Only reducer-backed keys leave a branch, so parallel branches can never collide on plain keys."""
    vendor_results: Annotated[dict[str, dict], merge_vendor_results]
    downstream_done: Annotated[list[str], union_unique]
    node_log: Annotated[list[dict], operator.add]
    errors: Annotated[list[str], operator.add]
