-- migrate:up
CREATE TABLE order_line_items (
  id                  BIGSERIAL      NOT NULL,
  merchant_id         BIGINT         NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
  shopify_order_id    TEXT           NOT NULL,
  shopify_variant_id  TEXT           NOT NULL,
  quantity            INT            NOT NULL DEFAULT 1,
  price               NUMERIC(12,2)  NOT NULL,
  discount_amount     NUMERIC(12,2)  NOT NULL DEFAULT 0,
  -- experiment_id links this line item to an A/B experiment for outcome tracking
  experiment_id       BIGINT,
  -- Which arm this purchase came from (null if not part of an experiment)
  experiment_group    TEXT,          -- control | treatment | null
  created_at          TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
  -- TimescaleDB (TS103): unique constraints on a hypertable must include the
  -- partition column. Composite PK satisfies this requirement.
  PRIMARY KEY (id, created_at)
);

CREATE INDEX idx_order_items_merchant     ON order_line_items(merchant_id);
CREATE INDEX idx_order_items_variant      ON order_line_items(shopify_variant_id);
CREATE INDEX idx_order_items_order        ON order_line_items(shopify_order_id);
CREATE INDEX idx_order_items_experiment   ON order_line_items(experiment_id) WHERE experiment_id IS NOT NULL;
CREATE INDEX idx_order_items_created      ON order_line_items(created_at DESC);

-- Convert to a TimescaleDB hypertable partitioned by created_at.
-- chunk_time_interval = 7 days is a good default for high-volume order data.
SELECT create_hypertable(
  'order_line_items',
  'created_at',
  chunk_time_interval => INTERVAL '7 days',
  if_not_exists => TRUE
);

-- migrate:down
DROP TABLE IF EXISTS order_line_items;
