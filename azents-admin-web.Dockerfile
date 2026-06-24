FROM public.ecr.aws/docker/library/node:24-alpine AS base

ARG ROOT_DIR=/app

# --- pruner: turbo prune으로 필요한 워크스페이스만 추출 ---
FROM base AS pruner

RUN npm install -g turbo@2.9.14
WORKDIR ${ROOT_DIR}/typescript

COPY typescript/ .
RUN turbo prune @azents/admin-web --docker

# --- deps: 의존성 설치 (pruned lockfile 사용) ---
FROM base AS deps

RUN corepack enable && corepack prepare pnpm@11.1.0 --activate
WORKDIR ${ROOT_DIR}/typescript

# turbo prune으로 추출한 최소 package.json + pruned lockfile 복사
COPY --from=pruner ${ROOT_DIR}/typescript/out/json/ .

RUN pnpm install --frozen-lockfile

# --- builder: 빌드 ---
FROM base AS builder

RUN corepack enable && corepack prepare pnpm@11.1.0 --activate
WORKDIR ${ROOT_DIR}/typescript

# 의존성 복사
COPY --from=deps ${ROOT_DIR}/typescript/ .

# 소스 코드 복사 (turbo prune으로 추출한 필요 패키지만)
COPY --from=pruner ${ROOT_DIR}/typescript/out/full/ .

# turbo prune에 포함되지 않는 루트 설정 파일
COPY typescript/tsconfig.base.json ./

# OpenAPI spec 복사 (클라이언트 코드 생성용)
COPY python/apps/azents/specs/ ${ROOT_DIR}/python/apps/azents/specs/

# 이전 빌드의 Next.js 캐시 복사 (CI에서 --build-context next-cache=... 로 주입)
COPY --from=next-cache /next-cache/ ./apps/azents-admin-web/.next/cache/

# 환경변수는 서버 사이드 전용이므로 런타임에 주입 (빌드 타임 ARG 불필요)
RUN pnpm run build --filter=@azents/admin-web

# --- cache-export: Next.js 빌드 캐시 내보내기 ---
FROM scratch AS cache-export
COPY --from=builder /app/typescript/apps/azents-admin-web/.next/cache/ /next-cache/

# --- runner: 프로덕션 런타임 ---
FROM base AS runner

ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

# Next.js standalone output 복사
COPY --from=builder --chown=nextjs:nodejs ${ROOT_DIR}/typescript/apps/azents-admin-web/.next/standalone ${ROOT_DIR}/

WORKDIR ${ROOT_DIR}/apps/azents-admin-web

COPY --from=builder --chown=nextjs:nodejs ${ROOT_DIR}/typescript/apps/azents-admin-web/.next/static ./.next/static

USER nextjs

EXPOSE 3000

CMD ["node", "server.js"]
