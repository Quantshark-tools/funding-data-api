# funding-data-api

FastAPI service for querying funding-rate data from the Quantshark database.

## Local development

```bash
uv sync --dev
cp .env.example .env
```

Run API:

```bash
uv run uvicorn funding_data_api.main:app --reload --host 0.0.0.0 --port 8000
```

Health check:

```bash
curl http://localhost:8000/health
```

OpenAPI docs:

- `http://localhost:8000/docs`
- `http://localhost:8000/redoc`

## Configuration

- Database: `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_DBNAME`
- Optional DB tuning: `FDA_ENGINE_KWARGS`, `FDA_SESSION_KWARGS`
- CORS: `FDA_CORS_*` variables (see `.env.example`)

## API overview

Base prefix: `/api/v0`

- `/meta/*`: assets, sections, quotes, contract search, contract metadata
- `/funding-data/*`: historical/live points, period sums, differences, funding wall

## Quality checks

```bash
uv run ruff check .
uv run pyright
uv run pytest -q
```

## License

MIT
