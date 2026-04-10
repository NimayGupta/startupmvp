-- migrate:up
-- Thompson Sampling Beta distribution parameters for each (merchant, context_bucket, action) tuple.
-- action is a discrete discount level: 0, 5, 10, 15, 20 (percent).
-- context_bucket is a string key e.g. "under_25_high_low" (price_tier_inventory_conversion).
-- Alpha and beta track positive and negative rewards respectively.
CREATE TABLE bandit_parameters (
  id              BIGSERIAL      PRIMARY KEY,
  merchant_id     BIGINT         NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
  -- Discrete context bucket derived from feature vector binning
  context_bucket  TEXT           NOT NULL,
  -- Discount action in integer percent (0, 5, 10, 15, 20)
  action          INT            NOT NULL,
  -- Beta distribution parameters: alpha = successes + 1, beta = failures + 1
  alpha           NUMERIC(10,4)  NOT NULL DEFAULT 1.0,
  beta            NUMERIC(10,4)  NOT NULL DEFAULT 1.0,
  -- Total observations used to build these parameters
  observations    INT            NOT NULL DEFAULT 0,
  updated_at      TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
  UNIQUE(merchant_id, context_bucket, action)
);

CREATE INDEX idx_bandit_merchant         ON bandit_parameters(merchant_id);
CREATE INDEX idx_bandit_context          ON bandit_parameters(merchant_id, context_bucket);

-- migrate:down
DROP TABLE IF EXISTS bandit_parameters;
