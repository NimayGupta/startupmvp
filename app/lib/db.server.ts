/**
 * PostgreSQL connection pool for the Remix app.
 *
 * Uses the `pg` package (node-postgres). The pool is created once at module
 * load time and reused across all requests.
 *
 * All queries must use parameterised statements — never string interpolation.
 */

import { Pool } from "pg";

declare global {
  // Prevent multiple pool instances in development hot-reload
  // eslint-disable-next-line no-var
  var __pgPool: Pool | undefined;
}

function createPool(): Pool {
  const pool = new Pool({
    connectionString: process.env.DATABASE_URL,
    max: 10,
    idleTimeoutMillis: 30_000,
    connectionTimeoutMillis: 5_000,
  });

  pool.on("error", (err) => {
    console.error("Unexpected PostgreSQL pool error:", err);
  });

  return pool;
}

export const db: Pool = global.__pgPool ?? (global.__pgPool = createPool());
