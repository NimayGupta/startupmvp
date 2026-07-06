/**
 * Data model + content pools for the hero decision ledger.
 * Everything here is ILLUSTRATIVE — a simulated preview of the product's
 * ledger, clearly labeled as such in the UI. Tune pools for realism.
 */

export type LedgerStatus = 'testing' | 'kept' | 'reverted';

export interface LedgerRow {
  sku: string;
  action: string;
  status: LedgerStatus;
  /** Profit delta vs control, e.g. '+2.4%'. Em dash while testing. */
  delta: string;
  /** Posterior probability the move beats control, e.g. '0.97'. */
  confidence: string;
}

export const statusLabels: Record<LedgerStatus, string> = {
  testing: 'testing',
  kept: 'kept',
  reverted: 'reverted',
};

/** Rendered server-side so the panel is complete without JS. */
export const seededRows: LedgerRow[] = [
  { sku: 'SKU-8841', action: 'lower 8%', status: 'kept', delta: '+2.4%', confidence: '0.97' },
  { sku: 'SKU-2210', action: 'raise 5%', status: 'testing', delta: '—', confidence: '0.71' },
  { sku: 'SKU-0937', action: 'bundle offer', status: 'reverted', delta: '−1.1%', confidence: '0.94' },
  { sku: 'SKU-5512', action: 'raise 3%', status: 'kept', delta: '+1.8%', confidence: '0.96' },
  { sku: 'SKU-7703', action: 'free shipping', status: 'testing', delta: '—', confidence: '0.58' },
  { sku: 'SKU-1189', action: 'lower 12%', status: 'kept', delta: '+3.1%', confidence: '0.99' },
];

/** Pools the client script draws from when streaming new rows (Stage 3). */
export const pools = {
  skuRange: [1000, 9899] as const,
  actions: [
    'raise 3%',
    'raise 5%',
    'raise 7%',
    'lower 5%',
    'lower 8%',
    'lower 12%',
    'bundle offer',
    'free shipping',
    'promo 10%',
    'hold price',
  ],
};

/** Footer counters. Also illustrative; the panel is labeled simulated. */
export const counters = {
  experimentsLabel: 'experiments concluded',
  netLiftLabel: 'net profit lift',
  experiments: 1284,
  netLift: '+11.2%',
};
