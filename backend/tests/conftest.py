import os

# FAISS (opt-in store) and PyTorch each bundle libomp; allow both in the one test process (documented unsafe workaround,
# tests only - the runtime default is the NumPy store, which has no second OpenMP runtime).
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_llm, get_session_factory_dep
from app.core.config import Settings, get_settings
from app.database.session import Base, get_db
from app.main import create_app

REVIEWER_HEADERS = {"X-Reviewer-Token": "tok-alice"}


class FakeLLM:
    """Scripted structured LLM: returns queued pydantic objects, one per call. No hidden defaults."""

    def __init__(self) -> None:
        self.queue: list = []
        self.calls: list[str] = []

    def extract(self, schema, instruction, document_text, max_tokens=1024):
        self.calls.append(document_text)
        if not self.queue:
            raise AssertionError("FakeLLM called with an empty response queue")
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def engine():
    from app import models  # noqa: F401

    url = os.environ.get("HAL_TEST_DATABASE_URL")  # e.g. postgresql+psycopg://... to run the suite on Postgres
    if url:
        eng = create_engine(url)
        Base.metadata.drop_all(eng)
    else:
        eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    yield eng
    if url:
        Base.metadata.drop_all(eng)
        eng.dispose()


@pytest.fixture
def db_session(engine):
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield session
    session.close()


@pytest.fixture
def fake_llm():
    return FakeLLM()


@pytest.fixture
def client(engine, db_session, fake_llm, tmp_path):
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(data_dir=tmp_path, database_url="sqlite://", reviewer_tokens="alice:tok-alice")
    app = create_app()
    def shared_session():
        db_session.commit()  # end the test's open transaction so background sessions (other connections) see and can lock rows
        yield db_session
        db_session.commit()  # mirror the real get_db: commit after the request so other sessions can see it

    app.dependency_overrides[get_db] = shared_session
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_llm] = lambda: fake_llm
    app.dependency_overrides[get_session_factory_dep] = lambda: factory
    with TestClient(app) as c:
        yield c
