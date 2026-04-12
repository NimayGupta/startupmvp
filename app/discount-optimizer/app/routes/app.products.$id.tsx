import { useState } from "react";
import type { ActionFunctionArgs, LoaderFunctionArgs } from "@remix-run/node";
import { json } from "@remix-run/node";
import { Form, useActionData, useLoaderData, useNavigation } from "@remix-run/react";
import {
  Badge,
  Banner,
  BlockStack,
  Button,
  Card,
  Divider,
  InlineStack,
  Layout,
  Page,
  Select,
  SkeletonBodyText,
  Text,
  TextField,
} from "@shopify/polaris";
import { TitleBar } from "@shopify/app-bridge-react";
import { query } from "../lib/db.server";
import {
  buildVariantFeatureMap,
  fetchMerchantFeatures,
  type FeatureVector,
} from "../lib/engine.server";
import { upsertMerchant } from "../lib/merchant.server";
import {
  approveRecommendation,
  editApproveRecommendation,
  fetchLatestRecommendation,
  generateRecommendation,
  rejectRecommendation,
  type RecommendationRecord,
} from "../lib/recommendations.server";
import { createAutomaticProductDiscount } from "../lib/shopify-discounts.server";
import { authenticate } from "../shopify.server";

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

interface ActionData {
  error?: string;
  success?: string;
}

