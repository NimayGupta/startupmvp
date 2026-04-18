import type { ActionFunctionArgs } from "@remix-run/node";
import { json } from "@remix-run/node";
import type Stripe from "stripe";
import { stripe, STRIPE_WEBHOOK_SECRET, upsertSubscription } from "../lib/stripe.server";
import { query } from "../lib/db.server";

/**
 * POST /webhooks/stripe
 *
 * Handles Stripe webhook events. Verify signature first, then process.
 * Register this URL in the Stripe dashboard as the webhook endpoint.
 *
 * Relevant events:
 *   customer.subscription.created
 *   customer.subscription.updated
 *   customer.subscription.deleted
 *   invoice.payment_failed
 */

async function getMerchantIdByCustomer(stripeCustomerId: string): Promise<number | null> {
  const rows = await query<{ merchant_id: number }>(
    "SELECT merchant_id FROM subscriptions WHERE stripe_customer_id = $1 LIMIT 1",
    [stripeCustomerId],
  );
  return rows[0]?.merchant_id ?? null;
}

function planFromSubscription(sub: Stripe.Subscription): string {
  // Map Stripe price ID back to plan slug.
  const priceId = sub.items.data[0]?.price?.id ?? "";
  const growthPriceId = process.env.STRIPE_GROWTH_PRICE_ID ?? "";
  const proPriceId = process.env.STRIPE_PRO_PRICE_ID ?? "";
  if (priceId === proPriceId) return "pro";
  if (priceId === growthPriceId) return "growth";
  return "free";
}

export const action = async ({ request }: ActionFunctionArgs) => {
  if (request.method !== "POST") {
    return json({ error: "Method not allowed" }, { status: 405 });
  }

  const rawBody = await request.text();
  const signature = request.headers.get("stripe-signature") ?? "";

  let event: Stripe.Event;
  try {
    event = stripe.webhooks.constructEvent(rawBody, signature, STRIPE_WEBHOOK_SECRET);
  } catch (err) {
    console.error("[stripe webhook] signature verification failed:", err);
    return json({ error: "Invalid signature" }, { status: 400 });
  }

  try {
    switch (event.type) {
      case "customer.subscription.created":
      case "customer.subscription.updated": {
        const sub = event.data.object as Stripe.Subscription;
        const merchantId = await getMerchantIdByCustomer(sub.customer as string);
        if (!merchantId) {
          console.warn("[stripe webhook] no merchant for customer", sub.customer);
          break;
        }
        const plan = planFromSubscription(sub);
        const periodEndTimestamp = sub.items.data[0]?.current_period_end;
        const periodEnd = periodEndTimestamp
          ? new Date(periodEndTimestamp * 1000)
          : null;
        await upsertSubscription(
          merchantId,
          sub.customer as string,
          plan,
          sub.status,
          sub.id,
          periodEnd,
        );
        console.info(
          `[stripe webhook] subscription updated: merchant=${merchantId} plan=${plan} status=${sub.status}`,
        );
        break;
      }

      case "customer.subscription.deleted": {
        const sub = event.data.object as Stripe.Subscription;
        const merchantId = await getMerchantIdByCustomer(sub.customer as string);
        if (!merchantId) break;
        await upsertSubscription(
          merchantId,
          sub.customer as string,
          "free",
          "canceled",
          sub.id,
          null,
        );
        console.info(`[stripe webhook] subscription canceled: merchant=${merchantId}`);
        break;
      }

      case "invoice.payment_failed": {
        const invoice = event.data.object as Stripe.Invoice;
        const customerId =
          typeof invoice.customer === "string" ? invoice.customer : invoice.customer?.id ?? "";
        const merchantId = await getMerchantIdByCustomer(customerId);
        if (!merchantId) break;
        await query(
          "UPDATE subscriptions SET status = 'past_due', updated_at = NOW() WHERE merchant_id = $1",
          [merchantId],
        );
        console.warn(`[stripe webhook] payment failed: merchant=${merchantId}`);
        break;
      }

      default:
        // Unhandled event type — acknowledge and ignore
        break;
    }
  } catch (err) {
    console.error("[stripe webhook] handler error:", err);
    return json({ error: "Internal error" }, { status: 500 });
  }

  return json({ received: true });
};
