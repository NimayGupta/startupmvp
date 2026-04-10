/**
 * Merchant record management.
 *
 * The Shopify session (from PrismaSessionStorage) is the auth source of truth.
 * These helpers mirror the merchant into our PostgreSQL `merchants` table,
 * storing the access_token encrypted with pgcrypto for use by Python workers.
 *
 * Call `upsertMerchant()` at the top of every protected loader/action.
 */

import { query } from "./db.server";

export interface MerchantRecord {
  id: number;
  shopify_domain: string;
  auto_approve_enabled: boolean;
  safe_zone_max_pct: number;
  notification_email_enabled: boolean;
  notification_email: string | null;
}

/**
 * Upserts a merchant row from the Shopify session.
 *
 * - Creates the row on first install.
 * - Refreshes access_token + scopes on every request (tokens can rotate).
 * - access_token is encrypted with pgp_sym_encrypt using DB_ENCRYPTION_KEY.
 *
 * Always returns a populated MerchantRecord.
 */
export async function upsertMerchant(
  shopDomain: string,
  accessToken: string,
  scopes: string,
): Promise<MerchantRecord> {
  const encKey = process.env.DB_ENCRYPTION_KEY ?? "";

  const rows = await query<MerchantRecord>(
    `INSERT INTO merchants (shopify_domain, access_token, scopes)
     VALUES ($1, pgp_sym_encrypt($2, $3), $4)
     ON CONFLICT (shopify_domain) DO UPDATE SET
       access_token = pgp_sym_encrypt($2, $3),
       scopes       = EXCLUDED.scopes,
       updated_at   = NOW()
     RETURNING
       id,
       shopify_domain,
       auto_approve_enabled,
       safe_zone_max_pct::float AS safe_zone_max_pct,
       notification_email_enabled,
       notification_email`,
    [shopDomain, accessToken, encKey, scopes],
  );

  if (rows.length === 0) {
    throw new Error(`upsertMerchant failed for domain: ${shopDomain}`);
  }
  return rows[0];
}

/**
 * Looks up a merchant by shop domain. Returns null if not found.
 */
export async function getMerchantByDomain(
  shopDomain: string,
): Promise<MerchantRecord | null> {
  const rows = await query<MerchantRecord>(
    `SELECT id, shopify_domain, auto_approve_enabled,
            safe_zone_max_pct::float AS safe_zone_max_pct,
            notification_email_enabled, notification_email
     FROM merchants
     WHERE shopify_domain = $1`,
    [shopDomain],
  );
  return rows[0] ?? null;
}

/**
 * Persists merchant settings from the Settings page.
 */
export async function updateMerchantSettings(
  merchantId: number,
  settings: {
    autoApproveEnabled: boolean;
    safeZoneMaxPct: number;
    notificationEmailEnabled: boolean;
    notificationEmail: string | null;
  },
): Promise<void> {
  await query(
    `UPDATE merchants SET
       auto_approve_enabled        = $1,
       safe_zone_max_pct           = $2,
       notification_email_enabled  = $3,
       notification_email          = $4,
       updated_at                  = NOW()
     WHERE id = $5`,
    [
      settings.autoApproveEnabled,
      settings.safeZoneMaxPct,
      settings.notificationEmailEnabled,
      settings.notificationEmail,
      merchantId,
    ],
  );
}
