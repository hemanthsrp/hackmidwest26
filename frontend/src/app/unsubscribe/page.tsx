import { createHmac, timingSafeEqual } from "node:crypto";
import { db } from "@/lib/db";
import { users } from "@/lib/schema";
import { eq } from "drizzle-orm";
import { defaultPreferences } from "@/lib/market";
import Link from "next/link";
import { service } from "@/lib/server";
async function unsubscribe(form: FormData) {
  "use server";
  const id = String(form.get("user"));
  const token = String(form.get("token"));
  if (!process.env.AUTH_SECRET) throw new Error("Unavailable");
  const expected = createHmac("sha256", process.env.AUTH_SECRET)
    .update(`unsubscribe:${id}`)
    .digest("hex");
  if (
    token.length !== expected.length ||
    !timingSafeEqual(Buffer.from(token), Buffer.from(expected))
  )
    throw new Error("Invalid unsubscribe link");
  const [user] = await db().select().from(users).where(eq(users.id, id));
  if (!user) return;
  const preferences = {
    ...defaultPreferences,
    ...user.preferences,
    emailAlerts: false,
  };
  await db().update(users).set({ preferences }).where(eq(users.id, id));
  try {
    await service(id, "me/preferences", {
      method: "PATCH",
      body: JSON.stringify(preferences),
    });
  } catch {
    /* The email sender checks the authoritative account preference before delivery. */
  }
}
export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ user?: string; token?: string }>;
}) {
  const p = await searchParams;
  return (
    <main className="empty-state">
      <h1>Email preferences</h1>
      <p>
        Stop receiving Folio research digests. Account security messages remain
        enabled.
      </p>
      <form action={unsubscribe}>
        <input type="hidden" name="user" value={p.user || ""} />
        <input type="hidden" name="token" value={p.token || ""} />
        <button className="primary-button">
          Unsubscribe from research emails
        </button>
      </form>
      <p>You can update your preferences again in account settings.</p>
      <Link href="/">Back to Folio</Link>
    </main>
  );
}
