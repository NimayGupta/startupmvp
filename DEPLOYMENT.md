# StartupMVP Deployment

This repo deploys as a multi-service application:

- `app/discount-optimizer`: Shopify Remix app
- `engine`: FastAPI service
- `workers`: Celery worker
- `postgres`: PostgreSQL
- `redis`: Redis

## Prerequisites

- Docker and Docker Compose
- A Shopify Partner app
- A public HTTPS URL for the app

## 1. Create a production env file

Copy `.env.example` to `.env` and fill in at least:

- `SHOPIFY_API_KEY`
- `SHOPIFY_API_SECRET`
- `SHOPIFY_APP_URL`
- `DATABASE_URL`
- `REDIS_URL`
- `DB_ENCRYPTION_KEY`
- `INTERNAL_API_KEY`

For a single-host Docker deployment, these values work as a starting point:

- `DATABASE_URL=postgres://postgres:postgres@postgres:5432/discount_optimizer`
- `REDIS_URL=redis://redis:6379/0`
- `CELERY_BROKER_URL=redis://redis:6379/1`
- `CELERY_RESULT_BACKEND=redis://redis:6379/2`
- `ENGINE_URL=http://engine:8000`
- `NODE_ENV=production`
- `PYTHON_ENV=production`

## 2. Update Shopify app settings

Set the public app URL and redirect URL in:

- `app/discount-optimizer/shopify.app.toml`

Use your real production domain instead of `https://example.com`.

## 3. Build and start

From the repo root:

```bash
docker compose up --build -d
```

## 4. Verify

Check running services:

```bash
docker compose ps
```

Check logs:

```bash
docker compose logs app
docker compose logs engine
docker compose logs worker
```

## 5. Shopify production deploy

If you want Shopify to sync app configuration and webhooks, run inside `app/discount-optimizer`:

```bash
npm run deploy
```

That requires Shopify CLI authentication and your Partner account.

## Notes

- The app must be reachable over HTTPS for Shopify OAuth and webhooks.
- `ENGINE_URL` should stay internal when the services run on the same Docker network.
- The Python worker depends on Redis and the engine; keep all services up together.
