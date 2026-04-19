# Discount Optimizer

A Shopify embedded app that uses Bayesian A/B testing and Thompson Sampling to find the optimal discount percentage for each product — automatically, without guesswork.

The merchant approves an AI-generated recommendation, an experiment starts, and the system concludes it when statistical significance is reached. Over time a trust score is built; on the Pro plan, the whole loop runs without manual approval.

---

## How It Works

1. **Feature pipeline** — Celery syncs your Shopify catalog and computes feature vectors (price tier, inventory tier, historical conversion rate) into Redis every 6 hours.
2. **Recommendation engine** — FastAPI generates a discount suggestion per product using either a rules engine (v1) or a Thompson Sampling contextual bandit, with a plain-English LLM explanation.
3. **A/B experiment** — Approving a recommendation creates a Shopify automatic discount and starts a Bayesian experiment. Every 6 hours the Gamma-Poisson model checks whether the treatment is outperforming control at ≥ 95% probability.
4. **Trust score** — Each concluded experiment updates a per-merchant trust score. Once it crosses 0.70 and the merchant is on the Pro plan, Auto-Approve mode runs the loop fully autonomously.

---

## Architecture

```
┌─────────────────────┐     GraphQL/REST      ┌─────────────┐
│  Remix app (Node)   │ ◄──────────────────── │   Shopify   │
│  app/ · port 3000   │                        └─────────────┘
└────────┬────────────┘
         │ HTTP (internal)
         ▼
┌─────────────────────┐     asyncpg / Redis
│  FastAPI engine     │ ◄──────────────────── PostgreSQL 15
│  engine/ · port 8000│                        Redis 7
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Celery workers     │  beat schedule: 6h feature refresh,
│  workers/           │  6h experiment monitor, weekly retrain
└─────────────────────┘
```

### Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Remix v2, Shopify Polaris, Shopify App Bridge |
| Backend API | FastAPI 0.111, Python 3.11, asyncpg, SQLAlchemy async |
| Task queue | Celery 5.4 + Redis broker |
| Database | PostgreSQL 15 + TimescaleDB |
| Cache / feature store | Redis 7 |
| ML / stats | NumPy, Gamma-Poisson Bayesian model, Thompson Sampling bandit |
| LLM explanations | Anthropic Claude (via `anthropic` SDK) |
| Billing | Stripe (Checkout + Customer Portal + webhooks) |
| Observability | Sentry (Remix + FastAPI) |
| Infrastructure | AWS ECS Fargate, RDS Multi-AZ, ElastiCache, ALB, ECR |
| CI/CD | GitHub Actions → ECR → ECS rolling deploy |

---

## Project Structure

```
engine/          FastAPI decision engine (recommendations, bandit, experiments, trust)
workers/         Celery task workers (sync, feature refresh, experiment monitor, retrain)
app/
  discount-optimizer/   Remix embedded app (Shopify OAuth, dashboard, billing)
    extensions/
      ab-checkout/      Shopify UI extension — checkout experiment banner
infra/
  ecs/           ECS Fargate task definition JSON files
  terraform/     Terraform skeleton (VPC, RDS, ElastiCache, ALB, ECS)
  loadtest/      Locust load test (20 concurrent merchants, p95 < 500ms)
  postgres/      DB init SQL / migrations
scripts/
  seed_local.py  Seeds local dev data without a real Shopify connection
docs/
  merchant-onboarding.md
  app-store-listing.md
.github/
  workflows/
    ci.yml       Lint + typecheck + pytest on every push
    deploy.yml   Build → ECR → ECS on push to main/staging
```

---

