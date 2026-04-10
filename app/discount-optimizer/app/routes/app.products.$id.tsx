import { useState } from "react";
import type { LoaderFunctionArgs } from "@remix-run/node";
import { json } from "@remix-run/node";
import { useLoaderData } from "@remix-run/react";
import {
  Page,
  Layout,
  Card,
  BlockStack,
  InlineStack,
  Text,
  Select,
  Button,
  Badge,
  Divider,
  SkeletonBodyText,
} from "@shopify/polaris";
import { TitleBar } from "@shopify/app-bridge-react";
import { authenticate } from "../shopify.server";
import { upsertMerchant } from "../lib/merchant.server";
import { query } from "../lib/db.server";
import {
  fetchMerchantFeatures,
  buildVariantFeatureMap,
  type FeatureVector,
} from "../lib/engine.server";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ProductDetail {
  id: number;
  title: string;
  shopify_product_id: string;
  product_type: string | null;
  vendor: string | null;
}

interface VariantRow {
  id: number;
  shopify_variant_id: string;
  title: string;
  price: string;
  compare_at_price: string | null;
  inventory_quantity: number;
}

interface ExperimentRow {
  id: number;
  status: string;
  control_discount_pct: string;
  treatment_discount_pct: string;
  started_at: string | null;
  concluded_at: string | null;
  conclusion_type: string | null;
}

// ---------------------------------------------------------------------------
// Loader
// ---------------------------------------------------------------------------

export const loader = async ({ request, params }: LoaderFunctionArgs) => {
  const { session } = await authenticate.admin(request);

  const merchant = await upsertMerchant(
    session.shop,
    session.accessToken ?? "",
    session.scope ?? "",
  );

  const productId = Number(params.id);
  if (!productId || isNaN(productId)) {
    throw new Response("Not Found", { status: 404 });
  }

  const [productRows, variantRows, experiments] = await Promise.all([
    query<ProductDetail>(
      `SELECT id, title, shopify_product_id, product_type, vendor
       FROM products
       WHERE id = $1 AND merchant_id = $2`,
      [productId, merchant.id],
    ),
    query<VariantRow>(
      `SELECT id, shopify_variant_id, title, price::text, compare_at_price::text,
              inventory_quantity
       FROM product_variants
       WHERE product_id = $1
       ORDER BY price ASC`,
      [productId],
    ),
    query<ExperimentRow>(
      `SELECT id, status, control_discount_pct::text, treatment_discount_pct::text,
              started_at, concluded_at, conclusion_type
       FROM experiments
       WHERE product_id = $1
       ORDER BY created_at DESC
       LIMIT 20`,
      [productId],
    ),
  ]);

  if (productRows.length === 0) {
    throw new Response("Not Found", { status: 404 });
  }

  const engineResponse = await fetchMerchantFeatures(merchant.id);
  const featuresByVariantId = buildVariantFeatureMap(
    engineResponse?.features ?? [],
  );

  return json({
    product: productRows[0],
    variants: variantRows,
    featuresByVariantId,
    experiments,
  });
};

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function MetricCard({
  label,
  value,
  subdued = false,
}: {
  label: string;
  value: string;
  subdued?: boolean;
}) {
  return (
    <Card>
      <BlockStack gap="100">
        <Text as="p" variant="bodySm" tone="subdued">
          {label}
        </Text>
        <Text
          as="p"
          variant="headingLg"
          tone={subdued ? "subdued" : undefined}
        >
          {value}
        </Text>
      </BlockStack>
    </Card>
  );
}

