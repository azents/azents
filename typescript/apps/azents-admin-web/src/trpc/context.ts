/**
 * tRPC Context
 *
 * azents admin API와 통신하기 위한 API 클라이언트 설정.
 * OAuth2 인증이 설정된 경우 Bearer 토큰을 자동으로 추가.
 */
import { type Client, createClient, createConfig } from "@azents/admin-client";
import { getAccessToken } from "@/config/oauth2";
import { getServerConfig, type ServerConfig } from "@/config/server";
import { withApiErrorInterceptor } from "./api-error";

export interface Context {
  adminApiClient: Client;
}

/**
 * Admin API 클라이언트 생성
 *
 * OAuth2 인증이 설정된 경우 Bearer 토큰을 헤더에 추가.
 * ALB에서 JWT 검증을 수행하므로 유효한 토큰이 필요.
 */
async function getAdminApiClient(config: ServerConfig): Promise<Client> {
  const accessToken = await getAccessToken(config);

  const clientConfig = createConfig({
    baseUrl: config.adminApiUrl,
  });

  // OAuth2 토큰이 있으면 Authorization 헤더 추가
  if (accessToken) {
    clientConfig.headers = {
      ...clientConfig.headers,
      Authorization: `Bearer ${accessToken}`,
    };
  }

  return withApiErrorInterceptor(createClient(clientConfig));
}

/**
 * Context 생성 함수 (async)
 * - HTTP 요청이 있을 때마다 호출됨
 */
export async function createContext(): Promise<Context> {
  const config = getServerConfig();

  return {
    adminApiClient: await getAdminApiClient(config),
  };
}

/**
 * Server-side caller용 context 생성
 * - Server Component에서 직접 호출할 때 사용
 */
export async function createServerContext(): Promise<Context> {
  return createContext();
}
