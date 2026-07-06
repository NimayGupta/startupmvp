# Deploying the Margent marketing site

The site is fully static (`npm run build` → `dist/`). Both configs live in
this folder. Before the first deploy, do the **pre-flight** list at the
bottom.

## Vercel

1. Import the GitHub repo in Vercel.
2. Settings → General:
   - **Root Directory**: `site`
   - Framework preset: Astro (auto-detected; `vercel.json` pins it)
3. Optional: add env var `PUBLIC_FORM_ENDPOINT` (Project → Settings →
   Environment Variables) to switch the waitlist band from mailto to the
   capture form.
4. Deploy. Every push touching `site/` on the connected branch redeploys.

CLI alternative:

```bash
cd site
npx vercel          # first run links the project; set root dir = .
npx vercel --prod
```

## Netlify

1. New site from Git.
2. Build settings:
   - **Base directory**: `site`
   - Build command: `npm run build`
   - Publish directory: `site/dist`
   (`netlify.toml` supplies command/publish when base is `site`.)
3. Optional env var `PUBLIC_FORM_ENDPOINT` (Site configuration →
   Environment variables). Note: if you use Netlify, consider Netlify Forms
   instead — add `data-netlify="true"` to the form and drop the env var.
4. Deploy.

CLI alternative:

```bash
cd site
npm run build
npx netlify deploy --dir=dist          # preview
npx netlify deploy --dir=dist --prod
```

## Custom domain

1. Buy/choose the domain (e.g. `margent.com`).
2. **Update the code first** (see pre-flight), then:
   - **Vercel**: Project → Settings → Domains → add domain. Point DNS:
     apex `A 76.76.21.21`, `www` CNAME `cname.vercel-dns.com` (Vercel shows
     the exact records).
   - **Netlify**: Domain management → add domain. Point DNS: apex
     ALIAS/ANAME to `apex-loadbalancer.netlify.com` (or Netlify DNS),
     `www` CNAME `<site>.netlify.app`.
3. Both hosts issue TLS automatically; force-HTTPS is on by default.

## Pre-flight (required before going public)

- [ ] Replace `margent.example.com` in `astro.config.mjs` (drives OG URLs +
      sitemap) and in `public/robots.txt`.
- [ ] Replace `hello@margent.example.com` and `margent.example.com` in
      `src/data/site.ts`.
- [ ] Work through the launch checklist in `CLAIMS.md`.
- [ ] Optionally set `PUBLIC_FORM_ENDPOINT` and submit one real test lead.
- [ ] Regenerate the OG image if branding changed: `node scripts/make-og.mjs`.
