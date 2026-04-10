/**
 * PostgreSQL connection pool for application data.
 *
 * Prisma (SQLite) handles OAuth session storage.
 * This pool handles all merchant/product/order/event application data.
 *
 * Uses the `pg` (node-postgres) package.
 * Global singleton prevents multiple pools during Remix dev hot-reloads.
 * All queries must use parameterised statements — never string interpolation.
 */

import { Pool } from "pg";

declare global {
  // eslint-disable-next-line no-var
  var __pgPool: Pool | undefined;
}

function createPool(): Pool {
  const pool = new Pool({
    connectionString:
      process.env.DATABASE_URL ??
      "postgres://postgres:postgres@localhost:5432/discount_optimizer",
    max: 10,
    idleTimeoutMillis: 30_000,
    connectionTimeoutMillis: 5_000,
  });

  pool.on("error", (err) => {
    console.error("[pg] Unexpected pool error:", err);
  });

  return pool;
}

export const pgPool: Pool =
  global.__pgPool ?? (global.__pgPool = createPool());

/**
 * Run a parameterised SQL query and return typed rows.
 * Always use $1, $2, ... placeholders — never string interpolation.
 */
export async function query<T extends object>(
  sql: string,
  params?: unknown[],
): Promise<T[]> {
  const result = await pgPool.query<T>(sql, params);
  return result.rows;
}