export const loader = async ({ request, params }: LoaderFunctionArgs) => {
  const { session } = await authenticate.admin(request);

  const merchant = await upsertMerchant(
    session.shop,
    session.accessToken ?? "",
    session.scope ?? "",
  );

  const productId = Number(params.id);
  if (!productId || Number.isNaN(productId)) {
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
  const recommendation = await fetchLatestRecommendation(merchant.id, productId);

  return json({
    product: productRows[0],
    variants: variantRows,
    featuresByVariantId,
    experiments,
    recommendation,
  });
};

export const action = async ({ request, params }: ActionFunctionArgs) => {
  const { admin, session } = await authenticate.admin(request);
  const merchant = await upsertMerchant(
    session.shop,
    session.accessToken ?? "",
    session.scope ?? "",
  );

  const productId = Number(params.id);
  if (!productId || Number.isNaN(productId)) {
    return json<ActionData>({ error: "Invalid product id." }, { status: 400 });
  }

  const form = await request.formData();
  const intent = String(form.get("intent") ?? "");

  try {
    if (intent === "generate") {
      await generateRecommendation(merchant.id, productId);
      return json<ActionData>({ success: "Recommendation generated." });
    }

    const recommendationId = Number(form.get("recommendationId"));
    if (!recommendationId || Number.isNaN(recommendationId)) {
      return json<ActionData>({ error: "Missing recommendation id." }, { status: 400 });
    }

    if (intent === "reject") {
      const reason = String(form.get("reason") ?? "");
      await rejectRecommendation(recommendationId, reason);
      return json<ActionData>({ success: "Recommendation rejected." });
    }

    const rows = await query<{ title: string; shopify_product_id: string }>(
      `SELECT title, shopify_product_id
       FROM products
       WHERE id = $1 AND merchant_id = $2`,
      [productId, merchant.id],
    );
    const product = rows[0];
    if (!product) {
      return json<ActionData>({ error: "Product not found." }, { status: 404 });
    }

    if (intent === "approve") {
      const discountPct = Number(form.get("discountPct"));
      const shopifyDiscountId = await createAutomaticProductDiscount({
        admin,
        productTitle: product.title,
        shopifyProductId: product.shopify_product_id,
        discountPct,
      });
      await approveRecommendation(recommendationId, shopifyDiscountId, discountPct);
      return json<ActionData>({
        success: "Recommendation approved and Shopify discount created.",
      });
    }

    if (intent === "edit-approve") {
      const merchantEditPct = Number(form.get("merchantEditPct"));
      if (Number.isNaN(merchantEditPct) || merchantEditPct < 0) {
        return json<ActionData>(
          { error: "Enter a valid edited discount percentage." },
          { status: 400 },
        );
      }

      const shopifyDiscountId = await createAutomaticProductDiscount({
        admin,
        productTitle: product.title,
        shopifyProductId: product.shopify_product_id,
        discountPct: merchantEditPct,
      });
      await editApproveRecommendation(
        recommendationId,
        merchantEditPct,
        shopifyDiscountId,
      );
      return json<ActionData>({
        success: "Edited discount approved and Shopify discount created.",
      });
    }

    return json<ActionData>({ error: "Unknown action." }, { status: 400 });
  } catch (error) {
    return json<ActionData>(
      {
        error:
          error instanceof Error ? error.message : "Unexpected recommendation error.",
      },
      { status: 500 },
    );
  }
};

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

function recommendationTone(
  status: RecommendationRecord["status"],
): "attention" | "success" | "critical" | "info" {
  if (status === "approved" || status === "edited_and_approved") return "success";
  if (status === "rejected") return "critical";
  return "attention";
}

export default function ProductDetail() {
  const { product, variants, featuresByVariantId, experiments, recommendation } =
    useLoaderData<typeof loader>();
  const actionData = useActionData<typeof action>();
  const navigation = useNavigation();

  const [selectedVariantId, setSelectedVariantId] = useState<number>(
    variants[0]?.id ?? 0,
  );
  const [merchantEditPct, setMerchantEditPct] = useState(
    recommendation
      ? String(
          recommendation.merchant_edit_pct ??
            recommendation.recommended_discount_pct,
        )
      : "",
  );
  const [rejectReason, setRejectReason] = useState("");

  const fv = featuresByVariantId[selectedVariantId] ?? null;
  const selectedVariant = variants.find((variant) => variant.id === selectedVariantId);
  const isSubmitting = navigation.state === "submitting";

  const variantOptions = variants.map((variant) => ({
    label: `${variant.title} - $${variant.price}`,
    value: String(variant.id),
  }));

  return (
    <Page
      title={product.title}
      backAction={{ content: "Products", url: "/app" }}
      subtitle={[product.vendor, product.product_type].filter(Boolean).join(" - ")}
    >
      <TitleBar title={product.title} />
      <Layout>
        {actionData?.error && (
          <Layout.Section>
            <Banner tone="critical" title="Recommendation action failed">
              <p>{actionData.error}</p>
            </Banner>
          </Layout.Section>
        )}
        {actionData?.success && (
          <Layout.Section>
            <Banner tone="success" title="Recommendation updated">
              <p>{actionData.success}</p>
            </Banner>
          </Layout.Section>
        )}

        <Layout.Section>
          <BlockStack gap="400">
            <Card>
              <Select
                label="Variant"
                options={variantOptions}
                value={String(selectedVariantId)}
                onChange={(value) => setSelectedVariantId(Number(value))}
              />
              {selectedVariant && (
                <BlockStack gap="100">
                  <Text as="p" variant="bodySm" tone="subdued">
                    Inventory: {selectedVariant.inventory_quantity} units
                    {selectedVariant.compare_at_price &&
                      ` - Compare at: $${selectedVariant.compare_at_price}`}
                  </Text>
                </BlockStack>
              )}
            </Card>

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
                  <MetricCard label="Tests Run" value={String(fv.tests_run)} />
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
                    {experiments.map((experiment) => (
                      <BlockStack key={experiment.id} gap="100">
                        <InlineStack gap="200" align="space-between">
                          <Text as="p" variant="bodyMd">
                            {experiment.control_discount_pct}% vs{" "}
                            {experiment.treatment_discount_pct}% discount
                          </Text>
                          <Badge
                            tone={
                              experiment.status === "active"
                                ? "success"
                                : experiment.status === "killed"
                                  ? "critical"
                                  : "new"
                            }
                          >
                            {experiment.status}
                          </Badge>
                        </InlineStack>
                        {experiment.conclusion_type && (
                          <Text as="p" variant="bodySm" tone="subdued">
                            Concluded: {experiment.conclusion_type}
                            {experiment.concluded_at
                              ? ` on ${new Date(experiment.concluded_at).toLocaleDateString()}`
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

        <Layout.Section variant="oneThird">
          <BlockStack gap="400">
            <Card>
              <BlockStack gap="300">
                <Text as="h2" variant="headingMd">
                  Recommendation
                </Text>
                {recommendation ? (
                  <BlockStack gap="300">
                    <InlineStack align="space-between">
                      <Badge tone={recommendationTone(recommendation.status)}>
                        {recommendation.status.replaceAll("_", " ")}
                      </Badge>
                      <Text as="p" variant="bodySm" tone="subdued">
                        Confidence {(recommendation.confidence_score * 100).toFixed(0)}%
                      </Text>
                    </InlineStack>
                    <Text as="p" variant="headingLg">
                      {recommendation.merchant_edit_pct ??
                        recommendation.recommended_discount_pct}
                      %
                    </Text>
                    <Text as="p" variant="bodyMd">
                      {recommendation.llm_explanation}
                    </Text>
                    <Text as="p" variant="bodySm" tone="subdued">
                      {recommendation.rationale}
                    </Text>

                    {recommendation.status === "pending" && (
                      <BlockStack gap="300">
                        <Form method="post">
                          <input type="hidden" name="intent" value="approve" />
                          <input
                            type="hidden"
                            name="recommendationId"
                            value={recommendation.id}
                          />
                          <input
                            type="hidden"
                            name="discountPct"
                            value={recommendation.recommended_discount_pct}
                          />
                          <Button variant="primary" submit loading={isSubmitting}>
                            Approve {recommendation.recommended_discount_pct}%
                          </Button>
                        </Form>

                        <Form method="post">
                          <BlockStack gap="200">
                            <input type="hidden" name="intent" value="edit-approve" />
                            <input
                              type="hidden"
                              name="recommendationId"
                              value={recommendation.id}
                            />
                            <TextField
                              label="Edit discount before approving"
                              autoComplete="off"
                              type="number"
                              min={0}
                              max={100}
                              step={0.5}
                              suffix="%"
                              value={merchantEditPct}
                              onChange={setMerchantEditPct}
                              name="merchantEditPct"
                            />
                            <Button submit loading={isSubmitting}>
                              Approve edited discount
                            </Button>
                          </BlockStack>
                        </Form>

                        <Form method="post">
                          <BlockStack gap="200">
                            <input type="hidden" name="intent" value="reject" />
                            <input
                              type="hidden"
                              name="recommendationId"
                              value={recommendation.id}
                            />
                            <TextField
                              label="Reject reason"
                              autoComplete="off"
                              value={rejectReason}
                              onChange={setRejectReason}
                              name="reason"
                            />
                            <Button tone="critical" submit loading={isSubmitting}>
                              Reject recommendation
                            </Button>
                          </BlockStack>
                        </Form>
                      </BlockStack>
                    )}
                  </BlockStack>
                ) : (
                  <>
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
                    <Form method="post">
                      <input type="hidden" name="intent" value="generate" />
                      <Button variant="primary" submit loading={isSubmitting}>
                        Get recommendation
                      </Button>
                    </Form>
                  </>
                )}
                <Text as="p" variant="bodySm" tone="subdued">
                  Recommendations are generated by the Phase 3 rules engine and
                  can be approved, rejected, or edited before approval.
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
