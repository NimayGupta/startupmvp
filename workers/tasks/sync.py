"""
Phase 1D — Bulk historical data sync task.

Triggered once on merchant install after OAuth completes.
Pulls products + orders from the last 90 days via Shopify Bulk Operations API,
then upserts all records into the database.
"""
import io
import json
import logging
import time
from typing import Any

import httpx
from celery import Task
from celery.utils.log import get_task_logger

from workers.celery_app import celery_app
from workers.db import get_sync_db_connection
from workers.shopify import get_merchant_credentials, shopify_graphql_request

logger = get_task_logger(__name__)

# ---------------------------------------------------------------------------
# GraphQL mutations / queries
# ---------------------------------------------------------------------------

BULK_PRODUCTS_QUERY = """
mutation {
  bulkOperationRunQuery(
    query: \"\"\"
      {
        products(query: "created_at:>={{ ninety_days_ago }}") {
          edges {
            node {
              id
              title
              handle
              productType
              vendor
              status
              tags
              variants {
                edges {
                  node {
                    id
                    title
                    price
                    compareAtPrice
                    sku
                    inventoryQuantity
                    inventoryPolicy
                  }
                }
              }
            }
          }
        }
      }
    \"\"\"
  ) {
    bulkOperation {
      id
      status
    }
    userErrors {
      field
      message
    }
  }
}
"""

BULK_ORDERS_QUERY = """
mutation {
  bulkOperationRunQuery(
    query: \"\"\"
      {
        orders(query: "created_at:>={{ ninety_days_ago }}") {
          edges {
            node {
              id
              lineItems {
                edges {
                  node {
                    variant {
                      id
                    }
                    quantity
                    originalUnitPriceSet {
                      shopMoney {
                        amount
                      }
                    }
                    discountedUnitPriceSet {
                      shopMoney {
                        amount
                      }
                    }
                  }
                }
              }
            }
          }
        }
      }
    \"\"\"
  ) {
    bulkOperation {
      id
      status
    }
    userErrors {
      field
      message
    }
  }
}
"""

POLL_BULK_OPERATION = """
query {
  currentBulkOperation {
    id
    status
    errorCode
    url
    objectCount
  }
}
"""


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------


@celery_app.task(
    bind=True,
    name="workers.tasks.sync.bulk_sync_merchant",
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
)
def bulk_sync_merchant(self: Task, merchant_id: int) -> dict[str, Any]:
    """
    One-time bulk historical sync for a newly installed merchant.
    Pulls 90 days of products and orders from Shopify Bulk Operations API.
    """
    logger.info("Starting bulk sync for merchant_id=%s", merchant_id)

    domain, access_token = get_merchant_credentials(merchant_id)
    ninety_days_ago = _ninety_days_ago_iso()

    # --- Sync products ---
    product_count = _run_bulk_operation(
        domain=domain,
        access_token=access_token,
        mutation=BULK_PRODUCTS_QUERY.replace("{{ ninety_days_ago }}", ninety_days_ago),
        processor=lambda rows: _upsert_products(merchant_id, rows),
        operation_name="products",
    )

    # --- Sync orders ---
    order_count = _run_bulk_operation(
        domain=domain,
        access_token=access_token,
        mutation=BULK_ORDERS_QUERY.replace("{{ ninety_days_ago }}", ninety_days_ago),
        processor=lambda rows: _upsert_order_line_items(merchant_id, rows),
        operation_name="orders",
    )

    # --- Write sync_completed event ---
    _write_sync_completed_event(merchant_id, product_count, order_count)

    logger.info(
        "Bulk sync complete for merchant_id=%s: %d products, %d order line items",
        merchant_id,
        product_count,
        order_count,
    )
    return {"merchant_id": merchant_id, "product_count": product_count, "order_count": order_count}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ninety_days_ago_iso() -> str:
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run_bulk_operation(
    domain: str,
    access_token: str,
    mutation: str,
    processor: Any,
    operation_name: str,
) -> int:
    """Issue a bulk operation mutation, poll until complete, download and process results."""

    # Issue mutation
    response = shopify_graphql_request(domain, access_token, mutation)
    errors = (
        response.get("data", {}).get("bulkOperationRunQuery", {}).get("userErrors", [])
    )
    if errors:
        raise RuntimeError(f"Bulk operation user errors for {operation_name}: {errors}")

    # Poll until COMPLETED
    result_url = _poll_bulk_operation(domain, access_token, operation_name)

    # Download and parse JSONL
    rows = _download_jsonl(result_url)
    return processor(rows)


def _poll_bulk_operation(domain: str, access_token: str, operation_name: str) -> str:
    """
    Poll currentBulkOperation every 5 seconds until status == COMPLETED.
    Raises RuntimeError on FAILED or timeout (30 min).
    """
    max_polls = 360  # 30 minutes at 5s intervals
    for _ in range(max_polls):
        time.sleep(5)
        response = shopify_graphql_request(domain, access_token, POLL_BULK_OPERATION)
        op = response.get("data", {}).get("currentBulkOperation", {})
        status = op.get("status")
        if status == "COMPLETED":
            url = op.get("url")
            if not url:
                raise RuntimeError(f"Bulk operation {operation_name} completed but no URL returned")
            return url
        if status in ("FAILED", "CANCELED"):
            raise RuntimeError(f"Bulk operation {operation_name} ended with status={status} error={op.get('errorCode')}")
        logger.debug("Bulk operation %s status=%s, waiting...", operation_name, status)

    raise TimeoutError(f"Bulk operation {operation_name} timed out after 30 minutes")


