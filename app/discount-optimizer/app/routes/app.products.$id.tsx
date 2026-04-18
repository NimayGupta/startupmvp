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
  ProgressBar,
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
import {
  createExperiment,
  getTrustScore,
  killExperiment,
  type ExperimentStats,
  type TrustScore,
} from "../lib/experiments.server";
import { createAutomaticProductDiscount } from "../lib/shopify-discounts.server";
import { authenticate } from "../shopify.server";

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
  latest_stats: ExperimentStats | null;
  recommendation_id: number | null;
}

interface ActionData {
  error?: string;
  success?: string;
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
              started_at, concluded_at, conclusion_type,
              latest_stats, recommendation_id
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
  const [recommendation, trustScore] = await Promise.all([
    fetchLatestRecommendation(merchant.id, productId),
    getTrustScore(merchant.id, productId),
  ]);

  return json({
    merchantId: merchant.id,
    autoApproveEnabled: merchant.auto_approve_enabled ?? false,
    product: productRows[0],
    variants: variantRows,
    featuresByVariantId,
    experiments,
    recommendation,
    trustScore,
  });
};

// ---------------------------------------------------------------------------
// Action
// ---------------------------------------------------------------------------

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
    // ---- Generate recommendation ----
    if (intent === "generate") {
      await generateRecommendation(merchant.id, productId);
      return json<ActionData>({ success: "Recommendation generated." });
    }

    // ---- Kill experiment ----
    if (intent === "kill-experiment") {
      const experimentId = Number(form.get("experimentId"));
      if (!experimentId) return json<ActionData>({ error: "Missing experiment id." }, { status: 400 });
      const result = await killExperiment(experimentId, merchant.id);
      if (!result) return json<ActionData>({ error: "Could not kill experiment." }, { status: 500 });
      return json<ActionData>({ success: "Experiment stopped." });
    }

    // ---- Create experiment (from approved recommendation) ----
    if (intent === "create-experiment") {
      const recommendationId = Number(form.get("recommendationId"));
      const treatmentDiscountPct = Number(form.get("treatmentDiscountPct"));
      if (!recommendationId || Number.isNaN(treatmentDiscountPct)) {
        return json<ActionData>({ error: "Missing experiment parameters." }, { status: 400 });
      }

      const rows = await query<{ title: string; shopify_product_id: string }>(
        `SELECT title, shopify_product_id FROM products WHERE id = $1 AND merchant_id = $2`,
        [productId, merchant.id],
      );
      if (!rows[0]) return json<ActionData>({ error: "Product not found." }, { status: 404 });

      const shopifyDiscountId = await createAutomaticProductDiscount({
        admin,
        productTitle: rows[0].title,
        shopifyProductId: rows[0].shopify_product_id,
        discountPct: treatmentDiscountPct,
      });

      const exp = await createExperiment({
        merchantId: merchant.id,
        productId,
        recommendationId,
        controlDiscountPct: 0,
        treatmentDiscountPct,
        shopifyDiscountId,
      });
      if (!exp) return json<ActionData>({ error: "Failed to create experiment." }, { status: 500 });
      return json<ActionData>({ success: "A/B experiment started. Traffic will be split 50/50." });
    }

    // ---- Recommendation actions ----
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
      `SELECT title, shopify_product_id FROM products WHERE id = $1 AND merchant_id = $2`,
      [productId, merchant.id],
    );
    const product = rows[0];
    if (!product) return json<ActionData>({ error: "Product not found." }, { status: 404 });

    if (intent === "approve") {
      const discountPct = Number(form.get("discountPct"));
      const shopifyDiscountId = await createAutomaticProductDiscount({
        admin,
        productTitle: product.title,
        shopifyProductId: product.shopify_product_id,
        discountPct,
      });
      await approveRecommendation(recommendationId, shopifyDiscountId, discountPct);
      return json<ActionData>({ success: "Recommendation approved and Shopify discount created." });
    }

    if (intent === "edit-approve") {
      const merchantEditPct = Number(form.get("merchantEditPct"));
      if (Number.isNaN(merchantEditPct) || merchantEditPct < 0) {
        return json<ActionData>({ error: "Enter a valid edited discount percentage." }, { status: 400 });
      }
      const shopifyDiscountId = await createAutomaticProductDiscount({
        admin,
        productTitle: product.title,
        shopifyProductId: product.shopify_product_id,
        discountPct: merchantEditPct,
      });
      await editApproveRecommendation(recommendationId, merchantEditPct, shopifyDiscountId);
      return json<ActionData>({ success: "Edited discount approved and Shopify discount created." });
    }

    return json<ActionData>({ error: "Unknown action." }, { status: 400 });
  } catch (error) {
    return json<ActionData>(
      { error: error instanceof Error ? error.message : "Unexpected error." },
      { status: 500 },
    );
  }
};

