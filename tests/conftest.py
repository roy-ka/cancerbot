import os

os.environ.setdefault("JWT_SECRET", "test-secret-key-not-for-production")
os.environ.setdefault("EMBED_MODEL_NAME", "nomic-embed-text")
os.environ.setdefault("ENV", "test")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from src.main import app
from src.deps.db import get_db
from src.deps.auth import get_current_user
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
        name="Test User",
        email="testuser@example.com",
        password_hash=SecurityUtils.hash_password("TestPass123!"),
    )
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


@pytest.fixture()
def mock_retrieval():
    return {
        "generation_context": [
            {"id": "src-001", "content_for_embedding": "Cancer cell metabolism involves the Warburg effect."},
            {"id": "src-002", "content_for_embedding": "Tumor suppressor genes regulate cell cycle."},
        ],
        "sources_ids": ["src-001", "src-002"],
    }
