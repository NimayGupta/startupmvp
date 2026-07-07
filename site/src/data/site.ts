/**
 * Single source of site-wide copy: nav, hero, CTAs, footer, contact.
 * Edit this file to change text anywhere in the chrome of the site.
 */

export interface NavLink {
  label: string;
  href: string;
}

export interface FooterColumn {
  title: string;
  links: { label: string; href: string }[];
}

/** Where every "Request access" CTA points (early-access signup form). */
const REQUEST_ACCESS_URL =
  'https://docs.google.com/forms/d/e/1FAIpQLSc5OPbck8DmZjfN7ZcG6hGI2K7YAe7d4PytWCF4FKSeUc7M-w/viewform?usp=header';

export const site = {
  name: 'Margent',
  requestAccessUrl: REQUEST_ACCESS_URL,
  title: 'Margent — the commerce decision engine',
  description:
    'Margent runs pricing and promotion decisions for Shopify stores as a closed loop — propose, test in checkout, prove causal profit lift, keep winners. Every decision and its real outcome lands in an append-only ledger.',
  url: 'https://margent.example.com', // TODO: real domain before launch
  contactEmail: 'hello@margent.example.com', // TODO: real email before launch

  nav: [
    { label: 'The loop', href: '#loop' },
    { label: 'Features', href: '#features' },
    { label: 'The ledger', href: '#moat' },
    { label: 'Roadmap', href: '#coming' },
  ] satisfies NavLink[],

  cta: {
    label: 'Request access',
    href: REQUEST_ACCESS_URL,
  },

  hero: {
    kicker: 'Commerce decision engine',
    title: 'Pricing, run as a closed loop.',
    lede: 'Margent proposes a price move, tests it in your real checkout, proves the profit lift is causal, and keeps only what wins. Losers revert on their own. Every decision — and what it actually earned — lands in an append-only ledger.',
    primaryCta: { label: 'Request access', href: REQUEST_ACCESS_URL },
    secondaryCta: { label: 'See the loop', href: '#loop' },
  },

  waitlist: {
    kicker: 'Early access',
    title: 'Run your pricing as a loop.',
    body: 'Margent is onboarding a small set of Shopify stores. Early stores shape the roadmap and get founding terms.',
    ctaLabel: 'Request access',
  },

  footer: {
    tagline: 'Pricing, run as a closed loop.',
    columns: [
      {
        title: 'Product',
        links: [
          { label: 'The loop', href: '#loop' },
          { label: 'Features', href: '#features' },
          { label: 'Roadmap', href: '#coming' },
          { label: 'Request access', href: REQUEST_ACCESS_URL },
        ],
      },
      {
        title: 'Company',
        links: [
          { label: 'The decision ledger', href: '#moat' },
          { label: 'Contact', href: 'mailto:hello@margent.example.com' },
        ],
      },
      {
        title: 'Built on',
        links: [
          { label: 'Shopify checkout', href: '#features' },
          { label: 'Bayesian experiments', href: '#loop' },
          { label: 'An append-only ledger', href: '#moat' },
        ],
      },
    ] satisfies FooterColumn[],
    note: '© 2026 Margent. All decisions recorded.',
  },
};
