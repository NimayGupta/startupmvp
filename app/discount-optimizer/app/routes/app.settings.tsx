import { useState } from "react";
import type { ActionFunctionArgs, LoaderFunctionArgs } from "@remix-run/node";
import { json } from "@remix-run/node";
import { useActionData, useLoaderData } from "@remix-run/react";
import {
  Page,
  Layout,
  Card,
  BlockStack,
  InlineStack,
  Text,
  TextField,
  Checkbox,
  Button,
  Banner,
  Divider,
} from "@shopify/polaris";
import { TitleBar, useAppBridge } from "@shopify/app-bridge-react";
import { authenticate } from "../shopify.server";
import { upsertMerchant, getMerchantByDomain, updateMerchantSettings } from "../lib/merchant.server";

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

  return json({ merchant });
};

// ---------------------------------------------------------------------------
// Action
// ---------------------------------------------------------------------------

export const action = async ({ request }: ActionFunctionArgs) => {
  const { session } = await authenticate.admin(request);

  const merchant = await getMerchantByDomain(session.shop);
  if (!merchant) {
    return json({ error: "Merchant not found" }, { status: 404 });
  }

  const form = await request.formData();

  const autoApproveEnabled = form.get("autoApproveEnabled") === "true";
  const rawSafeZone = Number(form.get("safeZoneMaxPct") ?? 20);
  // Clamp to valid range
  const safeZoneMaxPct = Math.min(Math.max(rawSafeZone, 0), 100);
  const notificationEmailEnabled =
    form.get("notificationEmailEnabled") === "true";
  const notificationEmail =
    (form.get("notificationEmail") as string | null) || null;

  await updateMerchantSettings(merchant.id, {
    autoApproveEnabled,
    safeZoneMaxPct,
    notificationEmailEnabled,
    notificationEmail,
  });

  return json({ saved: true });
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function Settings() {
  const { merchant } = useLoaderData<typeof loader>();
  const actionData = useActionData<typeof action>();
  const shopify = useAppBridge();

  const [autoApprove, setAutoApprove] = useState(
    merchant.auto_approve_enabled,
  );
  const [safeZone, setSafeZone] = useState(
    String(merchant.safe_zone_max_pct),
  );
  const [notifEnabled, setNotifEnabled] = useState(
    merchant.notification_email_enabled,
  );
  const [notifEmail, setNotifEmail] = useState(
    merchant.notification_email ?? "",
  );

  // Show a toast when saved successfully
  if (actionData && "saved" in actionData && actionData.saved) {
    shopify.toast.show("Settings saved");
  }

  return (
    <Page title="Settings">
      <TitleBar title="Settings" />
      <Layout>
        <Layout.Section>
          <BlockStack gap="400">
            {/* Show error if action returned one */}
            {"error" in (actionData ?? {}) && (
              <Banner tone="critical" title="Save failed">
                <p>{(actionData as { error: string }).error}</p>
              </Banner>
            )}

            {/* Optimization settings */}
            <Card>
              <BlockStack gap="400">
                <Text as="h2" variant="headingMd">
                  Optimization Settings
                </Text>

                <Checkbox
                  label="Enable auto-approve"
                  helpText="When enabled, low-risk recommendations are applied automatically for products with a high trust score (Phase 5)."
                  checked={autoApprove}
                  onChange={setAutoApprove}
                  name="autoApproveEnabled"
                />

                <TextField
                  label="Safe zone max discount"
                  type="number"
                  value={safeZone}
                  onChange={setSafeZone}
                  name="safeZoneMaxPct"
                  min={0}
                  max={100}
                  suffix="%"
                  helpText="The system will never recommend a discount higher than this value."
                  autoComplete="off"
                />
              </BlockStack>
            </Card>

            <Divider />

            {/* Notification preferences */}
            <Card>
              <BlockStack gap="400">
                <Text as="h2" variant="headingMd">
                  Notifications
                </Text>

                <Checkbox
                  label="Email me when a new recommendation is ready"
                  checked={notifEnabled}
                  onChange={setNotifEnabled}
                  name="notificationEmailEnabled"
                />

                <TextField
                  label="Notification email"
                  type="email"
                  value={notifEmail}
                  onChange={setNotifEmail}
                  name="notificationEmail"
                  disabled={!notifEnabled}
                  placeholder="you@example.com"
                  autoComplete="email"
                />
              </BlockStack>
            </Card>

            {/* Submit */}
            <InlineStack align="end">
              <form method="post">
                <input
                  type="hidden"
                  name="autoApproveEnabled"
                  value={String(autoApprove)}
                />
                <input
                  type="hidden"
                  name="safeZoneMaxPct"
                  value={safeZone}
                />
                <input
                  type="hidden"
                  name="notificationEmailEnabled"
                  value={String(notifEnabled)}
                />
                <input
                  type="hidden"
                  name="notificationEmail"
                  value={notifEmail}
                />
                <Button variant="primary" submit>
                  Save settings
                </Button>
              </form>
            </InlineStack>
          </BlockStack>
        </Layout.Section>
      </Layout>
    </Page>
  );
}
