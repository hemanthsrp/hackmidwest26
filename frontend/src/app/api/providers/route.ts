import { auth } from "@/auth";
import { db } from "@/lib/db";
import { accounts, users } from "@/lib/schema";
import { eq, and } from "drizzle-orm";
import { sameOrigin } from "@/lib/security";
import { failure } from "@/lib/server";
export async function GET() {
  const s = await auth();
  if (!s?.user?.id) return failure("Sign in required.", 401);
  const linked = await db()
    .select({ provider: accounts.provider })
    .from(accounts)
    .where(eq(accounts.userId, s.user.id));
  return Response.json(linked);
}
export async function DELETE(r: Request) {
  if (!sameOrigin(r)) return failure("Invalid origin.", 403);
  const s = await auth();
  if (!s?.user?.id) return failure("Sign in required.", 401);
  const userId = s.user.id;
  const body = await r.json();
  if (!["google", "apple", "microsoft-entra-id"].includes(body.provider))
    return failure("Unknown provider.");
  return db().transaction(async (tx) => {
    const [user] = await tx
      .select()
      .from(users)
      .where(eq(users.id, userId))
      .for("update");
    const linked = await tx
      .select()
      .from(accounts)
      .where(eq(accounts.userId, userId));
    if (!user?.passwordHash && linked.length <= 1)
      return failure("Add another sign-in method before removing this one.");
    await tx
      .delete(accounts)
      .where(
        and(eq(accounts.userId, userId), eq(accounts.provider, body.provider)),
      );
    return Response.json({ message: "Sign-in provider disconnected." });
  });
}
