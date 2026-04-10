-- migrate:up
CREATE TABLE experiment_assignments (
  id              BIGSERIAL   PRIMARY KEY,
  experiment_id   BIGINT      NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
  -- Hashed session or customer identifier — never the raw customer ID.
  -- Hash is deterministic: murmurhash3(session_id + experiment_id) for consistent re-assignment.
  session_hash    TEXT        NOT NULL,
  -- group_assignment: control | treatment
  group_assignment TEXT       NOT NULL,
  assigned_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  -- Prevent duplicate assignment for the same session in the same experiment
  UNIQUE(experiment_id, session_hash)
);

CREATE INDEX idx_assignments_experiment  ON experiment_assignments(experiment_id);
CREATE INDEX idx_assignments_session     ON experiment_assignments(session_hash);

-- migrate:down
DROP TABLE IF EXISTS experiment_assignments;
