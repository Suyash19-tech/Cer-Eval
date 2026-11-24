from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.agents.tender_extractor import StructuredLLM
from app.core.config import Settings, get_settings
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.database.session import get_session_factory
from app.document_processing.service import DocumentIntake
from app.rag.service import RagService


def require_reviewer(
    x_reviewer_token: str | None = Header(default=None), settings: Settings = Depends(get_settings)
) -> str:
    """Authenticate a human reviewer by token; returns the reviewer id. No tokens configured => nobody."""
    if not x_reviewer_token:
        raise UnauthorizedError("Missing X-Reviewer-Token header")
    reviewer = settings.reviewer_token_map.get(x_reviewer_token)
    if reviewer is None:
        raise ForbiddenError("Not an authorised reviewer")
    return reviewer


@lru_cache
def _granite() -> StructuredLLM:
    from app.llm.granite import GraniteLLM

    return GraniteLLM()


def get_llm() -> StructuredLLM:
    """Overridable in tests. The real model loads lazily on first use."""
    return _granite()


def get_session_factory_dep() -> Callable[[], Session]:
    return get_session_factory()


@lru_cache
def _rag(root: str) -> "RagService":
    from app.llm.embeddings import GraniteEmbedder
    from app.rag.service import RagService

    return RagService(GraniteEmbedder(), root=Path(root))


def get_rag(settings: Settings = Depends(get_settings)) -> "RagService":
    """Overridable in tests. Loads the local Granite embedder lazily on first use."""
    return _rag(str(settings.data_dir / "rag"))


def get_intake(settings: Settings = Depends(get_settings)) -> "DocumentIntake":
    from app.document_processing.ocr import get_ocr_engine
    from app.document_processing.service import DocumentIntake

    return DocumentIntake(settings, get_ocr_engine)


@lru_cache
def _checkpointer(path: str):  # noqa: ANN202
    import sqlite3

    from langgraph.checkpoint.sqlite import SqliteSaver

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return SqliteSaver(sqlite3.connect(path, check_same_thread=False))


def get_workflow_graph(
    settings: Settings = Depends(get_settings), llm: StructuredLLM = Depends(get_llm),
    rag: "RagService" = Depends(get_rag),
):  # noqa: ANN201
    """Overridable in tests. Checkpoints persist in SQLite so an interrupted workflow survives a restart."""
    from app.graph.workflow import WorkflowDeps, build_workflow, with_real_evaluators

    deps = with_real_evaluators(
        WorkflowDeps(session_factory=get_session_factory(), llm=llm, rag=rag, reports_dir=settings.reports_dir))
    return build_workflow(deps, _checkpointer(str(settings.data_dir / "checkpoints.sqlite")))
