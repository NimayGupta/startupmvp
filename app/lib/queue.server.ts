/**
 * Celery task queue client for the Remix app.
 *
 * The Remix app needs to enqueue Celery tasks (e.g., webhook processing,
 * bulk sync) without importing Python code. We use Celery's Redis protocol
 * directly: each task is a JSON message pushed to a Redis list.
 *
 * This is the standard Celery message format v2 for tasks with JSON payload.
 */

import { createClient } from "redis";
import { randomUUID } from "crypto";

let redisClient: ReturnType<typeof createClient> | null = null;

async function getRedis(): Promise<ReturnType<typeof createClient>> {
  if (!redisClient) {
    redisClient = createClient({ url: process.env.REDIS_URL });
    redisClient.on("error", (err) => console.error("Redis client error:", err));
    await redisClient.connect();
  }
  return redisClient;
}

interface CeleryTaskOptions {
  taskName: string;
  args: unknown[];
  kwargs?: Record<string, unknown>;
  queue?: string;
}

/**
 * Enqueue a Celery task using the Celery v2 message protocol over Redis.
 *
 * @param taskName - Fully qualified Python task name, e.g. "workers.tasks.sync.bulk_sync_merchant"
 * @param args     - Positional arguments for the task
 * @param kwargs   - Keyword arguments for the task
 * @param queue    - Redis queue name (defaults to "celery")
 */
export async function enqueueTask({
  taskName,
  args,
  kwargs = {},
  queue = "celery",
}: CeleryTaskOptions): Promise<string> {
  const redis = await getRedis();
  const taskId = randomUUID();

  const message = JSON.stringify({
    id: taskId,
    task: taskName,
    args,
    kwargs,
    retries: 0,
    eta: null,
    expires: null,
    utc: true,
    callbacks: null,
    errbacks: null,
    timelimit: [null, null],
    taskset: null,
    chord: null,
    headers: {},
    body: Buffer.from(
      JSON.stringify([args, kwargs, { callbacks: null, errbacks: null, chain: null, chord: null }])
    ).toString("base64"),
    content_type: "application/json",
    content_encoding: "utf-8",
  });

  await redis.lPush(queue, message);
  return taskId;
}

/**
 * Convenience: enqueue the bulk sync task for a merchant after OAuth install.
 */
export async function enqueueBulkSync(merchantId: number): Promise<string> {
  return enqueueTask({
    taskName: "workers.tasks.sync.bulk_sync_merchant",
    args: [merchantId],
  });
}

/**
 * Convenience: enqueue a webhook processing task.
 */
export async function enqueueWebhookTask(
  topic: string,
  merchantId: number,
  payload: unknown
): Promise<string> {
  const topicToTask: Record<string, string> = {
    "orders/create": "workers.tasks.webhooks.process_orders_create",
    "products/update": "workers.tasks.webhooks.process_products_update",
    "inventory_levels/update": "workers.tasks.webhooks.process_inventory_update",
  };

  const taskName = topicToTask[topic];
  if (!taskName) {
    throw new Error(`No task registered for webhook topic: ${topic}`);
  }

  return enqueueTask({
    taskName,
    args: [merchantId, payload],
  });
}
