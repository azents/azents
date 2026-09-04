FROM node:24-alpine@sha256:e67514e5d0f6c46656005e1b693b2ec9d52e80b641307de684d4a015ba7a4eaf AS base

ARG ROOT_DIR=/app

# --- pruner: extract only the required workspaces with turbo prune ---
FROM base AS pruner

RUN npm install -g turbo@2.10.12
WORKDIR ${ROOT_DIR}/typescript

COPY typescript/ .
RUN turbo prune @azents/admin-web --docker

# --- deps: install dependencies using the pruned lockfile ---
FROM base AS deps

RUN corepack enable && corepack prepare pnpm@11.1.0 --activate
WORKDIR ${ROOT_DIR}/typescript

# Copy the minimal package.json files and pruned lockfile produced by turbo prune
COPY --from=pruner ${ROOT_DIR}/typescript/out/json/ .

RUN pnpm install --frozen-lockfile

# --- builder: build the application ---
FROM base AS builder

RUN corepack enable && corepack prepare pnpm@11.1.0 --activate
WORKDIR ${ROOT_DIR}/typescript

# Copy dependencies
COPY --from=deps ${ROOT_DIR}/typescript/ .

# Copy source code for only the packages selected by turbo prune
COPY --from=pruner ${ROOT_DIR}/typescript/out/full/ .

# Copy root configuration files excluded from turbo prune
COPY typescript/tsconfig.base.json ./

# Copy OpenAPI specs for client code generation
COPY python/apps/azents/specs/ ${ROOT_DIR}/python/apps/azents/specs/

# Copy the previous Next.js build cache injected by CI with --build-context next-cache=...
COPY --from=next-cache /next-cache/ ./apps/azents-admin-web/.next/cache/

# Inject server-only environment variables at runtime; build-time arguments are unnecessary
RUN pnpm run build --filter=@azents/admin-web

# --- cache-export: export the Next.js build cache ---
FROM scratch AS cache-export
COPY --from=builder /app/typescript/apps/azents-admin-web/.next/cache/ /next-cache/

# --- runner: production runtime ---
FROM base AS runner

ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

# Copy the Next.js standalone output
COPY --from=builder --chown=nextjs:nodejs ${ROOT_DIR}/typescript/apps/azents-admin-web/.next/standalone ${ROOT_DIR}/

WORKDIR ${ROOT_DIR}/apps/azents-admin-web

COPY --from=builder --chown=nextjs:nodejs ${ROOT_DIR}/typescript/apps/azents-admin-web/.next/static ./.next/static

USER nextjs

EXPOSE 3000

CMD ["node", "server.js"]
