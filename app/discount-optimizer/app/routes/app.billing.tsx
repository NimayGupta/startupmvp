import type { ActionFunctionArgs, LoaderFunctionArgs } from "@remix-run/node";
import { json, redirect } from "@remix-run/node";
import { useFetcher, useLoaderData } from "@remix-run/react";
import {
  Badge,
  Banner,
  BlockStack,
  Box,
  Button,
  Card,
  Divider,
  InlineStack,
  Layout,
  List,
  Page,
  ProgressBar,
  Text,
} from "@shopify/polaris";
import { TitleBar } from "@shopify/app-bridge-react";
import { authenticate } from "../shopify.server";
import { upsertMerchant } from "../lib/merchant.server";
import {
  PLAN_DISPLAY,
  createCheckoutSession,
  createPortalSession,
  getSubscription,
  getUsageMetrics,
  upsertSubscription,
} from "../lib/stripe.server";

// ---------------------------------------------------------------------------
// Loader
// ---------------------------------------------------------------------------

export const loader = async ({ request }: LoaderFunctionArgs) => {
  const { session } = await authenticate.admin(request);
  const merchant = await upsertMerchant(
    session.shop,
    session.accessToken ?? "",
    session.scope ?? "",
  );

  const [sub, usage] = await Promise.all([
    getSubscription(merchant.id),
    getUsageMetrics(merchant.id),
  ]);

  const plan = sub?.plan ?? "free";
  const stripeEnabled = !!process.env.STRIPE_SECRET_KEY;

  return json({
    merchantId: merchant.id,
    shop: session.shop,
    plan,
    status: sub?.status ?? "active",
    currentPeriodEnd: sub?.current_period_end ?? null,
    usage,
    planDisplay: PLAN_DISPLAY,
    stripeEnabled,
  });
};

// ---------------------------------------------------------------------------
// Action
// ---------------------------------------------------------------------------

export const action = async ({ request }: ActionFunctionArgs) => {
  const { session } = await authenticate.admin(request);
  const merchant = await upsertMerchant(
    session.shop,
    session.accessToken ?? "",
    session.scope ?? "",
  );

  const form = await request.formData();
  const intent = form.get("intent") as string;
  const origin = new URL(request.url).origin;

  if (intent === "checkout") {
    const plan = form.get("plan") as "growth" | "pro";
    const url = await createCheckoutSession(
      merchant.id,
      session.shop,
      plan,
      `${origin}/app/billing?success=1`,
      `${origin}/app/billing?canceled=1`,
    );
    return redirect(url);
  }

  if (intent === "portal") {
    const url = await createPortalSession(
      merchant.id,
      `${origin}/app/billing`,
    );
    return redirect(url);
  }

  if (intent === "free") {
    // Downgrade: handled via Stripe Customer Portal; this is a direct fallback
    await upsertSubscription(merchant.id, "cus_placeholder", "free", "active");
    return json({ ok: true });
  }

  return json({ ok: false });
};

// ---------------------------------------------------------------------------
// Component helpers
// ---------------------------------------------------------------------------

function planBadge(plan: string) {
  const tones = { free: "new", growth: "info", pro: "success" } as const;
  type Tone = typeof tones[keyof typeof tones];
  return (
    <Badge tone={(tones[plan as keyof typeof tones] ?? "new") as Tone}>
      {plan.charAt(0).toUpperCase() + plan.slice(1)}
    </Badge>
  );
}