// ---------------------------------------------------------------------------
// Helper components
// ---------------------------------------------------------------------------

function MetricCard({ label, value, subdued = false }: { label: string; value: string; subdued?: boolean }) {
  return (
    <Card>
      <BlockStack gap="100">
        <Text as="p" variant="bodySm" tone="subdued">{label}</Text>
        <Text as="p" variant="headingLg" tone={subdued ? "subdued" : undefined}>{value}</Text>
      </BlockStack>
    </Card>
  );
}

function ExperimentStatusBadge({ status }: { status: string }) {
  const tone =
    status === "active" ? "success" :
    status === "killed" ? "critical" :
    status === "concluded" ? "attention" : "new";
  return <Badge tone={tone}>{status.replace(/_/g, " ")}</Badge>;
}

function ActiveExperimentCard({
  experiment,
  isSubmitting,
}: {
  experiment: ExperimentRow;
  isSubmitting: boolean;
}) {
  const stats = experiment.latest_stats;
  const prob = stats ? Math.round(stats.prob_treatment_better * 100) : null;
  const lift = stats ? stats.treatment_rpv - stats.control_rpv : null;
  const liftPct = stats && stats.control_rpv > 0
    ? ((lift! / stats.control_rpv) * 100).toFixed(1)
    : null;

  const confidenceLabel =
    prob === null ? "Awaiting first monitoring cycle…" :
    prob >= 95 ? `The system is ${prob}% confident the discount is significantly improving revenue per visitor.` :
    prob <= 5 ? `The system is ${100 - prob}% confident the discount is hurting revenue per visitor.` :
    `The system is ${prob}% confident the discount is improving revenue per visitor.`;

  return (
    <Card>
      <BlockStack gap="300">
        <InlineStack align="space-between">
          <Text as="h2" variant="headingMd">Active A/B Experiment</Text>
          <Badge tone="success">Running</Badge>
        </InlineStack>

        <Text as="p" variant="bodySm" tone="subdued">
          {experiment.control_discount_pct}% control vs{" "}
          {experiment.treatment_discount_pct}% treatment ·{" "}
          {stats ? `Day ${stats.days_running}` : "just started"}
        </Text>

        {stats ? (
          <BlockStack gap="300">
            <BlockStack gap="100">
              <Text as="p" variant="bodySm" tone="subdued">
                P(treatment better than control)
              </Text>
              <InlineStack gap="200" blockAlign="center">
                <div style={{ flex: 1 }}>
                  <ProgressBar
                    progress={stats.prob_treatment_better * 100}
                    tone={
                      stats.prob_treatment_better >= 0.95 ? "success" :
                      stats.prob_treatment_better <= 0.05 ? "critical" : "highlight"
                    }
                    size="small"
                  />
                </div>
                <Text as="p" variant="bodyMd">
                  {Math.round(stats.prob_treatment_better * 100)}%
                </Text>
              </InlineStack>
              <Text as="p" variant="bodySm" tone="subdued">{confidenceLabel}</Text>
            </BlockStack>

            <Divider />

            <InlineStack gap="400">
              <BlockStack gap="100">
                <Text as="p" variant="bodySm" tone="subdued">Control RPV</Text>
                <Text as="p" variant="bodyMd">${stats.control_rpv.toFixed(2)}/day</Text>
                <Text as="p" variant="bodySm" tone="subdued">{stats.control_n} orders</Text>
              </BlockStack>
              <BlockStack gap="100">
                <Text as="p" variant="bodySm" tone="subdued">Treatment RPV</Text>
                <Text
                  as="p"
                  variant="bodyMd"
                  tone={lift !== null && lift > 0 ? "success" : lift !== null && lift < 0 ? "critical" : undefined}
                >
                  ${stats.treatment_rpv.toFixed(2)}/day
                  {liftPct && ` (${lift! > 0 ? "+" : ""}${liftPct}%)`}
                </Text>
                <Text as="p" variant="bodySm" tone="subdued">{stats.treatment_n} orders</Text>
              </BlockStack>
            </InlineStack>
          </BlockStack>
        ) : (
          <SkeletonBodyText lines={3} />
        )}

        <Form method="post">
          <input type="hidden" name="intent" value="kill-experiment" />
          <input type="hidden" name="experimentId" value={experiment.id} />
          <Button tone="critical" submit loading={isSubmitting}>
            Kill experiment
          </Button>
        </Form>
      </BlockStack>
    </Card>
  );
}

