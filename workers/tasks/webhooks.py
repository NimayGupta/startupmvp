"""
Phase 1C — Background webhook processing tasks.

Webhook handlers in the Remix app must return HTTP 200 within 5 seconds.
Heavy processing is offloaded to these Celery tasks.
"""
import json
import logging
from typing import Any

from celery.utils.log import get_task_logger

from workers.celery_app import celery_app
from workers.db import get_sync_db_connection

logger = get_task_logger(__name__)


@celery_app.task(
    bind=True,
    name="workers.tasks.webhooks.process_orders_create",
    max_retries=5,
    default_retry_delay=30,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
)
def process_orders_create(self: Any, merchant_id: int, payload: dict[str, Any]) -> None:
    """
    Process an orders/create webhook payload.
    Upserts order line items into the database.
    """
    shopify_order_id = str(payload.get("id", ""))
    if not shopify_order_id:
        logger.warning("orders/create webhook missing order id, skipping")
        return

    line_items = payload.get("line_items", [])
    inserted = 0

    with get_sync_db_connection() as conn:
        with conn.cursor() as cur:
            for item in line_items:
                variant_id = str(item.get("variant_id", "") or "")
                if not variant_id:
                    continue
                price = float(item.get("price", 0))
                quantity = int(item.get("quantity", 1))

                # Sum discounts across all discount allocations for this line item
                discount_amount = sum(
                    float(d.get("amount", 0))
                    for d in item.get("discount_allocations", [])
                )

                cur.execute(
                    """
                    INSERT INTO order_line_items
                      (merchant_id, shopify_order_id, shopify_variant_id,
                       quantity, price, discount_amount)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (merchant_id, shopify_order_id, variant_id, quantity, price, discount_amount),
                )
                inserted += 1

        conn.commit()

    logger.info("orders/create: inserted %d line items for order %s", inserted, shopify_order_id)


@celery_app.task(
    bind=True,
    name="workers.tasks.webhooks.process_products_update",
    max_retries=5,
    default_retry_delay=30,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
)
def process_products_update(self: Any, merchant_id: int, payload: dict[str, Any]) -> None:
    """
    Process a products/update webhook payload.
    Updates product and variant records in the database.
    """
    shopify_product_id = str(payload.get("id", ""))
    if not shopify_product_id:
        return

    with get_sync_db_connection() as conn:
        with conn.cursor() as cur:
            # Upsert product
            cur.execute(
                """
                INSERT INTO products
                  (merchant_id, shopify_product_id, title, handle, product_type, vendor, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (merchant_id, shopify_product_id)
                DO UPDATE SET
                  title = EXCLUDED.title,
                  handle = EXCLUDED.handle,
                  product_type = EXCLUDED.product_type,
                  vendor = EXCLUDED.vendor,
                  status = EXCLUDED.status,
                  synced_at = NOW(),
                  updated_at = NOW()
                RETURNING id
                """,
                (
                    merchant_id,
                    shopify_product_id,
                    payload.get("title", ""),
                    payload.get("handle"),
                    payload.get("product_type"),
                    payload.get("vendor"),
                    (payload.get("status", "active") or "active").lower(),
                ),
            )
            result = cur.fetchone()
            if result is None:
                conn.commit()
                return
            product_db_id = result[0]

            # Upsert variants
            for variant in payload.get("variants", []):
                shopify_variant_id = str(variant.get("id", ""))
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
                        variant.get("compare_at_price"),
                        variant.get("sku"),
                        variant.get("inventory_quantity", 0),
                        variant.get("inventory_management") or "deny",
                    ),
                )

        conn.commit()
    logger.info("products/update: upserted product %s for merchant %s", shopify_product_id, merchant_id)


@celery_app.task(
    bind=True,
    name="workers.tasks.webhooks.process_inventory_update",
    max_retries=5,
    default_retry_delay=30,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
)
def process_inventory_update(self: Any, merchant_id: int, payload: dict[str, Any]) -> None:
    """
    Process an inventory_levels/update webhook payload.
    Updates inventory_quantity on the affected variant.
    """
    inventory_item_id = payload.get("inventory_item_id")
    available = payload.get("available")

    if inventory_item_id is None or available is None:
        return

    # inventory_item_id maps 1:1 to a variant's inventory — we identify the
    # variant by matching the Shopify variant ID stored in product_variants.
    # In practice Shopify sends variant_id in some webhook versions; fall back
    # to a subquery if needed.
    with get_sync_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE product_variants
                SET inventory_quantity = %s, updated_at = NOW()
                WHERE shopify_variant_id = (
                  SELECT shopify_variant_id FROM product_variants
                  WHERE shopify_variant_id::text = %s
                  LIMIT 1
                )
                """,
                (available, str(inventory_item_id)),
            )
        conn.commit()
    logger.info("inventory_levels/update: set available=%s for inventory_item_id=%s", available, inventory_item_id)
