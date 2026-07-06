# CLAIMS.md — claim and stat provenance

Every stat or factual claim on the site, with its provenance. Two kinds:

- **(a) externally sourced** — with the source linked.
- **(b) illustrative** — invented for illustration and labeled as such in the UI.

Do not add a number to the site without adding a row here.

## On the page

| Claim | Where | Kind | Provenance / note |
|-------|-------|------|-------------------|
| "Orders from AI-powered search on Shopify grew roughly 13× year over year in Q1 2026" | #moat "Why now" | (a) sourced | Shopify Q1 2026 earnings (May 5, 2026), as reported by [PYMNTS](https://www.pymnts.com/earnings/2026/ai-drove-orders-shopify-up-13-times-q1/). Shopify also reported AI-driven traffic up ~8× ([Shopify blog](https://www.shopify.com/enterprise/blog/ai-search-insights)). Linked from the page. |
| Ledger panel rows (SKUs, actions, deltas, confidences) | Hero | (b) illustrative | Simulated product preview. Labeled "simulated preview" in the panel header. Data in `src/data/ledger.ts`. |
| Ledger counters: "1,284 experiments concluded", "+11.2% net profit lift" | Hero ledger footer | (b) illustrative | Simulated; covered by the panel's "simulated preview" label. **Replace with real numbers when they exist.** |
| "How faithful is the signal?" bar chart (simulated < logs < live outcomes) | #moat | (b) illustrative | Qualitative argument drawn as bars. Caption on the chart says "Illustrative — not a measurement." |
| Feature statuses (live / rolling out) | #features | internal | Reflects actual product state per the app repo (Bayesian experiments, checkout extension, event ledger, explanations = built; bandit + trust/auto-approve = built, tier-gated rollout). **Re-verify before launch.** |
| "Margent is onboarding a small set of Shopify stores" | #waitlist | internal | Positioning statement — confirm it matches reality at launch. |

## Positioning context (not on the page, kept for pitch/application use)

| Claim | Kind | Provenance |
|-------|------|------------|
| Anthropic reportedly discussed spending >$1B on RL environments in a year | (a) sourced | The Information (Sept 2025), via [TechCrunch](https://techcrunch.com/2025/09/21/silicon-valley-bets-big-on-environments-to-train-ai-agents/) |
| a16z led a $43M Series A into an RL-environments startup (Deeptune) | (a) sourced | [Fortune, Mar 19 2026](https://fortune.com/2026/03/19/andreessen-horowitz-ai-startups-deeptune-series-a/) |
| Willingness to pay for price testing on Shopify is proven (Intelligems) | (a) sourced (qualitative) | [Intelligems](https://www.intelligems.io/) is a live, reviewed Shopify price-testing app ([App Store listing](https://apps.shopify.com/intelligems)). No acquisition or revenue claims — none verified. Kept off the public page (competitor mention). |

## Before launch (human checklist)

- [ ] Replace `hello@margent.example.com` and `margent.example.com` in `src/data/site.ts` + `astro.config.mjs`.
- [ ] Re-verify each feature status in `src/data/features.ts` against the product.
- [ ] Confirm the waitlist copy ("small set of stores") is accurate.
- [ ] Decide whether ledger counters stay simulated (labeled) or go real.
