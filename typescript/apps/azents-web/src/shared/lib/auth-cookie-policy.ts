export interface AuthCookieNames {
  ACCESS_TOKEN: string;
  REFRESH_TOKEN: string;
  EXPIRES_AT: string;
}

export interface AuthCookiePolicy {
  names: AuthCookieNames;
  secure: boolean;
  sameSite: "lax" | "none";
}

export type AuthCookiePolicyMode = "default" | "testenv_legacy";

const LOCAL_COOKIE_NAMES: AuthCookieNames = {
  ACCESS_TOKEN: "az-token",
  REFRESH_TOKEN: "az-refresh",
  EXPIRES_AT: "az-token-expires-at",
};

const PRODUCTION_COOKIE_NAMES: AuthCookieNames = {
  ACCESS_TOKEN: "__Host-Azents-Access",
  REFRESH_TOKEN: "__Host-Azents-Refresh",
  EXPIRES_AT: "__Host-Azents-Access-Expires-At",
};

export function authCookiePolicy(
  nodeEnv: "development" | "production" | "test",
  mode: AuthCookiePolicyMode = "default",
): AuthCookiePolicy {
  if (mode === "testenv_legacy") {
    return {
      names: LOCAL_COOKIE_NAMES,
      secure: true,
      sameSite: "lax",
    };
  }
  return nodeEnv === "production"
    ? {
        names: PRODUCTION_COOKIE_NAMES,
        secure: true,
        sameSite: "none",
      }
    : {
        names: LOCAL_COOKIE_NAMES,
        secure: false,
        sameSite: "lax",
      };
}
