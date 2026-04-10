-- migrate:up
CREATE TABLE product_variants (
  id                    BIGSERIAL      PRIMARY KEY,
  product_id            BIGINT         NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  shopify_variant_id    TEXT           NOT NULL,
  title                 TEXT           NOT NULL,
  price                 NUMERIC(12,2)  NOT NULL,
  compare_at_price      NUMERIC(12,2),
  sku                   TEXT,
  inventory_quantity    INT            NOT NULL DEFAULT 0,
  inventory_policy      TEXT,          -- deny | continue
  fulfillment_service   TEXT,
  synced_at             TIMESTAMPTZ,
  created_at            TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
  updated_at            TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
  UNIQUE(shopify_variant_id)
);

CREATE INDEX idx_variants_product        ON product_variants(product_id);
CREATE INDEX idx_variants_shopify_id     ON product_variants(shopify_variant_id);

-- migrate:down
DROP TABLE IF EXISTS product_variants;
