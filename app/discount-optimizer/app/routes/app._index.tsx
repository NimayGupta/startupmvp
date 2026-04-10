import type { LoaderFunctionArgs } from "@remix-run/node";
import { json } from "@remix-run/node";
import { useLoaderData, useNavigate, useNavigation } from "@remix-run/react";
import {
  Page,
  Layout,
  Card,
  DataTable,
  Badge,
  EmptyState,
  BlockStack,
  SkeletonBodyText,
  SkeletonDisplayText,
  Link,
  Text,
} from "@shopify/polaris";
import { TitleBar } from "@shopify/app-bridge-react";
import { authenticate } from "../shopify.server";
import { upsertMerchant } from "../lib/merchant.server";
import { query } from "../lib/db.server";
import {
  fetchMerchantFeatures,
  buildProductFeatureMap,
  type FeatureVector,
} from "../lib/engine.server";

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

  const products = await query<ProductRow>(
    `SELECT
       p.id,
       p.shopify_product_id,
       p.title,
       MIN(pv.price)::text                          AS min_price,
       EXISTS(
         SELECT 1 FROM experiments e
         WHERE e.product_id = p.id AND e.status = 'active'
       )                                            AS has_active_experiment
     FROM products p
     JOIN product_variants pv ON pv.product_id = p.id
     WHERE p.merchant_id = $1
       AND p.status      = 'active'
     GROUP BY p.id
     ORDER BY p.title`,
    [merchant.id],
  );

  const engineResponse = await fetchMerchantFeatures(merchant.id);
  const featuresByProductId = buildProductFeatureMap(
    engineResponse?.features ?? [],
  );

  return json({
    merchantId: merchant.id,
    products,
    featuresByProductId,
    hasProducts: products.length > 0,
  });
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtPct(val: number) {
  return `${(val * 100).toFixed(1)}%`;
}

function fmtUsd(val: number) {
  return `$${val.toFixed(2)}`;
}

function outcomeLabel(outcome: FeatureVector["last_test_outcome"]) {
  const map = { positive: "↑", negative: "↓", neutral: "→", none: "—" } as const;
  return map[outcome] ?? "—";
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ProductsIndex() {
  const { products, featuresByProductId, hasProducts } =
    useLoaderData<typeof loader>();
  const navigation = useNavigation();
  const navigate = useNavigate();

  const isLoading = navigation.state === "loading";

  if (isLoading) {
    return (
      <Page title="Products">
        <TitleBar title="Discount Optimizer" />
        <Layout>
          <Layout.Section>
            <Card>
              <BlockStack gap="400">
                <SkeletonDisplayText size="small" />
                <SkeletonBodyText lines={8} />
              </BlockStack>
            </Card>
          </Layout.Section>
        </Layout>
      </Page>
    );
  }

  if (!hasProducts) {
    return (
      <Page title="Products">
        <TitleBar title="Discount Optimizer" />
        <Layout>
          <Layout.Section>
            <Card>
              <EmptyState
                heading="No products synced yet"
                action={{ content: "Start sync", url: "/app/sync" }}
                image="https://cdn.shopify.com/s/files/1/0262/4071/2726/files/emptystate-files.png"
              >
                <p>
                  Sync your Shopify catalog to start receiving discount
                  recommendations.
                </p>
              </EmptyState>
            </Card>
          </Layout.Section>
        </Layout>
      </Page>
    );
  }

  const rows = products.map((p) => {
    const fv = featuresByProductId[p.id];
    const price = parseFloat(p.min_price ?? "0");

    return [
      // Product name — clickable
      <Link
        key={p.id}
        removeUnderline
        monochrome
        url={`/app/products/${p.id}`}
      >
        {p.title}
      </Link>,
      // Price
      fmtUsd(price),
      // Discount %
      fv ? fmtPct(fv.current_discount_pct) : "—",
      // 14-day conversion rate (orders/day proxy)
      fv ? fv.conversion_rate.toFixed(4) : "—",
      // Revenue per visitor (revenue/day proxy)
      fv ? fmtUsd(fv.revenue_per_visitor) : "—",
      // Inventory days supply
      fv ? `${fv.inventory_days_supply}d` : "—",
      // Active experiment badge
      p.has_active_experiment ? (
        <Badge key={`exp-${p.id}`} tone="success">
          Active
        </Badge>
      ) : (
        <Badge key={`exp-${p.id}`} tone="new">
          None
        </Badge>
      ),
    ];
  });

  return (
    <Page title="Products">
      <TitleBar title="Discount Optimizer" />
      <Layout>
        <Layout.Section>
          <Card>
            <BlockStack gap="200">
              <Text as="p" variant="bodySm" tone="subdued">
                Metrics are computed over a 14-day rolling window.
                Conversion rate and RPV are approximated as daily averages
                (no session data at MVP stage).
              </Text>
              <DataTable
                columnContentTypes={[
                  "text",
                  "numeric",
                  "numeric",
                  "numeric",
                  "numeric",
                  "numeric",
                  "text",
                ]}
                headings={[
                  "Product",
                  "Price",
                  "Discount",
                  "Conv. Rate",
                  "RPV",
                  "Inv. Days",
                  "Experiment",
                ]}
                rows={rows}
              />
            </BlockStack>
          </Card>
        </Layout.Section>
      </Layout>
    </Page>
  );
}
