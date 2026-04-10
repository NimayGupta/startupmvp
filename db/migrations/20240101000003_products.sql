-- migrate:up
CREATE TABLE products (
  id                  BIGSERIAL   PRIMARY KEY,
  merchant_id         BIGINT      NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
  shopify_product_id  TEXT        NOT NULL,
  title               TEXT        NOT NULL,
  handle              TEXT,
  product_type        TEXT,
  vendor              TEXT,
  status              TEXT        NOT NULL DEFAULT 'active',  -- active | archived | draft
  tags                TEXT[],
  synced_at           TIMESTAMPTZ,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(merchant_id, shopify_product_id)
);

CREATE INDEX idx_products_merchant       ON products(merchant_id);
CREATE INDEX idx_products_shopify_id     ON products(shopify_product_id);
CREATE INDEX idx_products_merchant_type  ON products(merchant_id, product_type);

-- migrate:down
DROP TABLE IF EXISTS products;
