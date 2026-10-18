# Testing

CancerBot has four test suites. The first three need no running services.

| Suite | Location | Runner | Needs services? |
|---|---|---|---|
| Backend | `tests/` | pytest | No — SQLite in-memory, all external calls mocked |
| NLP service | `nlp_service/test_extraction.py` | pytest | No — but loads the real scispaCy model |
| Frontend | `client/src/**/*.test.ts(x)` | Vitest | No |
| End-to-end | `e2e/tests/` | Playwright | Yes — the full stack |

## Backend

```bash
pip install -r requirements.txt -r requirements-test.txt
pytest                                   # full suite
pytest tests/test_auth.py                # one file
pytest tests/test_auth.py::TestVerifyCode -x  # one class, stop on first failure
```

`tests/conftest.py` sets every required env var to a safe dummy value **before** importing `src`, so module-level config (e.g. `JWT_SECRET`, checked at import in `src/auth/security.py`) is satisfied. When you add a new env var, add a `setdefault` for it there and to the `env:` block in `.github/workflows/test.yml`.

Key fixtures:
- `db_session` — per-test SQLite session (in-memory, `StaticPool` so request handlers share the same database)
- `test_user` — a verified user, `testuser@example.com` (no password; tests sign in by reading the code from the mocked email job)
- `client` — `TestClient` with authentication overridden to `test_user`
- `anon_client` — `TestClient` with no auth override (exercises the real sign-in/JWT path)
- `test_conversation` — a conversation owned by `test_user`

External systems are patched where they're imported: OpenSearch (`dbConnector`), Ollama/Groq/Gemini (`OllamaConnector`), the NLP service (`src.nlp`), PubMed/CrossRef/Wikipedia/ClinicalTrials.gov (`src.routers.conversation_helper`), Brevo (`src.utils.email_brevo.requests.post`), and the job queue (`src.queue.enqueue`).

SQLite quirks to know about:
- `DateTime(timezone=True)` comes back naive — code that compares timestamps normalizes with `.replace(tzinfo=timezone.utc)` when `tzinfo` is missing.
- Postgres-only SQL (e.g. `FOR UPDATE SKIP LOCKED`, the raw-SQL Alembic migrations) is not exercised by this suite.

## NLP service

The extraction logic is tested against the real `en_core_sci_sm` model, so it runs in its own lightweight environment (no torch, no FastAPI):

```bash
cd nlp_service
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-test.txt
pip install --no-deps scispacy==0.5.5   # same as the Dockerfile; skips an unused heavy dependency
pytest
```

## Frontend

```bash
cd client
npm install
npm test           # Vitest
npx tsc -b         # type check
npm run lint       # ESLint
```

## End-to-end (Playwright)

Requires the backend (`ENV` set to anything but `production`, so token-issuing endpoints return tokens the tests can use), the frontend, and their services running.

```bash
cd e2e
npm install
npx playwright install chromium
npm test              # headless
npm run test:headed   # watch it run
```

Configuration comes from the `E2E_*` variables in `.env` (see `example.env`): `E2E_BASE_URL`, `E2E_API_URL` and `E2E_EMAIL`. Sign-in is by emailed code, so **the backend must run with `DEV_EMAIL_SHORTCUTS=true`**: the API then also returns the code and the code screen shows it, which is how the helpers in `e2e/helpers.ts` (`registerUser`, `signInViaApi`, `signInViaUi`, `requestCodeViaUi`) sign in. `global-setup.ts` registers the E2E user on first run (tolerating "already registered" afterwards); the user is deliberately kept and reused across runs. The suite runs on one worker, which matters here: requesting a new code replaces the previous one for that address.

Locally, the registration and sign-in-code rate limits don't apply to requests from the machine itself, so you can run the suite repeatedly. They always apply in production.

## CI

`.github/workflows/test.yml` runs on pushes and pull requests:
- `scan` — builds the backend image and scans it with Trivy
- `test` — backend pytest suite (Python 3.12)
- `nlp-service-test` — NLP extraction tests against the real scispaCy model
- `frontend-test` — ESLint, Vitest, and a type-checked production build

`.github/workflows/e2e.yml` runs the Playwright suite on demand (manual "Run workflow") against an already-running deployment whose URLs you pass as inputs; it needs an `E2E_EMAIL` repository secret, and that deployment must run with `DEV_EMAIL_SHORTCUTS=true` (so never against production).
