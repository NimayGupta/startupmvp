-- This file runs once as superuser when the PostgreSQL container starts for the first time.
-- It bootstraps extensions that require superuser privileges before application migrations run.
-- dbmate migrations will call CREATE EXTENSION IF NOT EXISTS as a safety net,
-- but the actual creation happens here where we have superuser access.

CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
