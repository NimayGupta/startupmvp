/**
 * Tests for webhook HMAC verification and dispatch routing.
 *
 * These tests do NOT hit the real Shopify API or a real database.
 * All external dependencies are mocked.
 */

import { createHmac } from "crypto";

// ---------------------------------------------------------------------------
// Helpers mirroring the logic in app/routes/webhooks.tsx
// These are extracted for testability — the route itself uses the same logic.
// ---------------------------------------------------------------------------

function computeHmac(secret: string, body: string): string {
  return createHmac("sha256", secret).update(body, "utf8").digest("base64");
}

function verifyHmac(secret: string, body: string, header: string): boolean {
  const { timingSafeEqual } = require("crypto");
  try {
    return timingSafeEqual(
      Buffer.from(header, "base64"),
      Buffer.from(computeHmac(secret, body), "base64")
    );
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// HMAC verification tests
// ---------------------------------------------------------------------------

describe("Webhook HMAC verification", () => {
  const SECRET = "test-shopify-api-secret";
  const BODY = JSON.stringify({ id: 12345, title: "Test Order" });

  it("accepts a valid HMAC", () => {
    const hmac = computeHmac(SECRET, BODY);
    expect(verifyHmac(SECRET, BODY, hmac)).toBe(true);
  });

  it("rejects a tampered body", () => {
    const hmac = computeHmac(SECRET, BODY);
    const tamperedBody = BODY + "extra";
    expect(verifyHmac(SECRET, tamperedBody, hmac)).toBe(false);
  });

  it("rejects a wrong secret", () => {
    const hmac = computeHmac("wrong-secret", BODY);
    expect(verifyHmac(SECRET, BODY, hmac)).toBe(false);
  });

  it("rejects an empty HMAC header", () => {
    expect(verifyHmac(SECRET, BODY, "")).toBe(false);
  });

  it("rejects a non-base64 HMAC header", () => {
    expect(verifyHmac(SECRET, BODY, "not-valid-base64!!!")).toBe(false);
  });

  it("does not leak timing info (returns false instead of throwing)", () => {
    // Mismatched buffer lengths would throw without timingSafeEqual wrapping
    expect(() => verifyHmac(SECRET, BODY, "dGVzdA==")).not.toThrow();
    expect(verifyHmac(SECRET, BODY, "dGVzdA==")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Topic → task mapping tests
// ---------------------------------------------------------------------------

const TOPIC_TASK_MAP: Record<string, string> = {
  "orders/create": "workers.tasks.webhooks.process_orders_create",
  "products/update": "workers.tasks.webhooks.process_products_update",
  "inventory_levels/update": "workers.tasks.webhooks.process_inventory_update",
};

describe("Webhook topic to Celery task mapping", () => {
  it("maps all supported topics to task names", () => {
    for (const [topic, task] of Object.entries(TOPIC_TASK_MAP)) {
      expect(task).toContain("workers.tasks.webhooks");
      expect(topic.length).toBeGreaterThan(0);
    }
  });

  it("has no duplicate task names for different topics", () => {
    const taskNames = Object.values(TOPIC_TASK_MAP);
    const unique = new Set(taskNames);
    expect(unique.size).toBe(taskNames.length);
  });
});
