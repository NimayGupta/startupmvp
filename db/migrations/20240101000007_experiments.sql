-- migrate:up
CREATE TABLE experiments (
  id                      BIGSERIAL      PRIMARY KEY,
  merchant_id             BIGINT         NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
  product_id              BIGINT         NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  -- status: pending_approval | active | concluded | killed
  status                  TEXT           NOT NULL DEFAULT 'pending_approval',
  control_discount_pct    NUMERIC(5,2)   NOT NULL DEFAULT 0,
  treatment_discount_pct  NUMERIC(5,2)   NOT NULL,
  -- Shopify discount resource ID applied to the treatment group
  shopify_discount_id     TEXT,
  started_at              TIMESTAMPTZ,
  concluded_at            TIMESTAMPTZ,
  -- conclusion_type: significance_reached | max_duration | kill_switch | manual
  conclusion_type         TEXT,
  -- Snapshot of the latest computed Bayesian stats (refreshed every 6h by Celery)
  latest_stats            JSONB,
  -- Recommendation that triggered this experiment
  recommendation_id       BIGINT,
  created_at              TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_experiments_merchant    ON experiments(merchant_id);
CREATE INDEX idx_experiments_product     ON experiments(product_id);
CREATE INDEX idx_experiments_status      ON experiments(status);
CREATE INDEX idx_experiments_active      ON experiments(merchant_id, status) WHERE status = 'active';

-- migrate:down
DROP TABLE IF EXISTS experiments;
