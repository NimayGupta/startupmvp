// @ts-check
import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';

// https://astro.build/config
export default defineConfig({
  // TODO: replace with the real domain before launch (used for OG tags + sitemap)
  site: 'https://margent.example.com',
  output: 'static',
  integrations: [sitemap()],
});
