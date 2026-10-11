import { auth } from "@/auth";
import { db } from "@/lib/db";
import { users } from "@/lib/schema";
import { eq } from "drizzle-orm";
import { failure, service } from "@/lib/server";
export async function GET() {
  const s = await auth();
  if (!s?.user?.id) return failure("Sign in required.", 401);
  const [profile] = await db()
    .select({
      name: users.name,
      email: users.email,
      preferences: users.preferences,
      createdAt: users.createdAt,
    })
    .from(users)
    .where(eq(users.id, s.user.id));
  try {
    const r = await service(s.user.id, "me/export");
    if (!r.ok) return failure("The research data export is unavailable.", 503);
    return Response.json(
      { profile, research: await r.json() },
      {
        headers: {
          "Cache-Control": "no-store",
          "Content-Disposition": 'attachment; filename="folio-account.json"',
        },
      },
    );
  } catch {
    return failure("The research data export is unavailable.", 503);
  }
}
