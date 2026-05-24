# Testing Guide — CancerBot

## Quick Start

```bash
# Install test dependencies
pip install -r requirements.txt
pip install pytest pytest-asyncio freezegun

# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=src --cov-report=term-missing -v

# Run specific test file
pytest tests/test_auth.py -v

# Run specific test
pytest tests/test_auth.py::TestLogin::test_login_success_returns_token_and_sets_cookie -v
```

## Test Structure

```
tests/
├── conftest.py                  # Fixtures: SQLite DB, client, mocks
├── test_security.py             # JWT, password hashing (pure unit)
├── test_router_intent.py        # classify_intent (pure unit)
├── test_email.py                # SendGrid mocking
├── test_repositories.py         # Database layer (14 tests)
├── test_auth.py                 # Auth endpoints (13 tests)
└── test_conversations.py        # Chat endpoints + WebSocket (12 tests)
```

**Total: ~60 test functions covering critical paths**

## What's Tested

### Auth (test_auth.py)
- ✅ Register (success, duplicate email, validation)
- ✅ Login (success, wrong password, JWT cookie)
- ✅ Logout (cookie cleared)
- ✅ Forgot password (always 200, sends email)
- ✅ Reset password (success, wrong code, expiry)
- ✅ Auth check (authenticated vs unauthenticated)

### Conversations (test_conversations.py)
- ✅ New conversation (creates messages, metadata)
- ✅ Add message (existing conversation, not found, wrong user)
- ✅ List conversations (pagination, excludes deleted)
- ✅ Delete conversation (soft delete)
- ✅ Get messages (pagination, ordering)
- ✅ Fallback path (insufficient evidence triggers search)
- ✅ WebSocket (stages emitted, final message)

### Repositories (test_repositories.py)
- ✅ User: create, get_by_email, get_by_id
- ✅ Conversation: create, soft_delete, list
- ✅ Message: add, get_recent, pagination
- ✅ Password reset: create code, verify (with expiry & attempt limits)

### Security (test_security.py)
- ✅ Password hashing (pbkdf2_sha256 round-trip)
- ✅ JWT creation (returns valid token)
- ✅ JWT decode (success, expired, tampered, wrong secret)

### Email (test_email.py)
- ✅ SendGrid no-op when API key not set
- ✅ SendGrid send called with correct params
- ✅ Error propagation

### Routing (test_router_intent.py)
- ✅ classify_intent: concept vs intervention queries
- ✅ Tie-breaking (intervention wins)
- ✅ Case insensitivity

## Key Features

### No External Services Required
- ✅ PostgreSQL — mocked with SQLite in-memory
- ✅ OpenSearch — mocked (dbConnector calls)
- ✅ Ollama — mocked (generate_text returns string)
- ✅ SendGrid — mocked (sg.send() called)
- ✅ NLP service — mocked (external HTTP calls)
- ✅ PubMed/CrossRef/Wikipedia — mocked (conversation_helper tests)

### Fixtures (conftest.py)
- **engine** — SQLite in-memory with StaticPool (session-scoped)
- **db_session** — per-test DB session with rollback (function-scoped)
- **test_user** — pre-created user (function-scoped)
- **client** — TestClient with auth overridden (function-scoped)
- **anon_client** — TestClient without auth override (function-scoped)
- **test_conversation** — pre-created conversation + message (function-scoped)
- **mock_retrieval** — fake context items for mocking (function-scoped)

### Mocking Targets
Patches applied at import sites:

| Target | Patch | Type |
|---|---|---|
| run_retrieval | `src.routers.conversations.run_retrieval` | MagicMock |
| Ollama generate | `src.routers.conversations.OllamaConnector.generate_text` | MagicMock |
| OpenSearch fetch | `src.db.repositories.messeges.dbConnector.get_sources_by_id` | MagicMock |
| SendGrid client | `src.utils.email.SendGridAPIClient` | MagicMock |
| Email send | `src.routers.auth.send_password_reset_email` | AsyncMock |
| Code verify | `src.routers.auth.verify_and_consume_code` | MagicMock |
| datetime | `src.db.repositories.password_resets.datetime` | MagicMock |
| search_and_embed | `src.routers.conversations.search_and_embed` | AsyncMock |

## Known Issues & Workarounds

### SQLite UUID Column Filtering
SQLite returns UUID columns as `bytes`, not `uuid.UUID` objects. String filtering fails.
- **Fix**: conftest.py overrides `get_current_user` to fetch the test user from DB by email, bypassing the UUID filter.
- **Impact**: HTTP tests in `test_auth.py` and `test_conversations.py` use the override; repository tests pass UUID objects directly.

