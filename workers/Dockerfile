FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the workers package into a workers/ subdirectory so it is importable as `workers.*`
# The build context is ./workers, so COPY . copies its contents into /app/workers/
COPY . ./workers/

RUN adduser --disabled-password --gecos "" appuser && chown -R appuser /app
USER appuser

CMD ["celery", "-A", "workers.celery_app", "worker", "--loglevel=info", "--concurrency=4"]
