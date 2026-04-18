# Merchant Onboarding Guide — Discount Optimizer

## Step 1: Install the App

1. Open the [Shopify App Store](https://apps.shopify.com) and search for **Discount Optimizer**.
2. Click **Add app** and log in to your Shopify admin if prompted.
3. Review the requested permissions and click **Install app**.
4. You'll be redirected to the Discount Optimizer dashboard inside your Shopify admin.

Your store's product catalog and recent order history sync automatically in the background — this takes 2–5 minutes for most stores.

---

## Step 2: Connect Your Store

Once installed, the dashboard shows a **Products** table. If it's empty, the sync is still in progress — refresh after a minute.

Each product row shows:
- Current price and inventory level
- A **Generate Recommendation** button to request an AI discount suggestion

No additional configuration is required. The app reads your product and order data automatically via Shopify's API.

---

## Step 3: Run Your First Experiment

### Generate a recommendation

1. In the Products table, click **Generate Recommendation** for any product.
2. The AI engine analyzes 28 days of order history, current price, inventory, and conversion patterns.
3. A recommendation card appears with a suggested discount percentage and an explanation.

### Review and approve

- Read the **explanation** — it summarizes why this discount is suggested (e.g., high inventory, low conversion rate).
- Click **Approve** to accept the suggestion as-is, or **Edit & Approve** to type in your own discount percentage.
- Click **Reject** if the suggestion doesn't fit your current strategy. The system learns from rejections.

### What happens when you approve

Approving creates a Shopify automatic discount applied to that product. A **Bayesian A/B experiment** starts automatically: 50% of shoppers see the discounted price (treatment) and 50% see the original price (control).

---

## Step 4: Understand Your Experiment Results

The **Experiment Status** panel shows all running and completed experiments.

| Column | Meaning |
|--------|---------|
| Treatment discount | The discount being tested |
| Probability treatment is better | Bayesian probability (0–100%) that the discount improves order rate |
| Expected lift | Estimated percentage increase in orders |
| Status | Active / Concluded / Killed |

### When does an experiment conclude?

The system checks every 6 hours. An experiment concludes automatically when:
- **≥ 95% probability** treatment is better (or ≤ 5%) **and** at least 3 days have passed, **or**
- 30 days have elapsed (max duration)

You can also click **Kill experiment** at any time to stop it early — the Shopify discount is not automatically removed, so you can choose to keep or delete it manually.

---

## Step 5: Enable Auto-Approve (Pro plan)

Once your **Trust Score** reaches 0.70 or higher (shown in the sidebar), the Pro plan unlocks **Auto-Approve** mode. In this mode:
- Recommendations above the trust threshold are approved and launched as experiments automatically.
- You still see everything in the dashboard and can kill any experiment.
- Trust score is calculated from your approval history: `(positive approvals / total) × log-scaled experience`.

To upgrade to Pro: go to **Settings → Billing** and select the Pro plan.

---

## Frequently Asked Questions

**Q: Will the discount apply to all my customers?**
A: The experiment assigns each shopper randomly. Approximately half see the discount, half see the original price. Assignment is session-based and consistent.

**Q: What if I already have a discount running?**
A: Shopify applies the best available automatic discount. Running multiple overlapping experiments can confuse results — we recommend one experiment per product at a time.

**Q: How is the "expected lift" calculated?**
A: We use a Gamma-Poisson Bayesian model fit to order counts per day for the control window (14 days before experiment) and the treatment window (days since experiment start). Lift is the posterior mean difference in order rate.

**Q: Does the app store any customer personal data?**
A: No. We only store aggregate order counts and product-level metrics, never individual customer identifiers.

**Q: What happens when I uninstall?**
A: All your data is deleted within 48 hours per our privacy policy. Active Shopify discounts created by the app remain in your Shopify admin until you manually remove them.
