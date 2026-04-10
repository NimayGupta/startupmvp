FROM python:3.11-slim

WORKDIR /app

# Install curl for health check probes
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the engine package into an engine/ subdirectory so it is importable as `engine.*`
# The build context is ./engine, so COPY . copies its contents into /app/engine/
COPY . ./engine/

# Non-root user for security
RUN adduser --disabled-password --gecos "" appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "engine.main:app", "--host", "0.0.0.0", "--port", "8000"]
