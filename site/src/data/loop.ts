/** The four steps of the closed loop, shown in #loop. */

export interface LoopStep {
  n: string;
  title: string;
  body: string;
}

export const loop: LoopStep[] = [
  {
    n: '01',
    title: 'Propose',
    body: 'The engine reads margins, velocity, and price-response signals across your catalog, then proposes the one move most worth testing.',
  },
  {
    n: '02',
    title: 'Test in checkout',
    body: 'The move runs as a controlled A/B experiment on live traffic. Shoppers vote with orders, not surveys.',
  },
  {
    n: '03',
    title: 'Prove the lift',
    body: 'A Bayesian monitor watches profit per visitor and concludes only when the lift is causal — not noise, not seasonality.',
  },
  {
    n: '04',
    title: 'Keep or revert',
    body: 'Winners roll out to everyone. Losers revert automatically. Both land in the ledger, with the outcome attached.',
  },
];
