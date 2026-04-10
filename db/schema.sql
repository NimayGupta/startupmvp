-- =============================================================================
-- CANONICAL REFERENCE SCHEMA
-- This file is documentation only — it is NOT run directly by dbmate.
-- The authoritative schema is defined incrementally in db/migrations/*.sql
-- Run migrations with: dbmate --url "$DATABASE_URL" --migrations-dir ./db/migrations up
-- =============================================================================

-- Extensions (migration 001)
-- timescaledb, pgcrypto

-- MERCHANTS (migration 002)
-- id, shopify_domain (unique), access_token (BYTEA/encrypted), scopes, email,
-- plan_name, installed_at, uninstalled_at, active_engine_version,
-- auto_approve_enabled, safe_zone_max_pct, created_at, updated_at

-- PRODUCTS (migration 003)
-- id, merchant_id (FK), shopify_product_id, title, handle, product_type,
-- vendor, status, tags[], synced_at, created_at, updated_at
-- UNIQUE(merchant_id, shopify_product_id)

-- PRODUCT_VARIANTS (migration 004)
-- id, product_id (FK), shopify_variant_id (unique), title, price,
-- compare_at_price, sku, inventory_quantity, inventory_policy,
-- fulfillment_service, synced_at, created_at, updated_at

-- ORDER_LINE_ITEMS (migration 005) — TimescaleDB hypertable on created_at
-- id, merchant_id (FK), shopify_order_id, shopify_variant_id,
-- quantity, price, discount_amount, experiment_id, experiment_group, created_at

-- EVENT_LOG (migration 006) — TimescaleDB hypertable on created_at
-- APPEND-ONLY. UPDATE/DELETE blocked by trigger.
-- id, merchant_id (FK), event_type (see values below), payload (JSONB), created_at
--
-- event_type values:
--   recommendation_generated, recommendation_approved, recommendation_rejected,
--   recommendation_edited, experiment_started, experiment_assignment,
--   experiment_outcome, experiment_concluded, kill_switch_triggered,
--   auto_approve_applied, auto_approve_reversed, sync_completed,
--   feature_refresh_completed, model_retrained

-- EXPERIMENTS (migration 007)
-- id, merchant_id (FK), product_id (FK), status, control_discount_pct,
-- treatment_discount_pct, shopify_discount_id, started_at, concluded_at,
-- conclusion_type, latest_stats (JSONB), recommendation_id, created_at
-- status: pending_approval | active | concluded | killed
-- conclusion_type: significance_reached | max_duration | kill_switch | manual

-- EXPERIMENT_ASSIGNMENTS (migration 008)
-- id, experiment_id (FK), session_hash, group_assignment (control|treatment),
-- assigned_at
-- UNIQUE(experiment_id, session_hash)

-- RECOMMENDATIONS (migration 009)
-- id, merchant_id (FK), product_id (FK), recommended_discount_pct,
-- rationale, llm_explanation, confidence_score, model_version,
-- feature_snapshot (JSONB), status, merchant_edit_pct, created_at, reviewed_at
-- status: pending | approved | rejected | edited_and_approved

-- PRODUCT_TRUST_SCORES (migration 010)
-- id, product_id (FK), merchant_id (FK), trust_score (0.0–1.0),
-- tests_completed, tests_positive, updated_at
-- UNIQUE(product_id, merchant_id)

-- BANDIT_PARAMETERS (migration 011)
-- id, merchant_id (FK), context_bucket, action (int percent: 0,5,10,15,20),
-- alpha, beta, observations, updated_at
-- UNIQUE(merchant_id, context_bucket, action)

-- SUBSCRIPTIONS (migration 012)
-- id, merchant_id (FK, unique), stripe_customer_id, stripe_subscription_id,
-- plan (free|growth|pro), status, current_period_start, current_period_end,
-- created_at, updated_at