def _download_jsonl(url: str) -> list[dict[str, Any]]:
    """Download and parse a Shopify bulk operation JSONL result file."""
    with httpx.Client(timeout=120) as client:
        response = client.get(url)
        response.raise_for_status()

    rows = []
    for line in io.StringIO(response.text):
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _upsert_products(merchant_id: int, rows: list[dict[str, Any]]) -> int:
    """
    Parse JSONL product rows and upsert into products + product_variants tables.
    Returns the number of products upserted.
    """
    import re

    with get_sync_db_connection() as conn:
        with conn.cursor() as cur:
            product_count = 0
            for row in rows:
                # Shopify GIDs look like "gid://shopify/Product/123456"
                shopify_product_id = _extract_gid(row.get("id", ""))
                if not shopify_product_id:
                    continue

                # Upsert product
                cur.execute(
                    """
                    INSERT INTO products
                      (merchant_id, shopify_product_id, title, handle, product_type, vendor, status, tags)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (merchant_id, shopify_product_id)
                    DO UPDATE SET
                      title = EXCLUDED.title,
                      handle = EXCLUDED.handle,
                      product_type = EXCLUDED.product_type,
                      vendor = EXCLUDED.vendor,
                      status = EXCLUDED.status,
                      tags = EXCLUDED.tags,
                      synced_at = NOW(),
                      updated_at = NOW()
                    RETURNING id
                    """,
                    (
                        merchant_id,
                        shopify_product_id,
                        row.get("title", ""),
                        row.get("handle"),
                        row.get("productType"),
                        row.get("vendor"),
                        row.get("status", "active").lower(),
                        row.get("tags", []),
                    ),
                )
                result = cur.fetchone()
                if result is None:
                    continue
                product_db_id = result[0]
                product_count += 1

                # Upsert variants
                for variant_edge in row.get("variants", {}).get("edges", []):
                    variant = variant_edge.get("node", {})
                    shopify_variant_id = _extract_gid(variant.get("id", ""))
                    if not shopify_variant_id:
                        continue
                    cur.execute(
                        """
                        INSERT INTO product_variants
                          (product_id, shopify_variant_id, title, price, compare_at_price,
                           sku, inventory_quantity, inventory_policy)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (shopify_variant_id)
                        DO UPDATE SET
                          title = EXCLUDED.title,
                          price = EXCLUDED.price,
                          compare_at_price = EXCLUDED.compare_at_price,
                          sku = EXCLUDED.sku,
                          inventory_quantity = EXCLUDED.inventory_quantity,
                          inventory_policy = EXCLUDED.inventory_policy,
                          synced_at = NOW(),
                          updated_at = NOW()
                        """,
                        (
                            product_db_id,
                            shopify_variant_id,
                            variant.get("title", "Default Title"),
                            variant.get("price", "0"),
                            variant.get("compareAtPrice"),
                            variant.get("sku"),
                            variant.get("inventoryQuantity", 0),
                            variant.get("inventoryPolicy", "deny"),
                        ),
                    )

            conn.commit()
    return product_count


def _upsert_order_line_items(merchant_id: int, rows: list[dict[str, Any]]) -> int:
    """
    Parse JSONL order rows and upsert into order_line_items.
    Returns the number of line items inserted.
    """
    with get_sync_db_connection() as conn:
        with conn.cursor() as cur:
            line_item_count = 0
            for row in rows:
                shopify_order_id = _extract_gid(row.get("id", ""))
                if not shopify_order_id:
                    continue

                for item_edge in row.get("lineItems", {}).get("edges", []):
                    item = item_edge.get("node", {})
                    variant = item.get("variant") or {}
                    shopify_variant_id = _extract_gid(variant.get("id", ""))
                    if not shopify_variant_id:
                        continue

                    original_price = float(
                        item.get("originalUnitPriceSet", {})
                        .get("shopMoney", {})
                        .get("amount", 0)
                    )
                    discounted_price = float(
                        item.get("discountedUnitPriceSet", {})
                        .get("shopMoney", {})
                        .get("amount", original_price)
                    )
                    discount_amount = original_price - discounted_price

                    cur.execute(
                        """
                        INSERT INTO order_line_items
                          (merchant_id, shopify_order_id, shopify_variant_id,
                           quantity, price, discount_amount)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT DO NOTHING
                        """,
                        (
                            merchant_id,
                            shopify_order_id,
                            shopify_variant_id,
                            item.get("quantity", 1),
                            discounted_price,
                            discount_amount,
                        ),
                    )
                    line_item_count += 1

            conn.commit()
    return line_item_count


def _write_sync_completed_event(merchant_id: int, product_count: int, order_count: int) -> None:
    with get_sync_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO event_log (merchant_id, event_type, payload)
                VALUES (%s, 'sync_completed', %s)
                """,
                (merchant_id, json.dumps({"product_count": product_count, "order_count": order_count})),
            )
        conn.commit()


def _extract_gid(gid: str) -> str:
    """Extract the numeric ID from a Shopify GID string. e.g. 'gid://shopify/Product/123' → '123'"""
    if gid and "/" in gid:
        return gid.rsplit("/", 1)[-1]
    return gid
