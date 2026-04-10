-- migrate:up
-- Stripe subscription records for billing (Phase 6).
-- Plan tiers: free | growth | pro
CREATE TABLE subscriptions (
  id                      BIGSERIAL   PRIMARY KEY,
  merchant_id             BIGINT      NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
  stripe_customer_id      TEXT        NOT NULL,
  stripe_subscription_id  TEXT,
  -- plan: free | growth | pro
  plan                    TEXT        NOT NULL DEFAULT 'free',
  -- status mirrors Stripe subscription status: active | past_due | canceled | trialing
  status                  TEXT        NOT NULL DEFAULT 'active',
  current_period_start    TIMESTAMPTZ,
  current_period_end      TIMESTAMPTZ,
  created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(merchant_id)
);

CREATE INDEX idx_subscriptions_merchant        ON subscriptions(merchant_id);
CREATE INDEX idx_subscriptions_stripe_customer ON subscriptions(stripe_customer_id);

-- migrate:down
DROP TABLE IF EXISTS subscriptions;
