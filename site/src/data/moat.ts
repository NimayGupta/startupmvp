/** Content for #moat — the decision ledger / environment story. */

export interface MoatPoint {
  n: string;
  title: string;
  body: string;
}

export interface FidelityRow {
  label: string;
  note: string;
  /** Bar length, % of the widest bar. Illustrative, not a measurement. */
  value: number;
  highlight?: boolean;
}

export const moat = {
  kicker: 'The ledger',
  title: 'The environment labs can’t buy.',
  lede: 'Simulated shoppers are guesses. Historical logs are correlations. The one signal that teaches an agent to price well — a real decision on a live store, and the revenue that followed — never touches the public internet. Margent’s day job writes exactly that signal, decision by decision, into an append-only ledger.',

  points: [
    {
      n: '01',
      title: 'Sealed by construction',
      body: 'Shopper price-response lives inside private checkout infrastructure. It can’t be scraped, and it isn’t in any training set.',
    },
    {
      n: '02',
      title: 'Real reward, not a proxy',
      body: 'The ledger records profit that actually happened, on real orders — the gold standard the measurement field is chasing.',
    },
    {
      n: '03',
      title: 'Compounds from customer one',
      body: 'A late entrant with more capital still can’t reconstruct the missing months of outcomes. Time in market is the moat.',
    },
    {
      n: '04',
      title: 'A different day job',
      body: 'Labs build models, not merchant-facing outcome capture inside thousands of individual checkouts. This layer is ours to build.',
    },
  ] satisfies MoatPoint[],

  chart: {
    title: 'How faithful is the signal?',
    caption: 'Illustrative comparison of training-signal fidelity for pricing agents — not a measurement.',
    rows: [
      { label: 'Simulated shoppers', note: 'guesses about behavior', value: 28 },
      { label: 'Historical logs', note: 'correlation, no counterfactual', value: 55 },
      { label: 'Live decisions + outcomes', note: 'the ledger', value: 100, highlight: true },
    ] satisfies FidelityRow[],
  },

  whyNow: {
    title: 'Why now',
    body: 'Agentic commerce just made pricing a machine problem. Orders from AI-powered search on Shopify grew roughly 13× year over year in Q1 2026. When a bot does the price comparison, every store needs a strategy engine — and every engine needs real outcomes to learn from.',
    sourceLabel: 'Shopify Q1 2026 earnings',
    sourceHref: 'https://www.pymnts.com/earnings/2026/ai-drove-orders-shopify-up-13-times-q1/',
  },
};