function ConcludedExperimentCard({ experiment }: { experiment: ExperimentRow }) {
  const stats = experiment.latest_stats;
  if (!stats) return null;

  const winner =
    experiment.conclusion_type === "kill_switch" ? "Control (discount removed)" :
    stats.prob_treatment_better >= 0.95 ? "Treatment (discount kept)" :
    stats.prob_treatment_better <= 0.05 ? "Control (discount removed)" : "Inconclusive";

  const lift = stats.treatment_rpv - stats.control_rpv;
  const liftPct = stats.control_rpv > 0
    ? ((lift / stats.control_rpv) * 100).toFixed(1)
    : "N/A";

  return (
    <Card>
      <BlockStack gap="300">
        <InlineStack align="space-between">
          <Text as="h2" variant="headingMd">Experiment Results</Text>
          <Badge tone={experiment.conclusion_type === "kill_switch" ? "critical" : "success"}>
            {experiment.conclusion_type?.replace(/_/g, " ") ?? "concluded"}
          </Badge>
        </InlineStack>

        <BlockStack gap="200">
          <InlineStack gap="200">
            <Text as="p" variant="bodySm" tone="subdued">Winner:</Text>
            <Text as="p" variant="bodyMd">{winner}</Text>
          </InlineStack>
          <InlineStack gap="200">
            <Text as="p" variant="bodySm" tone="subdued">RPV lift:</Text>
            <Text as="p" variant="bodyMd" tone={lift > 0 ? "success" : "critical"}>
              {lift > 0 ? "+" : ""}{liftPct}%
            </Text>
          </InlineStack>
          <InlineStack gap="200">
            <Text as="p" variant="bodySm" tone="subdued">Confidence:</Text>
            <Text as="p" variant="bodyMd">
              {Math.round(stats.prob_treatment_better * 100)}% P(treatment better)
            </Text>
          </InlineStack>
          <InlineStack gap="200">
            <Text as="p" variant="bodySm" tone="subdued">Duration:</Text>
            <Text as="p" variant="bodyMd">{stats.days_running} days</Text>
          </InlineStack>
        </BlockStack>
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

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

export default function ProductDetail() {
  const { merchantId, autoApproveEnabled, product, variants, featuresByVariantId, experiments, recommendation, trustScore } =
    useLoaderData<typeof loader>();
  const actionData = useActionData<typeof action>();
  const navigation = useNavigation();

  const [selectedVariantId, setSelectedVariantId] = useState<number>(variants[0]?.id ?? 0);
  const [merchantEditPct, setMerchantEditPct] = useState(
    recommendation
      ? String(recommendation.merchant_edit_pct ?? recommendation.recommended_discount_pct)
      : "",
  );
  const [rejectReason, setRejectReason] = useState("");

  const fv = featuresByVariantId[selectedVariantId] ?? null;
  const selectedVariant = variants.find((v) => v.id === selectedVariantId);
  const isSubmitting = navigation.state === "submitting";

  const activeExperiment = experiments.find((e) => e.status === "active") ?? null;
  const latestConcluded = experiments.find(
    (e) => e.status === "concluded" || e.status === "killed",
  ) ?? null;

  const canCreateExperiment =
    recommendation &&
    (recommendation.status === "approved" || recommendation.status === "edited_and_approved") &&
    !activeExperiment;

  const treatmentDiscountPct =
    recommendation?.merchant_edit_pct ?? recommendation?.recommended_discount_pct ?? 0;

  const variantOptions = variants.map((v) => ({
    label: `${v.title} - $${v.price}`,
    value: String(v.id),
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
            <Banner tone="critical" title="Action failed"><p>{actionData.error}</p></Banner>
          </Layout.Section>
        )}
        {actionData?.success && (
          <Layout.Section>
            <Banner tone="success" title="Done"><p>{actionData.success}</p></Banner>
          </Layout.Section>
        )}

        {/* ---- Main column ---- */}
        <Layout.Section>
          <BlockStack gap="400">
            {/* Variant selector */}
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
                      ` · Compare at: $${selectedVariant.compare_at_price}`}
                  </Text>
                </BlockStack>
              )}
            </Card>

            {/* 14-day metrics */}
            {fv ? (
              <BlockStack gap="300">
                <Text as="h2" variant="headingMd">14-Day Metrics</Text>
                <InlineStack gap="300" wrap>
                  <MetricCard label="Conversion Rate" value={fv.conversion_rate.toFixed(4)} />
                  <MetricCard label="Revenue / Visitor" value={`$${fv.revenue_per_visitor.toFixed(2)}`} />
                  <MetricCard label="Avg Order Value" value={`$${fv.avg_order_value.toFixed(2)}`} />
                  <MetricCard label="Inventory Days" value={`${fv.inventory_days_supply}d`} />
                  <MetricCard label="Current Discount" value={`${(fv.current_discount_pct * 100).toFixed(1)}%`} />
                  <MetricCard label="Price Tier" value={fv.price_tier} />
                  <MetricCard label="Day-of-Week Bias" value={fv.day_of_week_bias.toFixed(3)} />
                  <MetricCard label="Tests Run" value={String(fv.tests_run)} />
                  <MetricCard label="Last Outcome" value={fv.last_test_outcome} />
                </InlineStack>
              </BlockStack>
            ) : (
              <Card>
                <BlockStack gap="200">
                  <Text as="h2" variant="headingMd">14-Day Metrics</Text>
                  <SkeletonBodyText lines={3} />
                  <Text as="p" variant="bodySm" tone="subdued">
                    Feature data not yet available. Trigger a feature refresh or wait for the next 6-hour cycle.
                  </Text>
                </BlockStack>
              </Card>
            )}

            {/* Experiment history */}
            <Card>
              <BlockStack gap="300">
                <Text as="h2" variant="headingMd">Experiment History</Text>
                {experiments.length === 0 ? (
                  <Text as="p" variant="bodyMd" tone="subdued">
                    No experiments yet. Approve a recommendation, then click "Start A/B experiment".
                  </Text>
                ) : (
                  <BlockStack gap="200">
                    {experiments.map((exp) => (
                      <BlockStack key={exp.id} gap="100">
                        <InlineStack gap="200" align="space-between">
                          <Text as="p" variant="bodyMd">
                            {exp.control_discount_pct}% vs {exp.treatment_discount_pct}% discount
                          </Text>
                          <ExperimentStatusBadge status={exp.status} />
                        </InlineStack>
                        {exp.latest_stats && (
                          <Text as="p" variant="bodySm" tone="subdued">
                            P(treatment better): {Math.round(exp.latest_stats.prob_treatment_better * 100)}% ·
                            RPV lift: {exp.latest_stats.control_rpv > 0
                              ? `${(((exp.latest_stats.treatment_rpv - exp.latest_stats.control_rpv) / exp.latest_stats.control_rpv) * 100).toFixed(1)}%`
                              : "N/A"}
                          </Text>
                        )}
                        {exp.conclusion_type && (
                          <Text as="p" variant="bodySm" tone="subdued">
                            Concluded: {exp.conclusion_type.replace(/_/g, " ")}
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

        {/* ---- Sidebar ---- */}
        <Layout.Section variant="oneThird">
          <BlockStack gap="400">
            {/* Active experiment live card */}
            {activeExperiment && (
              <ActiveExperimentCard
                experiment={activeExperiment}
                isSubmitting={isSubmitting}
              />
            )}

            {/* Concluded experiment results */}
            {!activeExperiment && latestConcluded && (
              <ConcludedExperimentCard experiment={latestConcluded} />
            )}

            {/* Recommendation card */}
            <Card>
              <BlockStack gap="300">
                <Text as="h2" variant="headingMd">Recommendation</Text>
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
                      {recommendation.merchant_edit_pct ?? recommendation.recommended_discount_pct}%
                    </Text>
                    <Text as="p" variant="bodyMd">{recommendation.llm_explanation}</Text>
                    <Text as="p" variant="bodySm" tone="subdued">{recommendation.rationale}</Text>

                    {recommendation.status === "pending" && (
                      <BlockStack gap="300">
                        <Form method="post">
                          <input type="hidden" name="intent" value="approve" />
                          <input type="hidden" name="recommendationId" value={recommendation.id} />
                          <input type="hidden" name="discountPct" value={recommendation.recommended_discount_pct} />
                          <Button variant="primary" submit loading={isSubmitting}>
                            {`Approve ${recommendation.recommended_discount_pct}%`}
                          </Button>
                        </Form>
                        <Form method="post">
                          <BlockStack gap="200">
                            <input type="hidden" name="intent" value="edit-approve" />
                            <input type="hidden" name="recommendationId" value={recommendation.id} />
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
                            <Button submit loading={isSubmitting}>Approve edited discount</Button>
                          </BlockStack>
                        </Form>
                        <Form method="post">
                          <BlockStack gap="200">
                            <input type="hidden" name="intent" value="reject" />
                            <input type="hidden" name="recommendationId" value={recommendation.id} />
                            <TextField
                              label="Reject reason"
                              autoComplete="off"
                              value={rejectReason}
                              onChange={setRejectReason}
                              name="reason"
                            />
                            <Button tone="critical" submit loading={isSubmitting}>Reject</Button>
                          </BlockStack>
                        </Form>
                      </BlockStack>
                    )}
                  </BlockStack>
                ) : (
                  <>
                    {fv && fv.last_test_outcome !== "none" && (
                      <InlineStack gap="200">
                        <Text as="p" variant="bodySm" tone="subdued">Last test:</Text>
                        <Badge tone={outcomeColor(fv.last_test_outcome)}>{fv.last_test_outcome}</Badge>
                      </InlineStack>
                    )}
                    <Form method="post">
                      <input type="hidden" name="intent" value="generate" />
                      <Button variant="primary" submit loading={isSubmitting} disabled={!!activeExperiment}>
                        Get recommendation
                      </Button>
                    </Form>
                    {activeExperiment && (
                      <Text as="p" variant="bodySm" tone="subdued">
                        Recommendations are locked while an experiment is running.
                      </Text>
                    )}
                  </>
                )}
                <Text as="p" variant="bodySm" tone="subdued">
                  Recommendations are generated by the rules engine and can be approved,
                  rejected, or edited before approval.
                </Text>
              </BlockStack>
            </Card>

            {/* Create experiment CTA */}
            {/* Trust score card (Phase 5E) */}
            <TrustScoreCard
              trustScore={trustScore}
              autoApproveEnabled={autoApproveEnabled}
              isAutoApproveEligible={
                !!(recommendation?.feature_snapshot as Record<string, unknown> | undefined)
                  ?.auto_approve_eligible
              }
            />

            {canCreateExperiment && (
              <Card>
                <BlockStack gap="300">
                  <Text as="h2" variant="headingMd">Start A/B Experiment</Text>
                  <Text as="p" variant="bodyMd">
                    Run a controlled 50/50 split: control (no discount) vs treatment (
                    {treatmentDiscountPct}% off). Bayesian monitoring will auto-stop
                    the experiment when significance is reached or after 30 days.
                  </Text>
                  <Form method="post">
                    <input type="hidden" name="intent" value="create-experiment" />
                    <input type="hidden" name="recommendationId" value={recommendation!.id} />
                    <input type="hidden" name="treatmentDiscountPct" value={treatmentDiscountPct} />
                    <Button variant="primary" submit loading={isSubmitting}>
                      Start A/B experiment
                    </Button>
                  </Form>
                </BlockStack>
              </Card>
            )}
          </BlockStack>
        </Layout.Section>
      </Layout>
    </Page>
  );
}

// ---------------------------------------------------------------------------
// Phase 5E — Trust score sidebar card
// ---------------------------------------------------------------------------

function TrustScoreCard({
  trustScore,
  autoApproveEnabled,
  isAutoApproveEligible,
}: {
  trustScore: TrustScore;
  autoApproveEnabled: boolean;
  isAutoApproveEligible: boolean;
}) {
  const pct = Math.round(trustScore.trust_score * 100);
  const scoreTone =
    trustScore.auto_approve_eligible
      ? ("success" as const)
      : pct >= 40
        ? ("warning" as const)
        : ("critical" as const);

  return (
    <Card>
      <BlockStack gap="300">
        <InlineStack align="space-between">
          <Text as="h2" variant="headingMd">Trust Score</Text>
          <Badge tone={scoreTone}>{`${pct}%`}</Badge>
        </InlineStack>

        <ProgressBar progress={pct} size="small" tone={scoreTone === "success" ? "success" : "critical"} />

        <InlineStack gap="400">
          <Text as="p" variant="bodySm" tone="subdued">
            {trustScore.tests_completed} test{trustScore.tests_completed !== 1 ? "s" : ""} completed
          </Text>
          <Text as="p" variant="bodySm" tone="subdued">
            {trustScore.tests_positive} positive
          </Text>
        </InlineStack>

        {trustScore.auto_approve_eligible ? (
          <BlockStack gap="200">
            <Text as="p" variant="bodySm" tone="success">
              Auto-approve eligible
            </Text>
            {isAutoApproveEligible && autoApproveEnabled ? (
              <Banner tone="info">
                This recommendation meets all auto-approve criteria. It will be
                applied automatically when you enable auto-approve in settings.
              </Banner>
            ) : !autoApproveEnabled ? (
              <Text as="p" variant="bodySm" tone="subdued">
                Enable auto-approve in Settings to apply recommendations
                automatically for this product.
              </Text>
            ) : null}
          </BlockStack>
        ) : (
          <Text as="p" variant="bodySm" tone="subdued">
            {trustScore.tests_needed > 0
              ? `Needs ${trustScore.tests_needed} more successful test${trustScore.tests_needed !== 1 ? "s" : ""} to unlock auto-approve`
              : "Run at least 3 experiments to build a trust score."}
          </Text>
        )}
      </BlockStack>
    </Card>
  );
}
