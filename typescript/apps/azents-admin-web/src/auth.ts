import NextAuth from "next-auth";
import GitHub from "next-auth/providers/github";
import { z } from "zod";
import { getServerConfig } from "@/config/server";

const REQUIRED_ORG = "azents";
const config = getServerConfig();

const githubOrgsSchema = z.array(z.object({ login: z.string() }));

async function checkOrgMembership(accessToken: string): Promise<boolean> {
  const response = await fetch(`https://api.github.com/user/orgs`, {
    headers: {
      Authorization: `Bearer ${accessToken}`,
      Accept: "application/vnd.github+json",
    },
  });

  if (!response.ok) {
    return false;
  }

  const orgs = githubOrgsSchema.parse(await response.json());
  return orgs.some((org) => org.login === REQUIRED_ORG);
}

export const { handlers, signIn, signOut, auth } = NextAuth({
  trustHost: true,
  providers: [
    GitHub({
      clientId: config.githubClientId,
      clientSecret: config.githubClientSecret,
      authorization: {
        params: {
          scope: "read:org",
        },
      },
    }),
  ],
  callbacks: {
    async signIn({ account }) {
      if (account?.provider !== "github" || !account.access_token) {
        return false;
      }

      const isMember = await checkOrgMembership(account.access_token);
      if (!isMember) {
        return `/api/auth/error?error=AccessDenied&message=${encodeURIComponent(`You must be a member of the ${REQUIRED_ORG} organization`)}`;
      }

      return true;
    },
    jwt({ token, account }) {
      if (account) {
        token.accessToken = account.access_token;
      }
      return token;
    },
    session({ session, token }) {
      return {
        ...session,
        accessToken: token.accessToken,
      };
    },
  },
  pages: {
    signIn: "/login",
  },
});
