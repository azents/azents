FROM public.ecr.aws/docker/library/node:24-alpine AS base

ARG ROOT_DIR=/app

FROM base AS pruner

RUN npm install -g turbo@2.9.14
WORKDIR ${ROOT_DIR}/typescript

COPY typescript/ .
RUN turbo prune @azents/site --docker

FROM base AS deps

RUN corepack enable && corepack prepare pnpm@11.1.0 --activate
WORKDIR ${ROOT_DIR}/typescript

COPY --from=pruner ${ROOT_DIR}/typescript/out/json/ .

RUN pnpm install --frozen-lockfile

FROM base AS builder

RUN corepack enable && corepack prepare pnpm@11.1.0 --activate
WORKDIR ${ROOT_DIR}/typescript

COPY --from=deps ${ROOT_DIR}/typescript/ .
COPY --from=pruner ${ROOT_DIR}/typescript/out/full/ .
COPY typescript/tsconfig.base.json ./
COPY --from=next-cache /next-cache/ ./apps/azents-site/.next/cache/

ARG CI=true

RUN pnpm run build --filter=@azents/site

FROM scratch AS cache-export
COPY --from=builder /app/typescript/apps/azents-site/.next/cache/ /next-cache/

FROM base AS runner

ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

COPY --from=builder --chown=nextjs:nodejs ${ROOT_DIR}/typescript/apps/azents-site/.next/standalone ${ROOT_DIR}/

WORKDIR ${ROOT_DIR}/apps/azents-site

COPY --from=builder --chown=nextjs:nodejs ${ROOT_DIR}/typescript/apps/azents-site/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs ${ROOT_DIR}/typescript/apps/azents-site/public ./public

USER nextjs

EXPOSE 3000

CMD ["node", "server.js"]
