/**
 * Phase 4B — A/B Test Traffic Splitter (Checkout UI Extension)
 *
 * Runs at purchase.checkout.block.render before payment.
 *
 * Responsibilities:
 * 1. Check if any product in the cart has an active A/B experiment.
 * 2. Deterministically assign the session to control or treatment (50/50)
 *    using a murmurhash3 of (sessionId + experimentId).
 * 3. Write cart attributes so the Shopify Discount Function can read them:
 *      ab_group          → "control" | "treatment"
 *      ab_discount_pct   → the treatment discount % as a string
 *      ab_experiment_id  → the experiment's DB ID
 *      ab_session_hash   → the hashed identifier (for event logging)
 * 4. The assignment is logged server-side via the order webhook when the
 *    order is placed (cart attributes appear as note_attributes on the order).
 *
 * The extension renders nothing visible — it only mutates cart attributes.
 */

import { useEffect } from "react";
import {
  reactExtension,
  useApplyAttributeChange,
  useAttributes,
  useCartLines,
  useCustomer,
  useSessionToken,
} from "@shopify/ui-extensions-react/checkout";

const BACKEND_URL = __BACKEND_URL__ as string; // injected at build time

export default reactExtension(
  "purchase.checkout.block.render",
  () => <AbTestSplitter />,
);

interface ActiveExperiment {
  id: number;
  treatment_discount_pct: number;
}

function AbTestSplitter() {
  const applyAttributeChange = useApplyAttributeChange();
  const attributes = useAttributes();
  const cartLines = useCartLines();
  const customer = useCustomer();
  const sessionToken = useSessionToken();

  useEffect(() => {
    // Only run once — if ab_group is already set, skip
    if (attributes.find((a) => a.key === "ab_group")) return;

    void (async () => {
      // Collect shopify product IDs from the cart
      const productIds = cartLines.flatMap((line) => {
        const merch = line.merchandise;
        if ("product" in merch && merch.product?.id) {
          return [merch.product.id.replace("gid://shopify/Product/", "")];
        }
        return [];
      });
      if (productIds.length === 0) return;

      // Ask the backend if there's an active experiment for any cart product
      let experiment: ActiveExperiment | null = null;
      try {
        const token = await sessionToken.get();
        const resp = await fetch(
          `${BACKEND_URL}/api/active-experiment?product_ids=${productIds.join(",")}`,
          {
            headers: { Authorization: `Bearer ${token}` },
          },
        );
        if (resp.ok) {
          const data = await resp.json();
          if (data.experiment) experiment = data.experiment as ActiveExperiment;
        }
      } catch {
        // No experiment or backend unreachable — skip silently
        return;
      }

      if (!experiment) return;

      // Build a stable session identifier from customer ID or a fallback
      const sessionId =
        customer?.id?.replace("gid://shopify/Customer/", "") ??
        String(Date.now());
      const sessionHash = murmurhash3(`${sessionId}:${experiment.id}`);
      const group = sessionHash % 100 < 50 ? "control" : "treatment";

      // Set cart attributes (read by the Discount Function + order webhook)
      await Promise.all([
        applyAttributeChange({ key: "ab_group", type: "updateAttribute", value: group }),
        applyAttributeChange({
          key: "ab_discount_pct",
          type: "updateAttribute",
          value: String(experiment.treatment_discount_pct),
        }),
        applyAttributeChange({
          key: "ab_experiment_id",
          type: "updateAttribute",
          value: String(experiment.id),
        }),
        applyAttributeChange({
          key: "ab_session_hash",
          type: "updateAttribute",
          value: String(sessionHash),
        }),
      ]);
    })();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // This extension renders no UI — it only sets cart attributes
  return null;
}

// ---------------------------------------------------------------------------
// MurmurHash3 (32-bit) — deterministic, no external dep
// ---------------------------------------------------------------------------
function murmurhash3(str: string): number {
  let h1 = 0xdeadbeef;
  for (let i = 0; i < str.length; i++) {
    let k = str.charCodeAt(i);
    k = Math.imul(k, 0xcc9e2d51);
    k = ((k << 15) | (k >>> 17)) >>> 0;
    k = Math.imul(k, 0x1b873593);
    h1 ^= k;
    h1 = ((h1 << 13) | (h1 >>> 19)) >>> 0;
    h1 = (Math.imul(h1, 5) + 0xe6546b64) >>> 0;
  }
  h1 ^= str.length;
  h1 ^= h1 >>> 16;
  h1 = Math.imul(h1, 0x85ebca6b) >>> 0;
  h1 ^= h1 >>> 13;
  h1 = Math.imul(h1, 0xc2b2ae35) >>> 0;
  h1 ^= h1 >>> 16;
  return h1 >>> 0;
}
