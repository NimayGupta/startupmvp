/**
 * Bulk Data Sync Page — /app/sync
 *
 * Shown after a merchant installs the app. Displays the sync progress and
 * redirects to the products dashboard when complete.
 *
 * The actual sync is triggered server-side after OAuth (in shopify.server.ts).
 * This page polls a status endpoint every 3 seconds to update the UI.
 */

import { useEffect, useState } from "react";
import type { LoaderFunctionArgs, ActionFunctionArgs } from "@remix-run/node";
import { json, redirect } from "@remix-run/node";
import { useLoaderData, useFetcher } from "@remix-run/react";
import {
  Page,
  Layout,
  Card,
  Text,
  Banner,
  Button,
  BlockStack,
} from "@shopify/polaris";
import { authenticate } from "~/shopify.server";
import { db } from "~/lib/db.server";
import { enqueueBulkSync } from "~/lib/queue.server";
import { SyncStatus } from "~/components/SyncStatus";

interface SyncStatusData {
  synced: boolean;
  inProgress: boolean;
  productCount: number | null;
  error: string | null;
}

export const loader = async ({ request }: LoaderFunctionArgs) => {
  const { session } = await authenticate.admin(request);

  // Check if a sync_completed event exists for this merchant
  const merchantResult = await db.query<{ id: number }>(
    "SELECT id FROM merchants WHERE shopify_domain = $1 AND uninstalled_at IS NULL LIMIT 1",
    [session.shop]
  );

  if (merchantResult.rows.length === 0) {
    return redirect("/auth/login");
  }

  const merchantId = merchantResult.rows[0].id;

  // Check for completed sync event
  const syncResult = await db.query<{
    payload: { product_count: number; order_count: number };
    created_at: string;
  }>(
    `SELECT payload, created_at FROM event_log
     WHERE merchant_id = $1 AND event_type = 'sync_completed'
     ORDER BY created_at DESC LIMIT 1`,
    [merchantId]
  );

  if (syncResult.rows.length > 0) {
    const { product_count } = syncResult.rows[0].payload;
    return json<SyncStatusData>({
      synced: true,
      inProgress: false,
      productCount: product_count,
      error: null,
    });
  }

  return json<SyncStatusData>({
    synced: false,
    inProgress: true,
    productCount: null,
    error: null,
  });
};

export const action = async ({ request }: ActionFunctionArgs) => {
  const { session } = await authenticate.admin(request);

  const merchantResult = await db.query<{ id: number }>(
    "SELECT id FROM merchants WHERE shopify_domain = $1 AND uninstalled_at IS NULL LIMIT 1",
    [session.shop]
  );

  if (merchantResult.rows.length === 0) {
    return json({ error: "Merchant not found" }, { status: 404 });
  }

  const merchantId = merchantResult.rows[0].id;
  await enqueueBulkSync(merchantId);

  return json({ queued: true });
};

export default function SyncPage() {
  const initialData = useLoaderData<typeof loader>();
  const [status, setStatus] = useState<SyncStatusData>(initialData);
  const fetcher = useFetcher();

  // Poll every 3 seconds while sync is in progress
  useEffect(() => {
    if (status.synced || !status.inProgress) return;

    const interval = setInterval(async () => {
      const response = await fetch(window.location.href, {
        headers: { Accept: "application/json" },
      });
      if (response.ok) {
        const data: SyncStatusData = await response.json();
        setStatus(data);
        if (data.synced) {
          clearInterval(interval);
        }
      }
    }, 3000);

    return () => clearInterval(interval);
  }, [status.synced, status.inProgress]);

  return (
    <Page title="Syncing Your Store Data">
      <Layout>
        <Layout.Section>
          <Card>
            <BlockStack gap="400">
              {status.synced ? (
                <Banner tone="success" title="Sync complete!">
                  <p>
                    Your store data has been synced.{" "}
                    {status.productCount !== null &&
                      `${status.productCount} products imported.`}
                  </p>
                </Banner>
              ) : (
                <SyncStatus />
              )}

              {status.synced && (
                <Button
                  variant="primary"
                  url="/app"
                >
                  View your products
                </Button>
              )}

              {!status.synced && !status.inProgress && (
                <>
                  <Banner tone="warning" title="Sync not started">
                    <p>
                      The initial data sync has not started yet. Click below to
                      start it.
                    </p>
                  </Banner>
                  <fetcher.Form method="post">
                    <Button
                      variant="primary"
                      submit
                      loading={fetcher.state !== "idle"}
                    >
                      Start sync
                    </Button>
                  </fetcher.Form>
                </>
              )}
            </BlockStack>
          </Card>
        </Layout.Section>
      </Layout>
    </Page>
  );
}
