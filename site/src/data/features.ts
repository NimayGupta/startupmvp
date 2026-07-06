/** Feature grid content for #features. Icons map to names in Icon.astro. */

export type FeatureStatus = 'live' | 'rolling-out' | 'roadmap';

export interface Feature {
  icon: string;
  title: string;
  body: string;
  status: FeatureStatus;
}

export const statusLabels: Record<FeatureStatus, string> = {
  live: 'Live',
  'rolling-out': 'Rolling out',
  roadmap: 'Roadmap',
};

export const features: Feature[] = [
  {
    icon: 'flask',
    title: 'Bayesian price experiments',
    body: 'Every move ships as a controlled experiment with a stopping rule that knows when the evidence is in — no p-hacking, no eyeballing dashboards.',
    status: 'live',
  },
  {
    icon: 'pulse',
    title: 'Causal profit monitor',
    body: 'Lift is measured against a concurrent control, in profit that actually happened — not before-and-after guesswork.',
    status: 'live',
  },
  {
    icon: 'sparkle',
    title: 'Autonomous proposals',
    body: 'Margent reads your catalog and order history and queues the next test worth running, with the reasoning attached.',
    status: 'live',
  },
  {
    icon: 'bag',
    title: 'Native checkout testing',
    body: 'A Shopify checkout extension runs the test where the decision actually happens — no redirect scripts, no flicker.',
    status: 'live',
  },
  {
    icon: 'rows',
    title: 'Append-only decision ledger',
    body: 'Every proposal, approval, experiment, and outcome, recorded in order and never rewritten. Your pricing history becomes an asset.',
    status: 'live',
  },
  {
    icon: 'chat',
    title: 'Decisions that explain themselves',
    body: 'Every proposal comes with a plain-language explanation: the signal behind it, the expected lift, and the risk if it’s wrong.',
    status: 'live',
  },
  {
    icon: 'shield',
    title: 'Trust scores on every decision',
    body: 'Each recommendation carries a score built from the engine’s track record on your store. You set the bar for what ships without a click.',
    status: 'rolling-out',
  },
  {
    icon: 'split',
    title: 'Bandit traffic allocation',
    body: 'A Thompson-sampling bandit leans traffic toward likely winners while the experiment runs, so testing costs less margin.',
    status: 'rolling-out',
  },
];
