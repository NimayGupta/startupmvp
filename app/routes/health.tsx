/**
 * Health check endpoint for the Remix app.
 * Used by Docker Compose health checks and load balancers.
 * GET /health → { status: "ok", db_connected: boolean }
 */

import type { LoaderFunctionArgs } from "@remix-run/node";
import { db } from "~/lib/db.server";

export const loader = async (_args: LoaderFunctionArgs) => {
  let dbConnected = false;

  try {
    await db.query("SELECT 1");
    dbConnected = true;
  } catch {
    // DB unreachable
  }

  return Response.json(
    { status: dbConnected ? "ok" : "degraded", db_connected: dbConnected },
    {
      status: dbConnected ? 200 : 503,
      headers: { "Content-Type": "application/json" },
    }
  );
};
