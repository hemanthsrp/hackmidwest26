import { randomBytes } from "node:crypto";
import { and, eq, gt } from "drizzle-orm";
import { z } from "zod";
import { db } from "@/lib/db";
import { users, actionTokens, sessionRegistry } from "@/lib/schema";
import { hashPassword, sameOrigin, tokenHash } from "@/lib/security";
import { failure, rateLimit, sendEmail } from "@/lib/server";
const input = z.object({
  action: z.enum(["register", "forgot", "reset", "verify", "resend"]),
  email: z
    .email()
    .transform((x) => x.toLowerCase())
    .optional(),
  password: z.string().min(12).max(128).optional(),
  name: z.string().trim().min(1).max(80).optional(),
  token: z.string().max(128).optional(),
});
function localAccountSetupEnabled() {
  if (process.env.LOCAL_ACCOUNT_AUTH !== "true") return false;
  try {
    return ["localhost", "127.0.0.1", "[::1]"].includes(
      new URL(process.env.AUTH_URL || "").hostname,
    );
  } catch {
    return false;
  }
}
export async function POST(r: Request) {
  if (!sameOrigin(r)) return failure("Invalid request origin.", 403);
  if (!process.env.DATABASE_URL)
    return failure("Account services are not configured yet.", 503);
  try {
    const p = input.safeParse(await r.json());
    if (!p.success)
      return failure(
        "Check your details. Passwords need at least 12 characters.",
      );
    const { action, email, password, name, token } = p.data;
    if (!(await rateLimit(`identity:${email || tokenHash(token || "")}`, 5)))
      return failure("Too many attempts. Try again in 15 minutes.", 429);
    if (action === "verify" || action === "reset") {
      if (!token || (action === "reset" && !password))
        return failure("A valid token is required.");
      const purpose = action === "verify" ? "verify" : "reset";
      const ok = await db().transaction(async (tx) => {
        const [record] = await tx
          .delete(actionTokens)
          .where(
            and(
              eq(actionTokens.hash, tokenHash(token)),
              eq(actionTokens.purpose, purpose),
              gt(actionTokens.expires, new Date()),
            ),
          )
          .returning();
        if (!record) return false;
        if (purpose === "verify")
          await tx
            .update(users)
            .set({ emailVerified: new Date() })
            .where(eq(users.id, record.userId));
        else {
          await tx
            .update(users)
            .set({ passwordHash: await hashPassword(password!) })
            .where(eq(users.id, record.userId));
          await tx
            .delete(sessionRegistry)
            .where(eq(sessionRegistry.userId, record.userId));
        }
        return true;
      });
      return ok
        ? Response.json({
            message:
              action === "verify"
                ? "Email verified. You can sign in."
                : "Password reset. You can sign in.",
          })
        : failure("This link has expired or was already used.");
    }
    if (!email) return failure("Email is required.");
    const localSetup = action === "register" && localAccountSetupEnabled();
    if ((!process.env.RESEND_API_KEY || !process.env.EMAIL_FROM) && !localSetup)
      return failure("Email delivery is not configured yet.", 503);
    let [user] = await db().select().from(users).where(eq(users.email, email));
    if (action === "register") {
      if (process.env.ALLOW_REGISTRATION !== "true" && !localSetup)
        return failure(
          "Registration is not open yet. You can explore the demo.",
          503,
        );
      if (!password || !name) return failure("Name and password are required.");
      if (!user) {
        [user] = await db()
          .insert(users)
          .values({
            name,
            email,
            passwordHash: await hashPassword(password),
            ...(localSetup ? { emailVerified: new Date() } : {}),
          })
          .returning();
      } else if (localSetup && !user.emailVerified) {
        [user] = await db()
          .update(users)
          .set({ emailVerified: new Date() })
          .where(eq(users.id, user.id))
          .returning();
      }
      if (localSetup && user?.emailVerified)
        return Response.json({
          message:
            "Local Folio account is ready. Email verification is skipped only for this loopback app; you can sign in now.",
        });
    }
    if (user && !(action === "resend" && user.emailVerified)) {
      const raw = randomBytes(32).toString("hex");
      const purpose = action === "forgot" ? "reset" : "verify";
      if (action === "register" && user.emailVerified)
        return Response.json({
          message:
            "If this address is eligible, you will receive an email with next steps.",
        });
      await db()
        .insert(actionTokens)
        .values({
          hash: tokenHash(raw),
          userId: user.id,
          purpose,
          expires: new Date(Date.now() + 1800000),
        });
      const base = process.env.AUTH_URL;
      if (!base) throw new Error("AUTH_URL missing");
      await sendEmail(
        email,
        purpose === "verify"
          ? "Verify your Folio email"
          : "Reset your Folio password",
        `Open this link to ${purpose === "verify" ? "verify your email" : "reset your password"}: ${base}/login?flow=${purpose}&token=${raw}\nThis single-use link expires in 30 minutes. If you did not request it, ignore this email.`,
      );
    }
    return Response.json({
      message:
        "If this address is eligible, you will receive an email with next steps.",
    });
  } catch {
    return failure(
      "Account services are temporarily unavailable. Please try again.",
      503,
    );
  }
}
