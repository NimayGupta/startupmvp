"""
Shopify API helpers for Celery tasks.

All Shopify API calls go through these helpers so that:
- 429 rate limit responses are retried with exponential backoff + jitter
- Access tokens are decrypted from the database
- GraphQL errors are surfaced as exceptions
"""
from __future__ import annotations

import json
import os
import random
import time
from typing import Any

import httpx
import psycopg2

DATABASE_URL = os.getenv("DATABASE_URL", "postgres://postgres:postgres@localhost:5432/discount_optimizer")
DB_ENCRYPTION_KEY = os.getenv("DB_ENCRYPTION_KEY", "")
SHOPIFY_API_VERSION = "2024-04"


def get_merchant_credentials(merchant_id: int) -> tuple[str, str]:
    """
    Returns (shopify_domain, decrypted_access_token) for a merchant.
    Decrypts the access_token using pgcrypto.
    """
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT shopify_domain,
                       pgp_sym_decrypt(access_token, %s)::text AS access_token
                FROM merchants
                WHERE id = %s
                """,
                (DB_ENCRYPTION_KEY, merchant_id),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"Merchant {merchant_id} not found")
            return row[0], row[1]
    finally:
        conn.close()


def shopify_graphql_request(
    domain: str,
    access_token: str,
    query: str,
    variables: dict[str, Any] | None = None,
    max_retries: int = 5,
) -> dict[str, Any]:
    """
    Execute a Shopify GraphQL Admin API request with automatic 429 retry.
    Raises RuntimeError on non-retryable errors.
    """
    url = f"https://{domain}/admin/api/{SHOPIFY_API_VERSION}/graphql.json"
    headers = {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json",
    }
    body: dict[str, Any] = {"query": query}
    if variables:
        body["variables"] = variables

    attempt = 0
    while True:
        attempt += 1
        try:
            with httpx.Client(timeout=30) as client:
                response = client.post(url, headers=headers, json=body)
        except httpx.RequestError as exc:
            if attempt >= max_retries:
                raise RuntimeError(f"Shopify API request failed after {max_retries} attempts: {exc}") from exc
            _backoff(attempt)
            continue

        if response.status_code == 429:
            if attempt >= max_retries:
                raise RuntimeError(f"Shopify API rate-limited after {max_retries} retries")
            retry_after = float(response.headers.get("Retry-After", 2 ** attempt))
            time.sleep(retry_after + random.uniform(0, 1))
            continue

        if response.status_code >= 500:
            if attempt >= max_retries:
                response.raise_for_status()
            _backoff(attempt)
            continue

        response.raise_for_status()
        data: dict[str, Any] = response.json()

        # Surface GraphQL-level errors
        if "errors" in data:
            raise RuntimeError(f"Shopify GraphQL errors: {data['errors']}")

        return data


def _backoff(attempt: int, base: float = 1.0, max_wait: float = 30.0) -> None:
    """Exponential backoff with jitter."""
    wait = min(base * (2 ** (attempt - 1)), max_wait) + random.uniform(0, 1)
    time.sleep(wait)
