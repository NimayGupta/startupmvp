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

export const site = {
  name: 'Margent',
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
    href: '#waitlist',
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
          { label: 'Request access', href: '#waitlist' },
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