## Local Development

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- Node.js ≥ 20.19
- Python 3.11+
- [Shopify CLI](https://shopify.dev/docs/api/shopify-cli) — `npm install -g @shopify/cli`

### 1. Environment variables

```bash
cp .env.example .env
```

Minimum required values:

```env
DATABASE_URL=postgres://postgres:postgres@localhost:5432/discount_optimizer
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://redis:6379/2
INTERNAL_API_KEY=dev-internal-key
ANTHROPIC_API_KEY=sk-ant-...          # for LLM explanations
SHOPIFY_API_KEY=...                   # from Shopify Partners dashboard
SHOPIFY_API_SECRET=...
```

### 2. Start backing services

```bash
docker compose up -d postgres redis
```

### 3. Start the engine

```bash
cd engine
pip install -r requirements.txt
uvicorn engine.main:app --reload --port 8000
```

Interactive API docs: [http://localhost:8000/docs](http://localhost:8000/docs)

### 4. Start the worker

```bash
cd workers
pip install -r requirements.txt
celery -A workers.celery_app worker --beat --loglevel=info
```

### 5. Start the Remix app

```bash
cd app/discount-optimizer
npm install
npm run dev          # opens Shopify CLI tunnel + OAuth flow
```

### 6. Seed local data (skip Shopify OAuth)

If you just want to test the engine without a real Shopify store:

```bash
python scripts/seed_local.py
# Creates merchant_id=2, product_id=1 with 99 synthetic orders
# Warms Redis feature vectors automatically
```

### 7. Run everything with Docker Compose

```bash
docker compose up --build
```

All four services (postgres, redis, engine, worker, app) start together. The Remix app at this point won't complete the Shopify OAuth flow without valid API credentials.

---

## Running Tests

```bash
# Python — engine + workers
python -m pytest engine/tests/ workers/tests/ -v

# With coverage
python -m pytest engine/tests/ --cov=engine --cov-report=term-missing

# Remix — lint + type-check
cd app/discount-optimizer
npm run lint
npm run typecheck

# Load test (engine must be running)
pip install locust
locust -f infra/loadtest/locustfile.py \
  --host=http://localhost:8000 \
  --users=20 --spawn-rate=2 --run-time=5m --headless
```

Pass criteria for the load test: p95 latency < 500ms, zero 5xx errors.

---

## Key API Endpoints

All engine routes require `Authorization: Bearer <INTERNAL_API_KEY>`.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Service health check |
| `GET` | `/features/{merchant_id}` | Compute + return feature vectors |
| `POST` | `/recommendations/generate` | Generate discount recommendation |
| `POST` | `/recommendations/{id}/approve` | Approve recommendation |
| `POST` | `/recommendations/{id}/reject` | Reject recommendation |
| `POST` | `/recommendations/{id}/edit-approve` | Approve with custom discount % |
| `POST` | `/experiments` | Create A/B experiment |
| `GET` | `/experiments/{id}` | Get experiment + latest stats |
| `POST` | `/experiments/{id}/kill` | Stop experiment early |
| `POST` | `/experiments/monitor/{merchant_id}` | Run Bayesian stopping check |
| `GET` | `/trust/{merchant_id}` | Get trust score |
| `GET` | `/bandit/{merchant_id}/params` | Inspect bandit posteriors |
| `POST` | `/bandit/retrain/{merchant_id}` | Retrain bandit from event log |

---

## Billing Plans

Enforced server-side in `engine/api/billing.py`. HTTP 402 is returned when a limit is exceeded.

| | Free | Growth ($29/mo) | Pro ($99/mo) |
|---|---|---|---|
| Products | 1 | 20 | Unlimited |
| Concurrent experiments | 1 | 5 | Unlimited |
| Bandit optimization | — | ✓ | ✓ |
| Auto-Approve mode | — | — | ✓ |

Stripe webhooks are handled at `/webhooks/stripe` in the Remix app.

---

## Deployment

Push to `main` triggers the full production deploy pipeline:

1. CI runs lint, typecheck, and pytest
2. Three Docker images are built and pushed to ECR (engine, worker, remix)
3. ECS task definitions are rendered with the new image tags
4. Rolling deploy to `discount-optimizer-production` ECS cluster
5. Smoke test hits `/health` on the live URL

Push to `staging` does a force-new-deployment to `discount-optimizer-staging` instead.

See [DEPLOYMENT.md](DEPLOYMENT.md) for AWS setup instructions and Terraform usage.

---

## Documentation

- [docs/merchant-onboarding.md](docs/merchant-onboarding.md) — end-user guide
- [docs/app-store-listing.md](docs/app-store-listing.md) — Shopify App Store copy
- [CLAUDE.md](CLAUDE.md) — codebase guide for AI-assisted development
