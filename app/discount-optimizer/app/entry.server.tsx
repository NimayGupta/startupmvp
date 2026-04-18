import { PassThrough } from "stream";
import { renderToPipeableStream } from "react-dom/server";
import { RemixServer } from "@remix-run/react";
import {
  createReadableStreamFromReadable,
  type EntryContext,
} from "@remix-run/node";
import { isbot } from "isbot";
import { addDocumentResponseHeaders } from "./shopify.server";

// ---------------------------------------------------------------------------
// Sentry (Phase 6B) — instrument Node.js server
// Only initialises when SENTRY_DSN is set; no-ops otherwise.
// ---------------------------------------------------------------------------
if (process.env.SENTRY_DSN) {
  // Dynamic import so Sentry isn't bundled when DSN is absent.
  import("@sentry/remix").then(({ init, httpIntegration }) => {
    init({
      dsn: process.env.SENTRY_DSN,
      environment: process.env.NODE_ENV ?? "development",
      integrations: [httpIntegration()],
      tracesSampleRate: process.env.NODE_ENV === "production" ? 0.1 : 1.0,
      beforeSend(event) {
        // Attach merchant ID context if available in extra
        return event;
      },
    });
  }).catch(console.error);
}

export const streamTimeout = 5000;

export default async function handleRequest(
  request: Request,
  responseStatusCode: number,
  responseHeaders: Headers,
  remixContext: EntryContext,
) {
  addDocumentResponseHeaders(request, responseHeaders);
  const userAgent = request.headers.get("user-agent");
  const callbackName = isbot(userAgent ?? "") ? "onAllReady" : "onShellReady";

  return new Promise((resolve, reject) => {
    const { pipe, abort } = renderToPipeableStream(
      <RemixServer context={remixContext} url={request.url} />,
      {
        [callbackName]: () => {
          const body = new PassThrough();
          const stream = createReadableStreamFromReadable(body);
          responseHeaders.set("Content-Type", "text/html");
          resolve(
            new Response(stream, {
              headers: responseHeaders,
              status: responseStatusCode,
            }),
          );
          pipe(body);
        },
        onShellError(error) {
          reject(error);
        },
        onError(error) {
          responseStatusCode = 500;
          console.error(error);
          // Report to Sentry if initialised
          if (process.env.SENTRY_DSN) {
            import("@sentry/remix").then(({ captureException }) => captureException(error)).catch(() => {});
          }
        },
      },
    );

    setTimeout(abort, streamTimeout + 1000);
  });
}
