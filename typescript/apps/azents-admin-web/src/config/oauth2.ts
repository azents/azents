import { z } from "zod";
import type { ServerConfig } from "./server";

const tokenResponseSchema = z.object({
  access_token: z.string(),
  token_type: z.string(),
  expires_in: z.number(),
});

interface CachedToken {
  accessToken: string;
  expiresAt: number;
}

let tokenCache: CachedToken | null = null;

export async function getAccessToken(
  config: ServerConfig,
): Promise<string | null> {
  if (config.apiAuthMethod !== "oauth2") {
    return null;
  }

  // Return cached token if still valid (with 60s buffer)
  if (tokenCache && tokenCache.expiresAt > Date.now() + 60000) {
    return tokenCache.accessToken;
  }

  const response = await fetch(config.oauth2TokenUrl, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: new URLSearchParams({
      grant_type: "client_credentials",
      client_id: config.oauth2ClientId,
      client_secret: config.oauth2ClientSecret,
    }),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(
      `OAuth2 token request failed: ${response.status} ${errorText}`,
    );
  }

  const data = tokenResponseSchema.parse(await response.json());

  tokenCache = {
    accessToken: data.access_token,
    expiresAt: Date.now() + data.expires_in * 1000,
  };

  return tokenCache.accessToken;
}
