-- migrate:up
CREATE TABLE recommendations (
  id                      BIGSERIAL      PRIMARY KEY,
  merchant_id             BIGINT         NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
  product_id              BIGINT         NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  recommended_discount_pct NUMERIC(5,2)  NOT NULL,
  -- Plain-text rationale from the rule/bandit engine (used as LLM input)
  rationale               TEXT           NOT NULL,
  -- LLM-generated merchant-friendly explanation
  llm_explanation         TEXT,
  confidence_score        NUMERIC(4,3)   NOT NULL,  -- 0.000 – 1.000
  -- Which engine generated this: rules_v1 | bandit_v1
  model_version           TEXT           NOT NULL,
  -- Snapshot of the exact feature vector used — essential for RL replay
  feature_snapshot        JSONB          NOT NULL DEFAULT '{}',
  -- status: pending | approved | rejected | edited_and_approved
  status                  TEXT           NOT NULL DEFAULT 'pending',
  -- If the merchant edited the discount before approving, this captures their choice.
  -- The delta (recommended_discount_pct - merchant_edit_pct) is a training signal.
  merchant_edit_pct       NUMERIC(5,2),
  created_at              TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
  reviewed_at             TIMESTAMPTZ
);

CREATE INDEX idx_recommendations_merchant  ON recommendations(merchant_id);
CREATE INDEX idx_recommendations_product   ON recommendations(product_id);
CREATE INDEX idx_recommendations_status    ON recommendations(status);
CREATE INDEX idx_recommendations_pending   ON recommendations(merchant_id) WHERE status = 'pending';

-- migrate:down
DROP TABLE IF EXISTS recommendations;
