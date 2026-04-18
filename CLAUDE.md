# Discount Optimizer — CLAUDE.md

Codebase instructions for Claude Code. Read this before touching any file.

---

## Project Overview

A Shopify embedded app that runs Bayesian A/B discount experiments automatically.
Three services communicate over an internal network:

| Service | Language | Entry point | Port |
|---------|----------|------------|------|
| `engine/` | Python / FastAPI | `engine/main.py` | 8000 |
| `workers/` | Python / Celery | `workers/celery_app.py` | — |
| `app/discount-optimizer/` | TypeScript / Remix | `app/routes/` | 3000 |

Infrastructure: PostgreSQL 15, Redis (db 0 = features, db 1 = Celery broker, db 2 = Celery results), AWS ECS Fargate.

---

## Repository Layout

```
engine/                 FastAPI decision engine
  api/                  Route handlers (one file per domain)
  bandit/               Thompson sampling (thompson.py)
  experiments/          Bayesian model + CRUD (bayesian.py, service.py)
  features/             Feature vector computation
  recommendations/      Rules engine + LLM explanations (service.py, explain.py)
  rules/                Discount rule logic (v1.py)
  stats/                Bayesian stats helpers
  trust/                Trust score computation (scorer.py)
  db/session.py         Async SQLAlchemy session factory
  config.py             Pydantic settings (reads .env)
  tests/                pytest unit tests

workers/
  celery_app.py         Celery app + beat schedule
  tasks/
    sync.py             Shopify catalog → DB
    webhooks.py         Shopify webhook handlers
    feature_refresh.py  Recompute Redis feature vectors
    experiment_monitor.py  Bayesian stopping rule checks
    model_retrain.py    Weekly bandit retraining
  db.py                 Sync psycopg2 connection helper

app/discount-optimizer/
  app/
    routes/             Remix file-based routes
    lib/                Server-only helpers (*.server.ts)
  extensions/
    ab-checkout/        Shopify UI extension (checkout banner)
  prisma/               Shopify session storage schema only

infra/
  ecs/                  ECS task definition JSON files
  terraform/            Terraform skeleton (VPC, RDS, Redis, ALB, ECS)
  loadtest/             Locust load test script
  postgres/             Init SQL / migrations

scripts/
  seed_local.py         Seeds local dev DB + warms Redis (no Shopify needed)

docs/
  merchant-onboarding.md
  app-store-listing.md
```

---

## Development Setup

### Prerequisites
- Docker Desktop
- Node.js ≥ 20.19
- Python 3.11+
- Shopify CLI (`npm install -g @shopify/cli`)

### Start all services
```bash
docker compose up -d          # postgres, redis
cd engine && uvicorn engine.main:app --reload --port 8000
cd workers && celery -A workers.celery_app worker --beat --loglevel=info
cd app/discount-optimizer && npm run dev   # shopify app dev
```

### Seed local dev data (no real Shopify connection)
```bash
python scripts/seed_local.py
# Inserts product_variants + 99 synthetic orders for merchant_id=2, product_id=1
# Then calls GET /features/2 to warm Redis
```

### Environment variables
Copy `.env.example` to `.env` in the repo root. Required for local dev:
```
DATABASE_URL=postgres://postgres:postgres@localhost:5432/discount_optimizer
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2
INTERNAL_API_KEY=dev-internal-key
ANTHROPIC_API_KEY=sk-ant-...
```
The Remix app also needs `SHOPIFY_API_KEY` / `SHOPIFY_API_SECRET` for OAuth.

---

## Running Tests

```bash
# Engine unit tests
cd engine && python -m pytest tests/ -v

# Worker unit tests
cd workers && python -m pytest tests/ -v

# Load test (against running engine)
locust -f infra/loadtest/locustfile.py --host=http://localhost:8000 \
       --users=20 --spawn-rate=2 --run-time=5m --headless
```

All tests are pure unit tests — no live DB or Redis required except integration tests that explicitly connect.

---

## Key Patterns

