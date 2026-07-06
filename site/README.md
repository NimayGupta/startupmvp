# Margent — marketing site

The public marketing site for Margent, the commerce decision engine.
Static Astro site, plain CSS, self-hosted fonts, near-zero shipped JS.

This folder is standalone: it has its own `package.json` and lockfile and is
**not** part of the repo's npm workspaces. Always run npm commands from inside
`site/`.

## Run it

```bash
cd site
npm ci
npm run dev        # http://localhost:4321
npm run build      # static output in dist/
npm run preview    # serve the built site
```

## Where things live

| What | Where |
|------|-------|
| All copy (nav, hero, footer, contact email) | `src/data/site.ts` |
| Features, loop steps, roadmap, moat content | `src/data/*.ts` (Stage 2) |
| Design tokens (colors, type, spacing) | `src/styles/tokens.css` |
| Global reset + typography | `src/styles/global.css` |
| Page sections | `src/components/*.astro` |
| Claim/stat provenance | `CLAIMS.md` |

To change copy, edit the data files — the markup pulls everything from them.

## Design system

Two surfaces, warm near-black (`--ink`) and warm off-white (`--paper`),
alternating down the page. Components never hardcode surface colors; each
`<section>` gets a band class (`band--ink`, `band--paper`, `band--paper-2`)
that sets contextual vars (`--bg`, `--fg`, `--muted`, `--line`, `--accent`),
and components read only those.

Type: Fraunces (display, variable w/ optical sizing), Inter (body, variable),
IBM Plex Mono (data/ledger). All self-hosted via @fontsource — no network
font requests.

## Deploy

Static host. Configs for both Vercel (`vercel.json`) and Netlify
(`netlify.toml`) are included; point the project's root/base directory at
`site/`. Full steps land in `DEPLOY.md` (Stage 5).

CI: `.github/workflows/site-ci.yml` builds the site on any change under
`site/**`. The app's CI/deploy workflows ignore `site/**`.
