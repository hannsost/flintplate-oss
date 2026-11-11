# FlintPlate configuration

Start with [the root template](../.env.example). Values are placeholders and must be replaced.
Run `python3 scripts/setup-local.py` to generate `.env.flintplate`; add optional values from the template without overwriting generated secrets. Pass `--env-file .env.flintplate -f compose.yaml` to Compose. The frontend runs separately and uses `FLINTPLATE_API_URL` (default `http://127.0.0.1:8012`) for its `/api` proxy.

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | PostgreSQL asyncpg URL; use an isolated test database for tests |
| `REDIS_URL` | Redis URL including configured password |
| `SECRET_KEY` | Random signing key; replace the example before starting |
| `APP_ENV`, `ALLOWED_ORIGINS`, `FRONTEND_URL` | Environment and permitted browser origins |
| `LEGAL_*` | Operator details and review status; blank fields keep legal pages in draft |
| `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL` | Optional OpenAI-compatible provider |
| `AI_MOCK_MODE`, `AI_MAX_TOKENS`, `AI_REQUESTS_PER_MIN` | Offline fallback, token budget and process-local throttle |
| `FLINTPLATE_BASE_URL`, `FLINTPLATE_TOKEN`, `FLINTPLATE_READ_ONLY` | MCP client environment; read-only defaults to true |


`LEGAL_COMPANY_NAME`, `LEGAL_LEGAL_FORM`, `LEGAL_REPRESENTED_BY`, `LEGAL_STREET`,
`LEGAL_POSTAL_CODE`, `LEGAL_CITY`, `LEGAL_CONTACT_EMAIL`, `LEGAL_PRIVACY_EMAIL`,
`LEGAL_REGISTER`, `LEGAL_REGISTER_NUMBER`, `LEGAL_VAT_ID` and `LEGAL_REVIEWED` describe
the operator. FlintPlate additionally uses `LEGAL_CONTROLLER_ADDRESS` for the privacy notice.
Only fields consumed by the product's `frontend/lib/legal-constants.ts` are rendered.
Provide verified deployment values outside source control; keep `LEGAL_REVIEWED=false`
until the pages are complete. The project operator is neurofunken; no personal address is bundled.
Empty Helm `webLegal` values remain intentional.

`HIREOS_API_PORT` and `HIREOS_FRONTEND_PORT` (inherited Compose defaults 8001/3001),
`hireos_*` container names, Python package and database names are legacy identifiers.
They are not product names. The dedicated FlintPlate runtime instead binds API 8012 and uses frontend 3012, with FLINTPLATE_DB_PASSWORD, FLINTPLATE_RUNTIME_DB_PASSWORD and FLINTPLATE_REDIS_PASSWORD.
Any `hireos_secret` / `redis_secret` Compose defaults are development-only and must be
changed for real deployment. Use long independent signing/import keys, explicit database/Redis
URLs, HTTPS frontend origin and a JSON CORS allowlist for production. Do not reuse demo databases.

Optional integrations: `BA_CLIENT_ID` and `BA_CLIENT_SECRET` are environment-only (no bundled BA
credentials). SMTP, object storage, billing and external accounts require separate setup.
Leave unused integrations unset. AI settings: [AI providers](AI-PROVIDERS.md).
QuickWork, `@quickwork.de`, Max Müller, Lisa Brandt, LogiPort, NordBeck and CityGlanz in
inherited seeds/tests are fictional demo records, not customer data.

## Local checks

```sh
cd mcp && npm test
# From repository root:
cd backend && python3 -m unittest discover -s unit_tests -v
# With backend development dependencies installed:
black --check --line-length 100 .
ruff check .
mypy app
```

Full backend tests require Python 3.12, `pip install -c constraints-py312.txt -e ".[dev]"`,
the CPU Torch runtime as specified in CI, PostgreSQL 16 with pgvector, Redis, and PDF/OCR
system packages as listed in CI. Use only a disposable test database.
Set DATABASE_URL to postgresql+asyncpg://flintplate:<test-password>@localhost:5432/flintplate_test. The product runner refuses other database names and selects tests/test_flintplate.py by default. Supply additional test paths explicitly for the inherited suite.
Set `REDIS_URL`, a test-only `SECRET_KEY`, `APP_ENV=test`, `AI_MOCK_MODE=true` and `SMTP_HOST=`.
Then run `alembic upgrade head` and `python -m scripts.test_flintplate` from `backend/`.
For frontend checks: `cd frontend && npm ci && npm run lint && npm run build && npm run typecheck`.
GitHub and GitLab workflows define service setup; no external AI credentials are needed.
