-- migrate:up

-- ============================================================================
-- APPEND-ONLY EVENT LOG
-- This table is the core long-term moat for RL training.
-- NEVER UPDATE or DELETE rows. A PostgreSQL trigger enforces this invariant.
-- All system decisions, outcomes, and state changes are recorded here.
-- ============================================================================
CREATE TABLE event_log (
  id          BIGSERIAL   NOT NULL,
  merchant_id BIGINT      NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
  -- Valid event_type values:
  --   recommendation_generated | recommendation_approved | recommendation_rejected
  --   recommendation_edited | experiment_started | experiment_assignment
  --   experiment_outcome | experiment_concluded | kill_switch_triggered
  --   auto_approve_applied | auto_approve_reversed | sync_completed
  --   feature_refresh_completed | model_retrained
  event_type  TEXT        NOT NULL,
  -- JSONB payload must contain enough context to reconstruct system state at this moment.
  -- Future RL training depends on this richness.
  payload     JSONB       NOT NULL DEFAULT '{}',
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  -- TimescaleDB (TS103): unique constraints on a hypertable must include the
  -- partition column. Composite PK satisfies this requirement.
  PRIMARY KEY (id, created_at)
);

CREATE INDEX idx_event_log_merchant      ON event_log(merchant_id);
CREATE INDEX idx_event_log_type          ON event_log(event_type);
CREATE INDEX idx_event_log_merchant_type ON event_log(merchant_id, event_type);
CREATE INDEX idx_event_log_created       ON event_log(created_at DESC);
-- GIN index for JSONB payload queries (e.g., filtering by product_id inside payload)
CREATE INDEX idx_event_log_payload       ON event_log USING GIN(payload jsonb_path_ops);

-- Convert to TimescaleDB hypertable partitioned by created_at.
SELECT create_hypertable(
  'event_log',
  'created_at',
  chunk_time_interval => INTERVAL '30 days',
  if_not_exists => TRUE
);

-- ============================================================================
-- IMMUTABILITY TRIGGER
-- Raises an exception on any UPDATE or DELETE attempt.
-- This cannot be bypassed by application code — only a superuser could drop it.
-- ============================================================================
CREATE OR REPLACE FUNCTION prevent_event_log_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION
    'event_log is append-only. UPDATE and DELETE operations are forbidden. '
    'event_type=% id=%', OLD.event_type, OLD.id;
END;
$$;

CREATE TRIGGER event_log_immutable
BEFORE UPDATE OR DELETE ON event_log
FOR EACH ROW EXECUTE FUNCTION prevent_event_log_mutation();

-- migrate:down
DROP TRIGGER IF EXISTS event_log_immutable ON event_log;
DROP FUNCTION IF EXISTS prevent_event_log_mutation();
DROP TABLE IF EXISTS event_log;
