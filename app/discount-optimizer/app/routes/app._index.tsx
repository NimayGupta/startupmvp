import type { ActionFunctionArgs, LoaderFunctionArgs } from "@remix-run/node";
import { json } from "@remix-run/node";
import {
  useFetcher,
  useLoaderData,
  useNavigation,
  useRevalidator,
} from "@remix-run/react";
import {
  Badge,
  Banner,
  BlockStack,
  Box,
  Button,
  Card,
  Collapsible,
  DataTable,
  Divider,
  EmptyState,
  InlineStack,
  Layout,
  Page,
  ProgressBar,
  SkeletonBodyText,
  SkeletonDisplayText,
  Text,
} from "@shopify/polaris";
import { TitleBar } from "@shopify/app-bridge-react";
import { useEffect, useState } from "react";
import { authenticate } from "../shopify.server";
import { upsertMerchant } from "../lib/merchant.server";
import { query } from "../lib/db.server";
import {
  fetchMerchantFeatures,
  buildProductFeatureMap,
  type FeatureVector,
} from "../lib/engine.server";
import {
  getTrustScore,
  killExperiment,
  type ExperimentRecord,
  type TrustScore,
} from "../lib/experiments.server";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const ENGINE_URL = process.env.ENGINE_URL ?? "http://localhost:8000";
const INTERNAL_API_KEY = process.env.INTERNAL_API_KEY ?? "";

const engineHeaders = () => ({
  "Content-Type": "application/json",
  Authorization: `Bearer ${INTERNAL_API_KEY}`,
});

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ProductRow {
  id: number;
  shopify_product_id: string;
  title: string;
  min_price: string;
  has_active_experiment: boolean;
}

interface RecommendationRow {
  id: number;
  product_id: number;
  recommended_discount_pct: string;
  confidence_score: string;
  status: string;
  rationale: string | null;
  llm_explanation: string | null;
  model_version: string;
  feature_snapshot: Record<string, unknown> | null;
}

// ---------------------------------------------------------------------------
// Engine helpers (server-side only)
// ---------------------------------------------------------------------------

async function generateRec(productId: number, merchantId: number): Promise<RecommendationRow | null> {
  try {
    const res = await fetch(`${ENGINE_URL}/recommendations/generate`, {
      method: "POST",
      headers: engineHeaders(),
      body: JSON.stringify({ merchant_id: merchantId, product_id: productId }),
      signal: AbortSignal.timeout(15_000),
    });
    if (!res.ok) return null;
    return (await res.json()) as RecommendationRow;
  } catch {
    return null;
  }
}

async function approveRec(recId: number, discountPct: number): Promise<boolean> {
  try {
    const res = await fetch(`${ENGINE_URL}/recommendations/${recId}/approve`, {
      method: "POST",
      headers: engineHeaders(),
      body: JSON.stringify({
        shopify_discount_id: `demo-discount-${recId}`,
        applied_discount_pct: discountPct,
      }),
      signal: AbortSignal.timeout(10_000),
    });
    return res.ok;
  } catch {
    return false;
  }
}

async function rejectRec(recId: number): Promise<boolean> {
  try {
    const res = await fetch(`${ENGINE_URL}/recommendations/${recId}/reject`, {
      method: "POST",
      headers: engineHeaders(),
      body: JSON.stringify({ reason: "merchant_rejected" }),
      signal: AbortSignal.timeout(10_000),
    });
    return res.ok;
  } catch {
    return false;
  }
}

async function fetchExperiments(merchantId: number): Promise<(ExperimentRecord & { product_title: string })[]> {
  try {
    return await query<ExperimentRecord & { product_title: string }>(
      `SELECT e.id, e.merchant_id, e.product_id, e.recommendation_id,
              e.status, e.control_discount_pct::float, e.treatment_discount_pct::float,
              e.shopify_discount_id, e.started_at, e.concluded_at,
              e.conclusion_type, e.latest_stats, e.created_at,
              p.title AS product_title
       FROM experiments e
       JOIN products p ON p.id = e.product_id
       WHERE e.merchant_id = $1
       ORDER BY e.created_at DESC
       LIMIT 20`,
      [merchantId],
    );
  } catch {
    return [];
  }
}