function outcomeColor(
  outcome: FeatureVector["last_test_outcome"],
): "success" | "critical" | "warning" | "new" {
  if (outcome === "positive") return "success";
  if (outcome === "negative") return "critical";
  if (outcome === "neutral") return "warning";
  return "new";
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ProductDetail() {
  const { product, variants, featuresByVariantId, experiments } =
    useLoaderData<typeof loader>();

  const [selectedVariantId, setSelectedVariantId] = useState<number>(
    variants[0]?.id ?? 0,
  );

  const fv = featuresByVariantId[selectedVariantId] ?? null;
  const selectedVariant = variants.find((v) => v.id === selectedVariantId);

  const variantOptions = variants.map((v) => ({
    label: `${v.title} — $${v.price}`,
    value: String(v.id),
  }));

  return (
    <Page
      title={product.title}
      backAction={{ content: "Products", url: "/app" }}
      subtitle={[product.vendor, product.product_type].filter(Boolean).join(" · ")}
    >
      <TitleBar title={product.title} />
      <Layout>
        {/* ---------------------------------------------------------------- */}
        {/* Left column: variant selector + metric cards                      */}
        {/* ---------------------------------------------------------------- */}
        <Layout.Section>
          <BlockStack gap="400">
            {/* Variant selector */}
            <Card>
              <Select
                label="Variant"
                options={variantOptions}
                value={String(selectedVariantId)}
                onChange={(val) => setSelectedVariantId(Number(val))}
              />
              {selectedVariant && (
                <BlockStack gap="100">
                  <Text as="p" variant="bodySm" tone="subdued">
                    Inventory: {selectedVariant.inventory_quantity} units
                    {selectedVariant.compare_at_price &&
                      ` · Compare at: $${selectedVariant.compare_at_price}`}
                  </Text>
                </BlockStack>
              )}
            </Card>

            {/* Feature metric cards */}
            {fv ? (
              <BlockStack gap="300">
                <Text as="h2" variant="headingMd">
                  14-Day Metrics
                </Text>
                <InlineStack gap="300" wrap>
                  <MetricCard
                    label="Conversion Rate"
                    value={fv.conversion_rate.toFixed(4)}
                  />
                  <MetricCard
                    label="Revenue / Visitor"
                    value={`$${fv.revenue_per_visitor.toFixed(2)}`}
                  />
                  <MetricCard
                    label="Avg Order Value"
                    value={`$${fv.avg_order_value.toFixed(2)}`}
                  />
                  <MetricCard
                    label="Inventory Days"
                    value={`${fv.inventory_days_supply}d`}
                  />
                  <MetricCard
                    label="Current Discount"
                    value={`${(fv.current_discount_pct * 100).toFixed(1)}%`}
                  />
                  <MetricCard label="Price Tier" value={fv.price_tier} />
                  <MetricCard
                    label="Day-of-Week Bias"
                    value={fv.day_of_week_bias.toFixed(3)}
                  />
                  <MetricCard
                    label="Tests Run"
                    value={String(fv.tests_run)}
                  />
                  <MetricCard
                    label="Last Outcome"
                    value={fv.last_test_outcome}
                  />
                </InlineStack>
              </BlockStack>
            ) : (
              <Card>
                <BlockStack gap="200">
                  <Text as="h2" variant="headingMd">
                    14-Day Metrics
                  </Text>
                  <SkeletonBodyText lines={3} />
                  <Text as="p" variant="bodySm" tone="subdued">
                    Feature data not yet available. Trigger a feature refresh
                    or wait for the next 6-hour cycle.
                  </Text>
                </BlockStack>
              </Card>
            )}

            {/* Experiment history */}
            <Card>
              <BlockStack gap="300">
                <Text as="h2" variant="headingMd">
                  Experiment History
                </Text>
                {experiments.length === 0 ? (
                  <Text as="p" variant="bodyMd" tone="subdued">
                    No experiments yet. Experiments will appear here after
                    Phase 4 is complete.
                  </Text>
                ) : (
                  <BlockStack gap="200">
                    {experiments.map((exp) => (
                      <BlockStack key={exp.id} gap="100">
                        <InlineStack gap="200" align="space-between">
                          <Text as="p" variant="bodyMd">
                            {exp.control_discount_pct}% vs{" "}
                            {exp.treatment_discount_pct}% discount
                          </Text>
                          <Badge
                            tone={
                              exp.status === "active"
                                ? "success"
                                : exp.status === "killed"
                                  ? "critical"
                                  : "new"
                            }
                          >
                            {exp.status}
                          </Badge>
                        </InlineStack>
                        {exp.conclusion_type && (
                          <Text as="p" variant="bodySm" tone="subdued">
                            Concluded: {exp.conclusion_type}
                            {exp.concluded_at
                              ? ` on ${new Date(exp.concluded_at).toLocaleDateString()}`
                              : ""}
                          </Text>
                        )}
                        <Divider />
                      </BlockStack>
                    ))}
                  </BlockStack>
                )}
              </BlockStack>
            </Card>
          </BlockStack>
        </Layout.Section>

        {/* ---------------------------------------------------------------- */}
        {/* Right column: recommendation CTA + last outcome badge            */}
        {/* ---------------------------------------------------------------- */}
        <Layout.Section variant="oneThird">
          <BlockStack gap="400">
            <Card>
              <BlockStack gap="300">
                <Text as="h2" variant="headingMd">
                  Recommendation
                </Text>
                {fv && fv.last_test_outcome !== "none" && (
                  <InlineStack gap="200">
                    <Text as="p" variant="bodySm" tone="subdued">
                      Last test:
                    </Text>
                    <Badge tone={outcomeColor(fv.last_test_outcome)}>
                      {fv.last_test_outcome}
                    </Badge>
                  </InlineStack>
                )}
                <Button disabled>
                  Get recommendation
                </Button>
                <Text as="p" variant="bodySm" tone="subdued">
                  Discount recommendations are available in Phase 3.
                </Text>
              </BlockStack>
            </Card>

            {fv?.has_active_experiment && (
              <Card>
                <BlockStack gap="200">
                  <Badge tone="success">Active experiment</Badge>
                  <Text as="p" variant="bodySm" tone="subdued">
                    An A/B experiment is currently running for this product.
                    Full experiment controls will be available in Phase 4.
                  </Text>
                </BlockStack>
              </Card>
            )}
          </BlockStack>
        </Layout.Section>
      </Layout>
    </Page>
  );
}