### SQLite Datetime Timezone Stripping
SQLite `DateTime(timezone=True)` columns are stored as naive datetimes.
- **Fix**: `test_repositories.py` password reset tests patch `datetime` to return naive datetimes.
- **Impact**: Only affects password reset tests; other datetime comparisons work fine.

### StaticPool Required
SQLite `:memory:` creates a new database per connection. Without `StaticPool`, `create_all()` is invisible to request handlers.
- **Fix**: conftest.py uses `StaticPool` to force a single shared in-process connection.
- **Impact**: All SQLite operations now share the same database.

## CI/CD

GitHub Actions workflow: `.github/workflows/test.yml`

**Runs on:**
- Push to `main`, `master`, `develop`
- Pull requests to `main`, `master`

**Steps:**
1. Set up Python 3.13
2. Install production dependencies (`requirements.txt`)
3. Install test dependencies (`pytest`, `pytest-asyncio`, `freezegun`)
4. Run tests (`pytest --tb=short -v`)
5. Run with coverage (`pytest --cov=src --cov-report=term-missing`)

**Environment variables:**
- `JWT_SECRET=ci-test-jwt-secret-not-for-production`
- `EMBED_MODEL_NAME=nomic-embed-text`
- `ENV=test`
- `SENDGRID_API_KEY=` (empty)

No Docker services needed. No live external services.

## Running Tests Locally

### Setup
```bash
cd /path/to/cancerbot

# Create venv (optional but recommended)
python3 -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install dependencies
pip install -r requirements.txt
pip install pytest pytest-asyncio freezegun
```

### Run
```bash
# All tests
pytest tests/ -v

# Single file
pytest tests/test_auth.py -v

# Single test
pytest tests/test_auth.py::TestLogin::test_login_success_returns_token_and_sets_cookie -v

# With coverage
pytest tests/ --cov=src --cov-report=html
open htmlcov/index.html  # View HTML coverage report
```

### Debugging
```bash
# Stop on first failure
pytest tests/ -x -v

# Drop into pdb on failure
pytest tests/ --pdb

# Verbose output
pytest tests/ -vv

# Show print() statements
pytest tests/ -s
```

## Adding More Tests

When adding new features:

1. **Identify what to test**: critical paths, error cases, edge cases
2. **Choose test type**:
   - **Unit** (no DB, no HTTP): pure functions, utilities → `test_security.py`, `test_router_intent.py`
   - **Repository** (DB, no HTTP): database operations → `test_repositories.py`
   - **Integration** (HTTP, full stack): endpoints with mocked externals → `test_auth.py`, `test_conversations.py`
3. **Add test function** to appropriate file
4. **Use fixtures**: `db_session`, `client`, `test_user`, `test_conversation`
5. **Mock externals**: Ollama, OpenSearch, SendGrid via `@patch` or `with patch(...)`
6. **Run**: `pytest tests/test_file.py::TestClass::test_function -v`

## Performance

- **test_security.py**: <100ms (pure unit tests)
- **test_router_intent.py**: <100ms (pure unit tests)
- **test_email.py**: ~100ms (mocked SendGrid)
- **test_repositories.py**: ~500ms (SQLite transactions)
- **test_auth.py**: ~1s (HTTP + mocks)
- **test_conversations.py**: ~2s (HTTP + complex mocks + WebSocket)

**Total**: ~5-10 seconds for full test suite.

## Troubleshooting

### `RuntimeError: JWT_SECRET not set`
- **Cause**: conftest.py didn't set `JWT_SECRET` before importing `src.main`
- **Fix**: Check conftest.py has `os.environ.setdefault("JWT_SECRET", ...)` at the top

### `KeyError: 'nomic-embed-text'`
- **Cause**: `dbConnector` class-body code executed before `EMBED_MODEL_NAME` was set
- **Fix**: Check conftest.py sets `EMBED_MODEL_NAME` before importing `src.*`

### `TypeError: 'str' object has no attribute 'hex'`
- **Cause**: Passing string to UUID column filter in SQLite
- **Fix**: Pass `uuid.UUID` object or use conftest's `get_current_user` override

### `TypeError: can't compare offset-naive and offset-aware datetimes`
- **Cause**: SQLite returns naive datetime, code expects timezone-aware
- **Fix**: Patch `datetime` in password reset tests to return naive datetime

### `pytest: command not found`
- **Cause**: pytest not installed
- **Fix**: `pip install pytest pytest-asyncio freezegun`

### `FAILED - [Errno 48] Address already in use`
- **Cause**: TestClient port conflict (rare)
- **Fix**: Run tests one file at a time, or restart terminal
