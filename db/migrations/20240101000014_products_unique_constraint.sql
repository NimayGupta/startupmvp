-- migrate:up
-- Backfill: add unique constraint on (merchant_id, shopify_product_id) if missing.
-- The original products migration defined this constraint, but DBs initialised
-- from an older schema dump may be missing it, causing ON CONFLICT upserts to fail.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'products'::regclass
      AND contype   = 'u'
      AND conname   = 'products_merchant_id_shopify_product_id_key'
  ) THEN
    ALTER TABLE products
      ADD CONSTRAINT products_merchant_id_shopify_product_id_key
      UNIQUE (merchant_id, shopify_product_id);
  END IF;
END;
$$;

-- migrate:down
ALTER TABLE products
  DROP CONSTRAINT IF EXISTS products_merchant_id_shopify_product_id_key;
