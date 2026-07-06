/** Timeline rows for #coming. */

export type RoadmapStatus = 'now' | 'rolling-out' | 'next' | 'later';

export interface RoadmapRow {
  period: string;
  title: string;
  body: string;
  status: RoadmapStatus;
}

export const roadmap: RoadmapRow[] = [
  {
    period: 'Now',
    title: 'Closed-loop pricing on Shopify',
    body: 'Propose → test → prove → keep, live in checkout for a small set of stores. Private beta.',
    status: 'now',
  },
  {
    period: 'Rolling out',
    title: 'Cheaper tests, fewer clicks',
    body: 'Bandit traffic allocation that spends less margin per experiment, and trust-scored auto-approve for stores that want the loop fully closed.',
    status: 'rolling-out',
  },
  {
    period: 'Next',
    title: 'Promotions and offers',
    body: 'Discounts, bundles, and offer timing decided by the same loop that prices — proposed, tested, proven, kept.',
    status: 'next',
  },
  {
    period: 'Later',
    title: 'The environment',
    body: 'Licensed evaluation and training access to the outcome corpus, for labs and platforms building pricing agents.',
    status: 'later',
  },
];
