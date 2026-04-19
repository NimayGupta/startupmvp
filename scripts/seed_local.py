"""
Local dev seed script — populates the DB and Redis feature store so the
recommendation engine works without a real Shopify connection.

What it inserts:
  - 1 merchant row matched to your dev Shopify session's shop domain
  - 1 product + product_variant  (price $75, 80 units in stock)
  - 28 days of synthetic order_line_items (~3 orders/day)
  - Calls GET /features/{merchant_id} so Redis is warm immediately

Run from the repo root:
  python scripts/seed_local.py --shop-domain your-dev-store.myshopify.com

The shop domain MUST match what Shopify CLI reports as your dev store domain,
otherwise the Remix loader will create a different merchant row and show
"No products synced yet".  Find it in the CLI output or:
  SELECT shopify_domain FROM merchants ORDER BY id;
"""
from __future__ import annotations

import argparse
import os
import random
import sys
from datetime import datetime, timedelta, timezone

import psycopg2
try:
    import requests
except ImportError:
    import urllib.request, json as _json  # type: ignore[no-redef]

    class _FakeResp:
        def __init__(self, data: bytes, status: int):
            self._data, self.status_code = data, status
        def raise_for_status(self):
            if self.status_code >= 400:
                raise Exception(f"HTTP {self.status_code}")
        def json(self):
            return _json.loads(self._data)

    class requests:  # type: ignore[no-redef]
        @staticmethod
        def _req(method, url, headers=None, timeout=None, **_):
            req = urllib.request.Request(url, method=method, headers=headers or {})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return _FakeResp(r.read(), r.status)
        @staticmethod
        def get(url, **kw): return requests._req("GET", url, **kw)
        @staticmethod
        def post(url, **kw): return requests._req("POST", url, **kw)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/discount_optimizer",
)
ENGINE_URL = os.getenv("ENGINE_URL", "http://localhost:8000")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")


def _conn():
    return psycopg2.connect(DATABASE_URL)


def seed_variant(cur, product_id: int, variant_shopify_id: str) -> int:
    cur.execute(
        """
        INSERT INTO product_variants
          (product_id, shopify_variant_id, title, price, compare_at_price,
           sku, inventory_quantity, synced_at)
        VALUES
          (%s, %s, 'Default Title', 75.00, 95.00, 'SKU-LOCAL-001', 80, NOW())
        ON CONFLICT (shopify_variant_id) DO UPDATE
          SET price = EXCLUDED.price,
              inventory_quantity = EXCLUDED.inventory_quantity,
              synced_at = NOW()
        RETURNING id
        """,
        (product_id, variant_shopify_id),
    )
    row = cur.fetchone()
    assert row is not None
    return int(row[0])


def seed_orders(cur, merchant_id: int, variant_shopify_id: str, days: int = 28):
    """Insert synthetic daily orders over the past `days` days."""
    rng = random.Random(42)
    now = datetime.now(tz=timezone.utc)
    rows = []
    order_num = 5000
    for day_offset in range(days):
        ts = now - timedelta(days=day_offset, hours=rng.randint(0, 23))
        daily_orders = rng.randint(1, 6)
        for _ in range(daily_orders):
            order_num += 1
            rows.append((
                merchant_id,
                f"gid://shopify/Order/{order_num}",
                variant_shopify_id,
                rng.randint(1, 2),      # quantity
                75.00,                  # price
                0.00,                   # discount_amount
                ts,
            ))

    cur.executemany(
        """
        INSERT INTO order_line_items
          (merchant_id, shopify_order_id, shopify_variant_id, quantity,
           price, discount_amount, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        rows,
    )
    return len(rows)


def trigger_feature_refresh(merchant_id: int) -> dict:
    resp = requests.get(
        f"{ENGINE_URL}/features/{merchant_id}",
        headers={"Authorization": f"Bearer {INTERNAL_API_KEY}"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def upsert_merchant(cur, shop_domain: str) -> int:
    """Insert or return merchant row for the given shop domain."""
    cur.execute(
        """
        INSERT INTO merchants (shopify_domain, access_token, scopes)
        VALUES (%s, 'local-dev-token', 'read_products,read_orders')
        ON CONFLICT (shopify_domain) DO UPDATE
          SET shopify_domain = EXCLUDED.shopify_domain
        RETURNING id
        """,
        (shop_domain,),
    )
    row = cur.fetchone()
    assert row is not None
    return int(row[0])


def upsert_product(cur, merchant_id: int, shopify_product_id: str) -> int:
    """Insert or return product row."""
    cur.execute(
        """
        INSERT INTO products
          (merchant_id, shopify_product_id, title, status, synced_at)
        VALUES (%s, %s, 'Test Product (Local)', 'active', NOW())
        ON CONFLICT (merchant_id, shopify_product_id) DO UPDATE
          SET title     = EXCLUDED.title,
              synced_at = NOW()
        RETURNING id
        """,
        (merchant_id, shopify_product_id),
    )
    row = cur.fetchone()
    assert row is not None
    return int(row[0])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--shop-domain",
        default="test.myshopify.com",
        help="Shopify dev store domain — must match your active Shopify CLI session",
    )
    parser.add_argument(
        "--product-id", type=int, default=None,
        help="Reuse an existing product row id (skips product upsert)",
    )
    args = parser.parse_args()

    shop_domain = args.shop_domain

    conn = _conn()
    try:
        with conn.cursor() as cur:
            merchant_id = upsert_merchant(cur, shop_domain)
            print(f"  merchant: id={merchant_id}  domain={shop_domain}")

            if args.product_id:
                product_id = args.product_id
                cur.execute(
                    "UPDATE products SET merchant_id = %s WHERE id = %s",
                    (merchant_id, product_id),
                )
                print(f"  product:  id={product_id}  (reassigned to merchant {merchant_id})")
            else:
                shopify_product_id = f"gid://shopify/Product/{merchant_id}001"
                product_id = upsert_product(cur, merchant_id, shopify_product_id)
                print(f"  product:  id={product_id}  shopify_id={shopify_product_id}")

            variant_shopify_id = f"gid://shopify/ProductVariant/{product_id}001"
            variant_id = seed_variant(cur, product_id, variant_shopify_id)
            print(f"  product_variants row: id={variant_id}  shopify_id={variant_shopify_id}")

            order_count = seed_orders(cur, merchant_id, variant_shopify_id)
            print(f"  order_line_items: inserted {order_count} rows (28 days)")

        conn.commit()
    finally:
        conn.close()

    print("  Triggering feature refresh (DB -> Redis) ...")
    result = trigger_feature_refresh(merchant_id)
    print(f"  Feature store: {result}")

    print()
    print("Done. Now test the recommendation engine:")
    print(f"  IKEY=$(grep INTERNAL_API_KEY .env | cut -d= -f2)")
    print(f"  curl -s -X POST -H \"Authorization: Bearer $IKEY\" \\")
    print(f"    -H \"Content-Type: application/json\" \\")
    print(f"    -d '{{\"merchant_id\": {merchant_id}, \"product_id\": {product_id}}}' \\")
    print(f"    http://localhost:8000/recommendations/generate | python -m json.tool")


if __name__ == "__main__":
    sys.exit(main())
