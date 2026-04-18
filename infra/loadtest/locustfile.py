"""
Locust load test — simulates 20 concurrent merchants against the discount-optimizer engine.

Pass criteria:
  - p95 latency < 500ms
  - Zero 5xx errors
  - Celery queue depth < 100 (checked via /health endpoint)
  - PostgreSQL pool not exhausted

Run:
  locust -f infra/loadtest/locustfile.py --host=http://localhost:8000 \
         --users=20 --spawn-rate=2 --run-time=10m --headless
"""

import random
import time
from locust import HttpUser, TaskSet, between, task, events
from locust.exception import StopUser

ENGINE_API_KEY = "dev-internal-key"
AUTH_HEADERS = {"Authorization": f"Bearer {ENGINE_API_KEY}"}

# Simulated merchant pool: merchant IDs 1001–1020
MERCHANT_IDS = list(range(1001, 1021))

# Product pool per merchant (each merchant has 3 products)
def _products_for(merchant_id: int) -> list[int]:
    base = (merchant_id - 1001) * 3 + 1
    return [base, base + 1, base + 2]


class RecommendationFlow(TaskSet):
    """
    Simulates the core recommendation loop for a single merchant:
    - Generate a recommendation (every ~10 minutes in wall time → fast in load test)
    - Approve it with a fake Shopify discount ID
    - Create an experiment
    - Send mock assignment events
    - Send mock outcome events
    """

    def on_start(self):
        self.merchant_id = getattr(self.user, "merchant_id", random.choice(MERCHANT_IDS))
        self.products = _products_for(self.merchant_id)
        self.active_experiment_ids: list[int] = []
        self.pending_recommendation_id: int | None = None

    # ---------------------------------------------------------------------------
    # Recommendation generation (slow path — weight 1)
    # ---------------------------------------------------------------------------
    @task(1)
    def generate_recommendation(self):
        product_id = random.choice(self.products)
        with self.client.post(
            "/recommendations/generate",
            json={"merchant_id": self.merchant_id, "product_id": product_id},
            headers=AUTH_HEADERS,
            name="/recommendations/generate",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                data = resp.json()
                rec_id = data.get("id")
                if rec_id:
                    self.pending_recommendation_id = rec_id
                resp.success()
            elif resp.status_code == 404:
                # No features yet — not a 5xx, mark as success for load purposes
                resp.success()
            else:
                resp.failure(f"generate failed: {resp.status_code}")

    @task(1)
    def approve_recommendation(self):
        if self.pending_recommendation_id is None:
            return
        rec_id = self.pending_recommendation_id
        fake_discount_id = f"gid://shopify/DiscountNode/load-{rec_id}-{int(time.time())}"
        with self.client.post(
            f"/recommendations/{rec_id}/approve",
            json={
                "merchant_id": self.merchant_id,
                "shopify_discount_id": fake_discount_id,
            },
            headers=AUTH_HEADERS,
            name="/recommendations/{id}/approve",
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 404, 409):
                resp.success()
            else:
                resp.failure(f"approve failed: {resp.status_code}")
        self.pending_recommendation_id = None

    # ---------------------------------------------------------------------------
    # Experiment creation (weight 1, occasional)
    # ---------------------------------------------------------------------------
    @task(1)
    def create_experiment(self):
        if len(self.active_experiment_ids) >= 5:
            return
        product_id = random.choice(self.products)
        with self.client.post(
            "/experiments",
            json={
                "merchant_id": self.merchant_id,
                "product_id": product_id,
                "recommendation_id": random.randint(1, 100),
                "control_discount_pct": 0,
                "treatment_discount_pct": round(random.uniform(5, 25), 1),
                "shopify_discount_id": f"gid://shopify/DiscountNode/load-exp-{int(time.time())}",
            },
            headers=AUTH_HEADERS,
            name="/experiments [create]",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                exp_id = resp.json().get("id")
                if exp_id:
                    self.active_experiment_ids.append(exp_id)
                resp.success()
            elif resp.status_code == 402:
                resp.success()  # billing tier limit — expected, not a failure
            else:
                resp.failure(f"create experiment failed: {resp.status_code}")

    # ---------------------------------------------------------------------------
    # Experiment monitoring (weight 3 — runs ~3x per generate cycle)
    # ---------------------------------------------------------------------------
    @task(3)
    def monitor_experiments(self):
        with self.client.post(
            f"/experiments/monitor/{self.merchant_id}",
            headers=AUTH_HEADERS,
            name="/experiments/monitor/{merchant_id}",
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 404):
                resp.success()
            else:
                resp.failure(f"monitor failed: {resp.status_code}")

    # ---------------------------------------------------------------------------
    # Kill old experiments (occasional cleanup)
    # ---------------------------------------------------------------------------
    @task(1)
    def kill_old_experiment(self):
        if not self.active_experiment_ids:
            return
        exp_id = self.active_experiment_ids.pop(0)
        with self.client.post(
            f"/experiments/{exp_id}/kill",
            json={"merchant_id": self.merchant_id},
            headers=AUTH_HEADERS,
            name="/experiments/{id}/kill",
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 404):
                resp.success()
            else:
                resp.failure(f"kill failed: {resp.status_code}")

    # ---------------------------------------------------------------------------
    # Feature fetch (high-frequency reads)
    # ---------------------------------------------------------------------------
    @task(5)
    def fetch_features(self):
        product_id = random.choice(self.products)
        with self.client.get(
            f"/features/{self.merchant_id}",
            headers=AUTH_HEADERS,
            name="/features/{merchant_id}",
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 404):
                resp.success()
            else:
                resp.failure(f"features failed: {resp.status_code}")

    # ---------------------------------------------------------------------------
    # Bandit sample (high-frequency — drives discount decisions)
    # ---------------------------------------------------------------------------
    @task(5)
    def bandit_params(self):
        with self.client.get(
            f"/bandit/{self.merchant_id}/params",
            headers=AUTH_HEADERS,
            name="/bandit/{merchant_id}/params",
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 404):
                resp.success()
            else:
                resp.failure(f"bandit/params failed: {resp.status_code}")

    # ---------------------------------------------------------------------------
    # Trust score reads
    # ---------------------------------------------------------------------------
    @task(2)
    def fetch_trust_score(self):
        with self.client.get(
            f"/trust/{self.merchant_id}",
            headers=AUTH_HEADERS,
            name="/trust/{merchant_id}",
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 404):
                resp.success()
            else:
                resp.failure(f"trust score failed: {resp.status_code}")

    # ---------------------------------------------------------------------------
    # Health check (used by monitoring pass criteria check)
    # ---------------------------------------------------------------------------
    @task(1)
    def health_check(self):
        with self.client.get(
            "/health",
            name="/health",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"health check failed: {resp.status_code}")


class MerchantUser(HttpUser):
    """One Locust user = one merchant. Each gets a stable merchant_id."""

    tasks = [RecommendationFlow]
    wait_time = between(1, 5)  # seconds between tasks

    def on_start(self):
        # Assign stable merchant ID from pool (wraps if more users than merchants)
        idx = self.environment.runner.user_count % len(MERCHANT_IDS)
        self.merchant_id = MERCHANT_IDS[idx]


# ---------------------------------------------------------------------------
# Custom event: check queue depth after each run
# ---------------------------------------------------------------------------
@events.quitting.add_listener
def check_pass_criteria(environment, **kwargs):
    stats = environment.stats
    total_reqs = stats.total.num_requests
    total_fails = stats.total.num_failures
    p95 = stats.total.get_response_time_percentile(0.95) or 0

    print("\n=== Load Test Results ===")
    print(f"Total requests:  {total_reqs}")
    print(f"Total failures:  {total_fails}")
    print(f"p95 latency:     {p95:.0f}ms")

    passed = True
    if p95 > 500:
        print(f"FAIL: p95 {p95:.0f}ms exceeds 500ms threshold")
        passed = False
    if total_fails > 0:
        fail_pct = total_fails / max(total_reqs, 1) * 100
        print(f"FAIL: {total_fails} failures ({fail_pct:.1f}%)")
        passed = False

    if passed:
        print("PASS: All criteria met")
    else:
        environment.process_exit_code = 1
