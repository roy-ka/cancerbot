import os

os.environ.setdefault("JWT_SECRET", "test-secret-key-not-for-production")
os.environ.setdefault("EMBED_MODEL_NAME", "nomic-embed-text")
os.environ.setdefault("GROQ_MODEL_NAME", "openai/gpt-oss-120b")
os.environ["ENV"] = "test"
os.environ["AXIOM_TOKEN_WRITE"] = ""  # disable Axiom logging during tests
os.environ["AXIOM_TOKEN_READ"] = ""
os.environ["AXIOM_DATASET"] = ""
os.environ.setdefault("ADMIN_DIGEST_EMAILS", "admin-test@example.com")
os.environ["SENDGRID_API_KEY"] = "" # prevent real emails during tests (dormant provider)
os.environ["BREVO_API_KEY"] = ""    # prevent real emails during tests (active provider)
os.environ.setdefault("OPENSEARCH_CA_CERT", "")
os.environ.setdefault("NINJA_EMAIL", "ninja-test@example.com")
os.environ.setdefault("NINJA_PASSWORD", "test-ninja-password")
os.environ.setdefault("REDIS_PASSWORD", "test-redis-password")
os.environ.setdefault("REDIS_URL", "redis://:test-redis-password@localhost:6379/0")
os.environ.setdefault("MAX_USERS", "")  # blank = no registration cap, matching production default

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from src.main import app
from src.deps.db import get_db
from src.deps.auth import get_current_user, get_current_ninja_user, NinjaPrincipal
from src.db.base import Base
from src.db import models
from src.db.repositories.users import create_user
from src.db.repositories.conversations import create_conversation
from src.db.repositories.messeges import add_message
from src.auth.security import SecurityUtils


@pytest.fixture(scope="function")
def engine():
    _engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=_engine)
    yield _engine
    Base.metadata.drop_all(bind=_engine)


@pytest.fixture(scope="function")
def TestingSessionLocal(engine):
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


@pytest.fixture()
def db_session(TestingSessionLocal):
    session = TestingSessionLocal()
    yield session
    session.rollback()
    session.close()


@pytest.fixture()
def test_user(db_session):
    user = create_user(
        db_session,
        first_name="Test", last_name="User",
        email="testuser@example.com",
        password_hash=SecurityUtils.hash_password("TestPass123!"),
    )
    user.email_verified = True
    db_session.commit()
    return user


@pytest.fixture()
def client(TestingSessionLocal, test_user):
    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    def override_get_current_user():
        db = TestingSessionLocal()
        u = db.query(models.User).filter(models.User.email == test_user.email).first()
        db.close()
        return u

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


@pytest.fixture()
def real_token_client(TestingSessionLocal, test_user):
    """Like `client`, but authenticated via a genuine JWT cookie instead of
    overriding get_current_user — needed for anything that decodes the
    token itself rather than depending on get_current_user, e.g.
    get_current_ninja_user (see src/deps/auth.py), which must reject a real
    non-ninja user's token with 403 rather than never seeing it at all."""
    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as c:
        token = SecurityUtils.create_jwt_token({
            "sub": str(test_user.id), "email": test_user.email, "tv": test_user.token_version,
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        })
        c.cookies.set("access_token", token)
        yield c

    app.dependency_overrides.clear()


@pytest.fixture()
def ninja_client(TestingSessionLocal):
    """The ninja account has no users row at all (see src/deps/auth.py) —
    so unlike `client`, this overrides get_current_ninja_user directly with
    a stub principal instead of routing through a DB-backed get_current_user."""
    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_ninja_user] = lambda: NinjaPrincipal()

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


@pytest.fixture()
def anon_client(TestingSessionLocal):
    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


@pytest.fixture()
def test_conversation(db_session, test_user):
    conv = create_conversation(db_session, user_id=test_user.id, title="Test conv")
    add_message(db_session, conversation_id=conv.id, role="user", content="What is cancer?")
    db_session.commit()
    return conv


@pytest.fixture(autouse=True)
def reset_llm_clients():
    """Drop the process-wide cached AsyncGroq client between tests.

    OllamaConnector caches one client for the lifetime of the process so each
    request reuses a pooled connection instead of paying for a new TLS
    handshake. That cache would otherwise leak a mock from whichever test
    patched groq.AsyncGroq first into every test that follows.
    """
    from src.classes.ollama_connector import OllamaConnector
    OllamaConnector._async_groq = None
    yield
    OllamaConnector._async_groq = None


@pytest.fixture(autouse=True)
def mock_enqueue():
    """Prevent tests from enqueueing against a real Redis.

    Without this, every code path that fires a background job (auth.py's
    email sends, ollama_connector.py's fallback alert, conversation_helper's
    URL classification) calls arq's create_pool against REDIS_URL, and
    against no real Redis that isn't a fast failure — it's slow enough
    under pytest's event loop to blow up a whole file's runtime (measured:
    one file went from ~1s to 170s). Mirrors forcing SENDGRID_API_KEY/
    BREVO_API_KEY empty above — no test should depend on live external
    infrastructure by default.

    auth.py and ollama_connector.py both do `from src.queue import
    enqueue` at module level, binding their own local name — patching
    src.queue.enqueue alone wouldn't reach those already-bound references,
    so each needs its own patch target. conversation_helper.py imports it
    fresh inside the function body instead, so patching src.queue.enqueue
    (the source) is what reaches that one.

    Yields the ollama_connector-side mock (the one tests most often want to
    assert against, e.g. the fallback-alert enqueue). The others are
    patched too but not returned here — tests asserting on their enqueue
    calls open their own local `with patch("<module>.enqueue", ...)`, which
    nests inside and overrides this one for that block.
    """
    from unittest.mock import AsyncMock, patch
    with patch("src.routers.auth.enqueue", new=AsyncMock()), \
         patch("src.queue.enqueue", new=AsyncMock()), \
         patch("src.classes.ollama_connector.enqueue", new=AsyncMock()) as ollama_mock:
        yield ollama_mock


@pytest.fixture()
def mock_retrieval():
    return {
        "generation_context": [
            {"id": "src-001", "content_for_embedding": "Cancer cell metabolism involves the Warburg effect."},
            {"id": "src-002", "content_for_embedding": "Tumor suppressor genes regulate cell cycle."},
        ],
        "sources_ids": ["src-001", "src-002"],
    }
