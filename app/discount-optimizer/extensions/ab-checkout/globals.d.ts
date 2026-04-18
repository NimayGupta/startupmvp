/**
 * Build-time constants injected by Shopify CLI / Vite define.
 * During `shopify app dev` the CLI sets __BACKEND_URL__ to the ngrok tunnel URL.
 * During `shopify app deploy` it is set to the production app URL.
 */
declare const __BACKEND_URL__: string;
