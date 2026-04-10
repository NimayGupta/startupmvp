-- migrate:up
-- Extensions are bootstrapped in infra/postgres/init.sql by the superuser.
-- This migration is a safety net for non-Docker environments (Railway, Supabase, RDS)
-- where timescaledb and pgcrypto may already exist or need to be enabled differently.
-- IF NOT EXISTS makes both statements idempotent.
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- migrate:down
-- Extensions are intentionally not dropped in down migrations.
-- Dropping timescaledb would destroy all hypertable data.
