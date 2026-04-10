# NOTE: This Dockerfile is used for Docker Compose (production-like local dev).
# For development, run `shopify app dev` directly — it handles the tunnel and HMR.

FROM node:20-slim AS base
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# --- Dependencies ---
FROM base AS deps
COPY package*.json ./
RUN npm ci --only=production

# --- Build ---
FROM base AS build
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# --- Production image ---
FROM base AS runner
ENV NODE_ENV=production

RUN adduser --disabled-password --gecos "" appuser

COPY --from=deps /app/node_modules ./node_modules
COPY --from=build /app/build ./build
COPY --from=build /app/public ./public
COPY package.json ./

RUN chown -R appuser /app
USER appuser

EXPOSE 3000

CMD ["npm", "run", "start"]
