import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";
import Google from "next-auth/providers/google";
import Apple from "next-auth/providers/apple";
import Microsoft from "next-auth/providers/microsoft-entra-id";
import { DrizzleAdapter } from "@auth/drizzle-adapter";
import { and, eq, gt } from "drizzle-orm";
import { z } from "zod";
import { db } from "@/lib/db";
import {
  users,
  accounts,
  sessions,
  verificationTokens,
  sessionRegistry,
} from "@/lib/schema";
import { verifyPassword } from "@/lib/security";
import { rateLimit } from "@/lib/server";
const providers = [
  Credentials({
    credentials: { email: {}, password: {} },
    authorize: async (raw) => {
      const p = z
        .object({
          email: z.email().transform((x) => x.toLowerCase()),
          password: z.string().min(1).max(1024),
        })
        .safeParse(raw);
      if (!p.success || !process.env.DATABASE_URL) return null;
      if (!(await rateLimit(`login:${p.data.email}`))) return null;
      const [user] = await db()
        .select()
        .from(users)
        .where(eq(users.email, p.data.email));
      if (
        !user?.passwordHash ||
        !user.emailVerified ||
        !(await verifyPassword(p.data.password, user.passwordHash))
      )
        return null;
      return {
        id: user.id,
        name: user.name,
        email: user.email,
        image: user.image,
      };
    },
  }),
  ...(process.env.AUTH_GOOGLE_ID ? [Google] : []),
  ...(process.env.AUTH_APPLE_ID ? [Apple] : []),
  ...(process.env.AUTH_MICROSOFT_ENTRA_ID_ID ? [Microsoft] : []),
];
export const { handlers, auth, signIn, signOut } = NextAuth(() => ({
  secret: process.env.AUTH_SECRET,
  trustHost:
    process.env.AUTH_TRUST_HOST === "true" ||
    process.env.NODE_ENV !== "production",
  adapter: process.env.DATABASE_URL
    ? DrizzleAdapter(db(), {
        usersTable: users,
        accountsTable: accounts,
        sessionsTable: sessions,
        verificationTokensTable: verificationTokens,
      })
    : undefined,
  providers,
  session: { strategy: "jwt", maxAge: 7 * 24 * 60 * 60 },
  pages: { signIn: "/login", error: "/login" },
  callbacks: {
    async signIn({ account, user, profile }) {
      if (account?.provider === "credentials") return true;
      if (!process.env.DATABASE_URL) return false;
      const email = user.email?.toLowerCase();
      if (!email) return false;
      const [existing] = await db()
        .select()
        .from(users)
        .where(eq(users.email, email));
      if (!existing && process.env.ALLOW_REGISTRATION !== "true") return false;
      if (account?.provider === "google" && profile?.email_verified !== true)
        return false;
      return true;
    },
    async jwt({ token, user }) {
      if (user?.id) {
        const id = crypto.randomUUID();
        await db()
          .insert(sessionRegistry)
          .values({
            id,
            userId: user.id,
            expires: new Date(Date.now() + 7 * 86400000),
          });
        token.sid = id;
        token.sub = user.id;
      }
      if (token.sid && token.sub) {
        const [valid] = await db()
          .select()
          .from(sessionRegistry)
          .where(
            and(
              eq(sessionRegistry.id, String(token.sid)),
              eq(sessionRegistry.userId, token.sub),
              gt(sessionRegistry.expires, new Date()),
            ),
          );
        if (!valid) return null;
      }
      return token;
    },
    async session({ session, token }) {
      if (session.user && token.sub) session.user.id = token.sub;
      return session;
    },
  },
  events: {
    async signOut(message) {
      if ("token" in message && message.token?.sid)
        await db()
          .delete(sessionRegistry)
          .where(eq(sessionRegistry.id, String(message.token.sid)));
    },
  },
}));
