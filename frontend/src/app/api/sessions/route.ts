import { auth } from "@/auth";
import { db } from "@/lib/db";
import { sessionRegistry } from "@/lib/schema";
import { and, eq, gt } from "drizzle-orm";
import { failure } from "@/lib/server";
import { sameOrigin } from "@/lib/security";
export async function GET() {
  const s = await auth();
  if (!s?.user?.id) return failure("Sign in required.", 401);
  return Response.json(
    await db()
      .select({
        id: sessionRegistry.id,
        createdAt: sessionRegistry.createdAt,
        expires: sessionRegistry.expires,
      })
      .from(sessionRegistry)
      .where(
        and(
          eq(sessionRegistry.userId, s.user.id),
          gt(sessionRegistry.expires, new Date()),
        ),
      ),
  );
}
export async function DELETE(r: Request) {
  if (!sameOrigin(r)) return failure("Invalid request origin.", 403);
  const s = await auth();
  if (!s?.user?.id) return failure("Sign in required.", 401);
  const { id } = await r.json();
  if (typeof id !== "string") return failure("Session identifier required.");
  await db()
    .delete(sessionRegistry)
    .where(
      and(eq(sessionRegistry.userId, s.user.id), eq(sessionRegistry.id, id)),
    );
  return Response.json({ ok: true });
}
