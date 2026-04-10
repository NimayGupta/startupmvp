/**
 * SyncStatus component
 *
 * Displays a loading spinner and status message while the bulk data sync
 * is in progress. Used on the /app/sync page.
 */

import { Spinner, Text, BlockStack, InlineStack } from "@shopify/polaris";

export function SyncStatus() {
  return (
    <BlockStack gap="400" inlineAlign="center">
      <InlineStack gap="300" align="center">
        <Spinner size="large" accessibilityLabel="Syncing store data" />
        <BlockStack gap="100">
          <Text as="h2" variant="headingMd">
            Syncing your store data…
          </Text>
          <Text as="p" variant="bodySm" tone="subdued">
            We're importing your products and order history from the last 90 days.
            This usually takes 1–3 minutes. You can close this tab and we'll
            continue in the background.
          </Text>
        </BlockStack>
      </InlineStack>
    </BlockStack>
  );
}
