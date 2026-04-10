-- migrate:up
CREATE TABLE merchants (
  id              BIGSERIAL PRIMARY KEY,
  shopify_domain  TEXT        NOT NULL UNIQUE,
  -- access_token is stored encrypted using pgcrypto pgp_sym_encrypt.
  -- The plaintext token is never stored. Decrypt with:
  --   pgp_sym_decrypt(access_token, $DB_ENCRYPTION_KEY)::text
  access_token    BYTEA       NOT NULL,
  scopes          TEXT,
  email           TEXT,
  plan_name       TEXT,
  installed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  uninstalled_at  TIMESTAMPTZ,
  -- Which decision engine is active for this merchant.
  -- Starts as 'rules_v1', transitions to 'bandit_v1' after 5 completed experiments.
  active_engine_version TEXT NOT NULL DEFAULT 'rules_v1',
  -- Global auto-approve toggle (Phase 5). Off by default.
  auto_approve_enabled  BOOLEAN NOT NULL DEFAULT FALSE,
  -- Maximum discount the system can recommend (merchant-configurable, default 20%).
  safe_zone_max_pct     NUMERIC(5,2) NOT NULL DEFAULT 20.00,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_merchants_domain ON merchants(shopify_domain);

-- migrate:down
DROP TABLE IF EXISTS merchants;
