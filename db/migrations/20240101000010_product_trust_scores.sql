-- migrate:up
-- Per-product trust scores drive the auto-approve system (Phase 5).
-- Score = (tests_positive / tests_completed) * log1p(tests_completed) / log1p(10)
-- Capped at 1.0. Requires minimum 3 completed tests before score > 0.
CREATE TABLE product_trust_scores (
  id                BIGSERIAL      PRIMARY KEY,
  product_id        BIGINT         NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  merchant_id       BIGINT         NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
  trust_score       NUMERIC(5,4)   NOT NULL DEFAULT 0,  -- 0.0000 – 1.0000
  tests_completed   INT            NOT NULL DEFAULT 0,
  tests_positive    INT            NOT NULL DEFAULT 0,
  updated_at        TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
  UNIQUE(product_id, merchant_id)
);

CREATE INDEX idx_trust_scores_merchant   ON product_trust_scores(merchant_id);
CREATE INDEX idx_trust_scores_product    ON product_trust_scores(product_id);
-- Index for querying auto-approve eligible products
CREATE INDEX idx_trust_scores_eligible   ON product_trust_scores(merchant_id, trust_score)
  WHERE trust_score >= 0.7;

-- migrate:down
DROP TABLE IF EXISTS product_trust_scores;