### Engine: async DB access
All service functions receive an `AsyncSession` injected via FastAPI dependency `DbSession` (defined in `engine/api/deps.py`). Use `text()` for raw SQL — never ORM models (the schema predates SQLAlchemy ORM mapping).

```python
from sqlalchemy import text
result = await db.execute(text("SELECT ... WHERE id = :id"), {"id": rec_id})
row = result.fetchone()
```

### Engine: named parameter type casting
asyncpg cannot infer types when named params are added/subtracted. Use `CAST(:param AS numeric)` — never `:param::numeric` (the `::` after a named param is a syntax error in asyncpg).

### Engine: auth
All routes require `dependencies=[RequireInternalAuth]` (Bearer token check against `INTERNAL_API_KEY`). Never expose engine routes directly to the browser.

### Engine: event log
Every state change appends a row to `event_log`. The `_append_event(db, merchant_id, event_type, payload)` helper lives in `engine/recommendations/service.py` — copy it verbatim to new service files that need it. The bandit retrain reads `event_type = 'experiment_concluded'` from `event_log` (not the experiments table) to compute hard rewards.

### Workers: Celery task pattern
Follow `workers/tasks/feature_refresh.py` exactly:
- `bind=True`, `max_retries=3`, explicit `name=`
- Sync DB via `workers/db.py:get_sync_db_connection()`
- HTTP calls to engine via `httpx`
- Raise `RuntimeError` on partial failure → triggers Celery retry

### Remix: server-only API calls
All calls to the engine go through `app/lib/*.server.ts` files. The `.server.ts` suffix ensures Remix never bundles these in client code. `INTERNAL_API_KEY` must never appear in client-side JS.

### Remix: per-row optimistic UI
Use `useFetcher` (not `useSubmit`) for approve/reject/kill actions on individual rows so the full page doesn't reload.

---

## Billing Tiers

Enforced server-side in `engine/api/billing.py`. Raises HTTP 402 when a merchant exceeds their plan.

| Tier | Products | Experiments | Bandit | Auto-Approve |
|------|----------|-------------|--------|--------------|
| free | 1 | 1 | no | no |
| growth | 20 | 5 | yes | no |
| pro | unlimited | unlimited | yes | yes |

Stripe webhooks update the `merchant_billing` table via `app/routes/webhooks.stripe.tsx`.

---

## Deployment

### CI/CD
Push to `main` → GitHub Actions (`deploy.yml`) runs tests, builds 3 Docker images, pushes to ECR, deploys to ECS production with zero-downtime task definition rolling update.

Push to `staging` → force-new-deployment to staging cluster + smoke test.

### Secrets
All secrets live in AWS Secrets Manager under `discount-optimizer/<KEY>`. ECS task definitions reference them by ARN — never hardcode secrets in task defs or source.

### ECS task definitions
JSON files in `infra/ecs/`. Update `ACCOUNT_ID` placeholders before first deploy. The CI workflow renders new image tags into these files via `amazon-ecs-render-task-definition`.

---

## Gotchas

- **pytest name collision**: Functions named `tests_*` (plural) in source files get collected as test functions. If you import such a function into a test file, alias it: `from module import tests_foo as _tests_foo`.
- **asyncpg `::` cast syntax**: See "named parameter type casting" above — this has caused production bugs before.
- **Shopify extension versions**: `@shopify/ui-extensions` and `@shopify/ui-extensions-react` must be the same version (`2025.7.3`). The Rust function extension (`discount-ab-test`) is disabled (`shopify.extension.toml.disabled`) — requires Cargo to build.
- **npm workspace hoisting**: The `extensions/*` workspace causes silent hoisting failures. Install extension packages from inside the extension directory with `--no-workspaces --legacy-peer-deps`.
- **Feature vectors**: `GET /features/{merchant_id}` computes and caches feature vectors in Redis. Recommendations fail with "No features available" if Redis is cold — run `scripts/seed_local.py` or trigger a feature refresh first.
- **Bandit retrain data**: Retrain reads `experiment_concluded` events from `event_log`, not the `experiments` table. Manually updated experiment rows won't appear in retrain unless you also insert the event.
