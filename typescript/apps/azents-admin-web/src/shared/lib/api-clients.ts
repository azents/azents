import "server-only";
import {
  type Client as AdminApiClient,
  createClient as createAdminClient,
  createConfig as createAdminConfig,
} from "@azents/admin-client";
import {
  createClient as createPublicClient,
  createConfig as createPublicConfig,
  type Client as PublicApiClient,
} from "@azents/public-client";
import { getServerConfig } from "@/config/server";

export function createPublicApiClient(): PublicApiClient {
  return createPublicClient(
    createPublicConfig({
      baseUrl: getServerConfig().publicApiUrl,
    }),
  );
}

export function createAuthenticatedPublicApiClient(
  accessToken: string,
): PublicApiClient {
  return createPublicClient(
    createPublicConfig({
      baseUrl: getServerConfig().publicApiUrl,
      headers: {
        Authorization: `Bearer ${accessToken}`,
      },
    }),
  );
}

export function createBootstrapAdminApiClient(): AdminApiClient {
  return createAdminClient(
    createAdminConfig({
      baseUrl: getServerConfig().adminApiUrl,
    }),
  );
}

export function createAdminApiClient(accessToken: string): AdminApiClient {
  return createAdminClient(
    createAdminConfig({
      baseUrl: getServerConfig().adminApiUrl,
      headers: {
        Authorization: `Bearer ${accessToken}`,
      },
    }),
  );
}
