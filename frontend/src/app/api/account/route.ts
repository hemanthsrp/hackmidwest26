import { auth } from "@/auth";
import { db } from "@/lib/db";
import { users } from "@/lib/schema";
import { eq } from "drizzle-orm";
import { z } from "zod";
import { sameOrigin } from "@/lib/security";
import { failure, service } from "@/lib/server";
export async function GET() {
  const s = await auth();
  if (!s?.user?.id) return failure("Sign in to access your account.", 401);
  const [user] = await db()
    .select({
      name: users.name,
      email: users.email,
      preferences: users.preferences,
    })
    .from(users)
    .where(eq(users.id, s.user.id));
  return Response.json(user);
}
export async function PATCH(r: Request) {
  if (!sameOrigin(r)) return failure("Invalid request origin.", 403);
  const s = await auth();
  if (!s?.user?.id) return failure("Sign in required.", 401);
  const p = z
    .object({
      preferences: z.object({
        name: z.string().trim().min(1).max(80),
        risk: z.enum(["conservative", "balanced", "growth"]),
        horizon: z.enum(["7d", "30d", "90d"]),
        industries: z
          .array(
            z.enum([
              "AI",
              "Finance",
              "Technology",
              "Education",
              "Food",
              "Healthcare",
              "Energy",
              "Commodities",
            ]),
          )
          .max(8),
        theme: z.enum(["light", "dark"]),
        memory: z.boolean(),
        emailAlerts: z.boolean(),
        inAppAlerts: z.boolean(),
      }),
    })
    .safeParse(await r.json());
  if (!p.success) return failure("Invalid preferences.");
  try {
    const response = await service(s.user.id, "me/preferences", {
      method: "PATCH",
      body: JSON.stringify(p.data.preferences),
    });
    if (!response.ok)
      return failure(
        "Research preferences could not be saved. Please retry.",
        503,
      );
  } catch {
    return failure("Research preferences are unavailable. Please retry.", 503);
  }
  await db()
    .update(users)
    .set({ name: p.data.preferences.name, preferences: p.data.preferences })
    .where(eq(users.id, s.user.id));
  return Response.json({ ok: true });
}
export async function DELETE(r: Request) {
  if (!sameOrigin(r)) return failure("Invalid request origin.", 403);
  const s = await auth();
  if (!s?.user?.id) return failure("Sign in required.", 401);
  if ((await r.json()).confirmation !== "DELETE")
    return failure("Type DELETE to confirm.");
  try {
    const res = await service(s.user.id, "me", { method: "DELETE" });
    if (!res.ok)
      return failure(
        "Your research data could not be deleted. Please retry.",
        503,
      );
  } catch {
    return failure(
      "Research service unavailable. Account deletion has not completed.",
      503,
    );
  }
  await db().delete(users).where(eq(users.id, s.user.id));
  return Response.json({ ok: true });
}