async function seedDemoData(merchantId: number): Promise<{ ok: boolean; message: string }> {
  try {
    const res = await fetch(`${ENGINE_URL}/features/${merchantId}`, {
      headers: engineHeaders(),
      signal: AbortSignal.timeout(15_000),
    });
    if (!res.ok) return { ok: false, message: `Feature refresh failed: ${res.status}` };
    const data = await res.json() as { features: unknown[] };
    return {
      ok: true,
      message: `Demo ready — ${data.features?.length ?? 0} product(s) loaded`,
    };
  } catch (e) {
    return { ok: false, message: String(e) };
  }
}

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

  const [products, engineResponse, experiments, trustScore] = await Promise.all([
    query<ProductRow>(
      `SELECT p.id, p.shopify_product_id, p.title,
              MIN(pv.price)::text AS min_price,
              EXISTS(
                SELECT 1 FROM experiments e
                WHERE e.product_id = p.id AND e.status = 'active'
              ) AS has_active_experiment
       FROM products p
       JOIN product_variants pv ON pv.product_id = p.id
       WHERE p.merchant_id = $1 AND p.status = 'active'
       GROUP BY p.id
       ORDER BY p.title`,
      [merchant.id],
    ),
    fetchMerchantFeatures(merchant.id),
    fetchExperiments(merchant.id),
    getTrustScore(merchant.id, 1),
  ]);

  const recommendations =
    products.length > 0
      ? await query<RecommendationRow>(
          `SELECT DISTINCT ON (product_id)
                  id, product_id, recommended_discount_pct::text,
                  confidence_score::text, status, rationale, llm_explanation,
                  model_version, feature_snapshot
           FROM recommendations
           WHERE merchant_id = $1
             AND status IN ('pending','approved','rejected','edited_and_approved')
           ORDER BY product_id, id DESC`,
          [merchant.id],
        )
      : [];

  const featuresByProductId = buildProductFeatureMap(engineResponse?.features ?? []);
  const recByProductId: Record<number, RecommendationRow> = {};
  for (const r of recommendations) recByProductId[r.product_id] = r;

  return json({
    merchantId: merchant.id,
    products,
    featuresByProductId,
    recByProductId,
    experiments,
    trustScore,
    hasProducts: products.length > 0,
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

  if (intent === "generate") {
    const productId = Number(form.get("productId"));
    const rec = await generateRec(productId, merchant.id);
    return json({ intent, ok: !!rec, rec });
  }

  if (intent === "approve") {
    const recId = Number(form.get("recId"));
    const discountPct = Number(form.get("discountPct"));
    const ok = await approveRec(recId, discountPct);
    return json({ intent, ok });
  }

  if (intent === "reject") {
    const recId = Number(form.get("recId"));
    const ok = await rejectRec(recId);
    return json({ intent, ok });
  }

  if (intent === "kill") {
    const experimentId = Number(form.get("experimentId"));
    const result = await killExperiment(experimentId, merchant.id);
    return json({ intent, ok: !!result });
  }

  if (intent === "seed") {
    const result = await seedDemoData(merchant.id);
    return json({ intent, ...result });
  }

  return json({ intent, ok: false });
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtPct(val: number | string) {
  const n = typeof val === "string" ? parseFloat(val) : val;
  return `${(n * 100).toFixed(1)}%`;
}

function fmtDiscountPct(val: number | string) {
  const n = typeof val === "string" ? parseFloat(val) : val;
  return `${n.toFixed(1)}%`;
}

function fmtConfidence(val: number | string) {
  const n = typeof val === "string" ? parseFloat(val) : val;
  return `${(n * 100).toFixed(0)}%`;
}

function statusBadge(status: string, hasActiveExperiment: boolean): React.ReactNode {
  if (hasActiveExperiment) return <Badge tone="success">Active Experiment</Badge>;
  const tones: Record<string, "new" | "info" | "success" | "attention" | "critical" | "warning"> = {
    pending: "attention",
    approved: "success",
    edited_and_approved: "success",
    rejected: "critical",
  };
  const labels: Record<string, string> = {
    pending: "Pending Review",
    approved: "Approved",
    edited_and_approved: "Approved (edited)",
    rejected: "Rejected",
  };
  return (
    <Badge tone={tones[status] ?? "new"}>
      {labels[status] ?? "No recommendation"}
    </Badge>
  );
}

// ---------------------------------------------------------------------------
// TrustScoreCard (P4)
// ---------------------------------------------------------------------------

function TrustScoreCard({ trust }: { trust: TrustScore }) {
  const pct = Math.round(trust.trust_score * 100);
  return (
    <Card>
      <BlockStack gap="300">
        <Text as="h2" variant="headingMd">Trust Score</Text>
        <BlockStack gap="100">
          <InlineStack align="space-between">
            <Text as="p" variant="bodyMd" fontWeight="semibold">{pct}%</Text>
            <Text as="p" variant="bodySm" tone="subdued">
              {trust.tests_completed} test{trust.tests_completed !== 1 ? "s" : ""} completed
            </Text>
          </InlineStack>
          <ProgressBar
            progress={pct}
            tone={pct >= 70 ? "success" : pct >= 40 ? "highlight" : "critical"}
            size="small"
          />
        </BlockStack>
        {trust.auto_approve_eligible ? (
          <Badge tone="success">Auto-approve eligible</Badge>
        ) : (
          <Text as="p" variant="bodySm" tone="subdued">
            {trust.tests_needed} more positive {trust.tests_needed === 1 ? "test" : "tests"} needed for auto-approve
          </Text>
        )}
      </BlockStack>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// ExperimentPanel (P3)
// ---------------------------------------------------------------------------

function ExperimentPanel({
  experiments,
}: {
  experiments: (ExperimentRecord & { product_title: string })[];
}) {
  const fetcher = useFetcher<{ intent: string; ok: boolean }>();
  const active = experiments.filter((e) => e.status === "active");
  const rest = experiments.filter((e) => e.status !== "active").slice(0, 5);
  const rows = [...active, ...rest].map((exp) => {
    const stats = exp.latest_stats;
    const prob = stats
      ? `${(stats.prob_treatment_better * 100).toFixed(1)}%`
      : "—";
    const days = stats ? `${stats.days_running}d` : "—";
    const isKilling =
      fetcher.state !== "idle" &&
      fetcher.formData?.get("experimentId") === String(exp.id);

    return [
      exp.product_title,
      `${exp.control_discount_pct}% → ${exp.treatment_discount_pct}%`,
      days,
      prob,
      exp.status === "active" ? (
        <fetcher.Form method="post" key={exp.id}>
          <input type="hidden" name="intent" value="kill" />
          <input type="hidden" name="experimentId" value={exp.id} />
          <Button tone="critical" size="slim" submit loading={isKilling}>
            Kill
          </Button>
        </fetcher.Form>
      ) : (
        <Badge
          tone={
            exp.status === "concluded" ? "attention" : "critical"
          }
        >
          {exp.conclusion_type ?? exp.status}
        </Badge>
      ),
    ];
  });

  if (experiments.length === 0) {
    return (
      <Card>
        <BlockStack gap="200">
          <Text as="h2" variant="headingMd">A/B Experiments</Text>
          <Text as="p" tone="subdued">
            No experiments yet. Approve a recommendation to start one.
          </Text>
        </BlockStack>
      </Card>
    );
  }

  return (
    <Card>
      <BlockStack gap="300">
        <InlineStack align="space-between" blockAlign="center">
          <Text as="h2" variant="headingMd">A/B Experiments</Text>
          <Badge tone={active.length > 0 ? "success" : "new"}>
            {active.length > 0 ? `${active.length} active` : "none active"}
          </Badge>
        </InlineStack>
        <DataTable
          columnContentTypes={["text", "text", "numeric", "numeric", "text"]}
          headings={[
            "Product",
            "Control → Treatment",
            "Days",
            "P(treatment better)",
            "Action",
          ]}
          rows={rows}
        />
      </BlockStack>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// ProductRow (P1 + P2)
// ---------------------------------------------------------------------------

function ProductRow({
  product,
  fv,
  rec: initialRec,
}: {
  product: ProductRow;
  fv: FeatureVector | undefined;
  rec: RecommendationRow | undefined;
}) {
  const fetcher = useFetcher<{
    intent: string;
    ok: boolean;
    rec?: RecommendationRow;
  }>();
  const [rationaleOpen, setRationaleOpen] = useState(false);

  const rec =
    fetcher.data?.intent === "generate" && fetcher.data.rec
      ? fetcher.data.rec
      : initialRec;

  const recPct = rec ? parseFloat(rec.recommended_discount_pct) : null;
  const confidence = rec ? parseFloat(rec.confidence_score) : null;
  const contextBucket =
    (rec?.feature_snapshot as Record<string, string> | null)
      ?.context_bucket ?? "—";

  const recStatus =
    fetcher.data?.intent === "approve" && fetcher.data.ok
      ? "approved"
      : fetcher.data?.intent === "reject" && fetcher.data.ok
        ? "rejected"
        : rec?.status ?? null;

  const isGenerating =
    fetcher.state !== "idle" &&
    fetcher.formData?.get("intent") === "generate";
  const isApproving =
    fetcher.state !== "idle" &&
    fetcher.formData?.get("intent") === "approve";
  const isRejecting =
    fetcher.state !== "idle" &&
    fetcher.formData?.get("intent") === "reject";

  return (
    <Box paddingBlock="300">
      <BlockStack gap="200">
        <InlineStack align="space-between" blockAlign="start" wrap={false} gap="400">
          {/* Left: name + badges */}
          <BlockStack gap="100">
            <Text as="p" variant="bodyMd" fontWeight="semibold">
              {product.title}
            </Text>
            <InlineStack gap="100">
              {fv && (
                <Badge tone="new">
                  {fv.price_tier.replace(/_/g, " ")}
                </Badge>
              )}
              {contextBucket !== "—" && (
                <Badge>{contextBucket}</Badge>
              )}
            </InlineStack>
          </BlockStack>

          {/* Right: metric columns + actions */}
          <InlineStack gap="500" blockAlign="center" wrap={false}>
            <BlockStack gap="050" inlineAlign="center">
              <Text as="p" variant="bodySm" tone="subdued">Current</Text>
              <Text as="p" variant="bodyMd">
                {fv ? fmtPct(fv.current_discount_pct) : "—"}
              </Text>
            </BlockStack>

            <BlockStack gap="050" inlineAlign="center">
              <Text as="p" variant="bodySm" tone="subdued">AI Rec.</Text>
              <Text as="p" variant="bodyMd" fontWeight="semibold">
                {recPct !== null ? fmtDiscountPct(recPct) : "—"}
              </Text>
            </BlockStack>

            <BlockStack gap="050" inlineAlign="center">
              <Text as="p" variant="bodySm" tone="subdued">Confidence</Text>
              <Text as="p" variant="bodyMd">
                {confidence !== null ? fmtConfidence(confidence) : "—"}
              </Text>
            </BlockStack>

            <BlockStack gap="050" inlineAlign="center">
              <Text as="p" variant="bodySm" tone="subdued">Status</Text>
              {recStatus
                ? statusBadge(recStatus, product.has_active_experiment)
                : <Badge tone="new">No recommendation</Badge>
              }
            </BlockStack>

            {/* Action buttons */}
            <InlineStack gap="200" blockAlign="center">
              {!rec && (
                <fetcher.Form method="post">
                  <input type="hidden" name="intent" value="generate" />
                  <input type="hidden" name="productId" value={product.id} />
                  <Button submit loading={isGenerating} size="slim">
                    Generate
                  </Button>
                </fetcher.Form>
              )}

              {rec && recStatus === "pending" && (
                <>
                  <fetcher.Form method="post">
                    <input type="hidden" name="intent" value="approve" />
                    <input type="hidden" name="recId" value={rec.id} />
                    <input
                      type="hidden"
                      name="discountPct"
                      value={rec.recommended_discount_pct}
                    />
                    <Button
                      tone="success"
                      size="slim"
                      submit
                      loading={isApproving}
                    >
                      {`Approve ${fmtDiscountPct(parseFloat(rec.recommended_discount_pct))}`}
                    </Button>
                  </fetcher.Form>
                  <fetcher.Form method="post">
                    <input type="hidden" name="intent" value="reject" />
                    <input type="hidden" name="recId" value={rec.id} />
                    <Button
                      tone="critical"
                      size="slim"
                      submit
                      loading={isRejecting}
                    >
                      Reject
                    </Button>
                  </fetcher.Form>
                </>
              )}

              {rec && (rec.rationale || rec.llm_explanation) && (
                <Button
                  size="slim"
                  variant="plain"
                  onClick={() => setRationaleOpen((o) => !o)}
                >
                  {rationaleOpen ? "Hide" : "Why?"}
                </Button>
              )}
            </InlineStack>
          </InlineStack>
        </InlineStack>

        {/* Rationale collapsible (P2) */}
        <Collapsible
          id={`rationale-${product.id}`}
          open={rationaleOpen}
          transition={{ duration: "200ms", timingFunction: "ease-in-out" }}
        >
          <Box
            background="bg-surface-secondary"
            padding="300"
            borderRadius="200"
          >
            <BlockStack gap="150">
              {rec?.llm_explanation && (
                <Text as="p" variant="bodySm">
                  {rec.llm_explanation}
                </Text>
              )}
              {rec?.model_version && (
                <Text as="p" variant="bodySm" tone="subdued">
                  Engine: {rec.model_version}
                  {(rec.feature_snapshot as Record<string, unknown>)?.avg_conversion_rate != null &&
                    ` · Conv. rate: ${Number((rec.feature_snapshot as Record<string, number>).avg_conversion_rate).toFixed(4)}`}
                  {(rec.feature_snapshot as Record<string, unknown>)?.avg_inventory_days_supply != null &&
                    ` · Inv. days: ${Number((rec.feature_snapshot as Record<string, number>).avg_inventory_days_supply).toFixed(1)}`}
                </Text>
              )}
            </BlockStack>
          </Box>
        </Collapsible>

        {fetcher.data?.ok === false && (
          <Banner tone="critical">Action failed — check the engine logs.</Banner>
        )}
      </BlockStack>
      <Box paddingBlockStart="300">
        <Divider />
      </Box>
    </Box>
  );
}

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

export default function ProductsIndex() {
  const {
    products,
    featuresByProductId,
    recByProductId,
    experiments,
    trustScore,
    hasProducts,
  } = useLoaderData<typeof loader>();

  const navigation = useNavigation();
  const revalidator = useRevalidator();
  const seedFetcher = useFetcher<{
    intent: string;
    ok: boolean;
    message?: string;
  }>();

  const isLoading = navigation.state === "loading";

  const hasActive = experiments.some((e) => e.status === "active");
  useEffect(() => {
    if (!hasActive) return;
    const id = setInterval(() => revalidator.revalidate(), 30_000);
    return () => clearInterval(id);
  }, [hasActive, revalidator]);

  if (isLoading) {
    return (
      <Page title="Discount Optimizer">
        <TitleBar title="Discount Optimizer" />
        <Layout>
          <Layout.Section>
            <Card>
              <BlockStack gap="400">
                <SkeletonDisplayText size="small" />
                <SkeletonBodyText lines={6} />
              </BlockStack>
            </Card>
          </Layout.Section>
        </Layout>
      </Page>
    );
  }

  return (
    <Page title="Discount Optimizer">
      <TitleBar title="Discount Optimizer" />
      <Layout>
        {/* Main column */}
        <Layout.Section>
          <BlockStack gap="500">
            {/* P1 — Products */}
            <Card>
              <BlockStack gap="300">
                <InlineStack align="space-between" blockAlign="center">
                  <Text as="h2" variant="headingMd">Products</Text>
                  <Text as="p" variant="bodySm" tone="subdued">
                    {products.length} synced
                  </Text>
                </InlineStack>

                {!hasProducts ? (
                  <EmptyState
                    heading="No products synced yet"
                    action={{
                      content: "Load demo data",
                      loading: seedFetcher.state !== "idle",
                      onAction: () => {
                        const fd = new FormData();
                        fd.append("intent", "seed");
                        seedFetcher.submit(fd, { method: "post" });
                      },
                    }}
                    image="https://cdn.shopify.com/s/files/1/0262/4071/2726/files/emptystate-files.png"
                  >
                    <p>
                      Run <code>python scripts/seed_local.py</code> or click
                      &quot;Load demo data&quot; to warm up the feature store.
                    </p>
                  </EmptyState>
                ) : (
                  <BlockStack gap="0">
                    {products.map((p) => (
                      <ProductRow
                        key={p.id}
                        product={p}
                        fv={featuresByProductId[p.id]}
                        rec={recByProductId[p.id]}
                      />
                    ))}
                  </BlockStack>
                )}
              </BlockStack>
            </Card>

            {/* P3 — Experiments */}
            <ExperimentPanel
              experiments={
                experiments as (ExperimentRecord & { product_title: string })[]
              }
            />
          </BlockStack>
        </Layout.Section>

        {/* Sidebar */}
        <Layout.Section variant="oneThird">
          <BlockStack gap="400">
            {/* P4 — Trust score */}
            <TrustScoreCard trust={trustScore} />

            {/* P5 — Demo seed */}
            <Card>
              <BlockStack gap="300">
                <Text as="h2" variant="headingMd">Demo Controls</Text>
                <Text as="p" variant="bodySm" tone="subdued">
                  Refresh feature vectors from the database and warm the Redis
                  cache for all products.
                </Text>
                <seedFetcher.Form method="post">
                  <input type="hidden" name="intent" value="seed" />
                  <Button
                    submit
                    loading={seedFetcher.state !== "idle"}
                    fullWidth
                  >
                    Load demo data
                  </Button>
                </seedFetcher.Form>
                {seedFetcher.data && (
                  <Banner
                    tone={seedFetcher.data.ok ? "success" : "critical"}
                  >
                    {seedFetcher.data.message ?? (seedFetcher.data.ok ? "Done" : "Failed")}
                  </Banner>
                )}
              </BlockStack>
            </Card>
          </BlockStack>
        </Layout.Section>
      </Layout>
    </Page>
  );
}