function UsageCard({
  plan,
  usage,
}: {
  plan: string;
  usage: ReturnType<typeof useLoaderData<typeof loader>>["usage"];
}) {
  const limits = { free: { products: 1, experiments: 1 }, growth: { products: 20, experiments: 5 }, pro: { products: Infinity, experiments: Infinity } };
  const lim = limits[plan as keyof typeof limits] ?? limits.free;

  const productPct = lim.products === Infinity ? 0 : Math.min((usage.products_count / lim.products) * 100, 100);
  const expPct = lim.experiments === Infinity ? 0 : Math.min((usage.active_experiments / lim.experiments) * 100, 100);

  return (
    <Card>
      <BlockStack gap="400">
        <Text as="h2" variant="headingMd">This month&apos;s usage</Text>
        <BlockStack gap="300">
          <BlockStack gap="100">
            <InlineStack align="space-between">
              <Text as="p" variant="bodySm">Products synced</Text>
              <Text as="p" variant="bodySm" tone="subdued">
                {usage.products_count}{lim.products !== Infinity ? ` / ${lim.products}` : ""}
              </Text>
            </InlineStack>
            {lim.products !== Infinity && (
              <ProgressBar progress={productPct} tone={productPct >= 90 ? "critical" : "primary"} size="small" />
            )}
          </BlockStack>

          <BlockStack gap="100">
            <InlineStack align="space-between">
              <Text as="p" variant="bodySm">Active experiments</Text>
              <Text as="p" variant="bodySm" tone="subdued">
                {usage.active_experiments}{lim.experiments !== Infinity ? ` / ${lim.experiments}` : ""}
              </Text>
            </InlineStack>
            {lim.experiments !== Infinity && (
              <ProgressBar progress={expPct} tone={expPct >= 90 ? "critical" : "primary"} size="small" />
            )}
          </BlockStack>

          <Divider />

          <InlineStack align="space-between">
            <Text as="p" variant="bodySm">Recommendations generated</Text>
            <Text as="p" variant="bodySm">{usage.recommendations_this_month}</Text>
          </InlineStack>
          <InlineStack align="space-between">
            <Text as="p" variant="bodySm">Approval rate</Text>
            <Text as="p" variant="bodySm">{usage.approval_rate_pct}%</Text>
          </InlineStack>
        </BlockStack>
      </BlockStack>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function BillingPage() {
  const {
    plan,
    status,
    currentPeriodEnd,
    usage,
    planDisplay,
    stripeEnabled,
  } = useLoaderData<typeof loader>();

  const fetcher = useFetcher();
  const url = new URL(typeof window !== "undefined" ? window.location.href : "http://localhost");
  const justSucceeded = url.searchParams.get("success") === "1";
  const justCanceled = url.searchParams.get("canceled") === "1";

  return (
    <Page title="Billing">
      <TitleBar title="Billing & Plans" />
      <Layout>
        <Layout.Section>
          <BlockStack gap="500">
            {justSucceeded && (
              <Banner tone="success" title="Subscription updated">
                Your plan has been updated successfully.
              </Banner>
            )}
            {justCanceled && (
              <Banner tone="warning" title="Checkout canceled">
                No changes were made to your subscription.
              </Banner>
            )}

            {!stripeEnabled && (
              <Banner tone="warning" title="Stripe not configured">
                Set STRIPE_SECRET_KEY in your environment to enable billing.
              </Banner>
            )}

            {/* Current plan */}
            <Card>
              <BlockStack gap="300">
                <InlineStack align="space-between" blockAlign="center">
                  <Text as="h2" variant="headingMd">Current plan</Text>
                  {planBadge(plan)}
                </InlineStack>
                <InlineStack gap="200" blockAlign="center">
                  <Text as="p" variant="bodyLg" fontWeight="semibold">
                    {planDisplay[plan]?.price ?? "$0/month"}
                  </Text>
                  {status === "past_due" && <Badge tone="critical">Past due</Badge>}
                  {status === "trialing" && <Badge tone="info">Trial</Badge>}
                </InlineStack>
                {currentPeriodEnd && (
                  <Text as="p" variant="bodySm" tone="subdued">
                    Renews {new Date(currentPeriodEnd).toLocaleDateString()}
                  </Text>
                )}
                {plan !== "free" && stripeEnabled && (
                  <fetcher.Form method="post">
                    <input type="hidden" name="intent" value="portal" />
                    <Button submit loading={fetcher.state !== "idle"}>
                      Manage subscription
                    </Button>
                  </fetcher.Form>
                )}
              </BlockStack>
            </Card>

            {/* Plan comparison */}
            <InlineStack gap="400" align="start" wrap={false}>
              {(["free", "growth", "pro"] as const).map((p) => {
                const info = planDisplay[p];
                const isCurrent = p === plan;
                const isDowngrade = ["free", "growth", "pro"].indexOf(p) < ["free", "growth", "pro"].indexOf(plan);
                return (
                  <Box key={p} minWidth="200px">
                    <Card>
                      <BlockStack gap="300">
                        <InlineStack align="space-between">
                          <Text as="h3" variant="headingMd">{info.name}</Text>
                          {isCurrent && <Badge tone="success">Current</Badge>}
                        </InlineStack>
                        <Text as="p" variant="bodyLg" fontWeight="semibold">
                          {info.price}
                        </Text>
                        <List>
                          {info.features.map((f) => (
                            <List.Item key={f}>{f}</List.Item>
                          ))}
                        </List>
                        {!isCurrent && !isDowngrade && stripeEnabled && p !== "free" && (
                          <fetcher.Form method="post">
                            <input type="hidden" name="intent" value="checkout" />
                            <input type="hidden" name="plan" value={p} />
                            <Button
                              variant="primary"
                              submit
                              fullWidth
                              loading={
                                fetcher.state !== "idle" &&
                                fetcher.formData?.get("plan") === p
                              }
                            >
                              Upgrade to {info.name}
                            </Button>
                          </fetcher.Form>
                        )}
                        {!isCurrent && isDowngrade && stripeEnabled && (
                          <fetcher.Form method="post">
                            <input type="hidden" name="intent" value="portal" />
                            <Button submit fullWidth variant="plain">
                              Downgrade via portal
                            </Button>
                          </fetcher.Form>
                        )}
                      </BlockStack>
                    </Card>
                  </Box>
                );
              })}
            </InlineStack>
          </BlockStack>
        </Layout.Section>

        <Layout.Section variant="oneThird">
          <UsageCard plan={plan} usage={usage} />
        </Layout.Section>
      </Layout>
    </Page>
  );
}
