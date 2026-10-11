import { timingSafeEqual, createHmac } from "node:crypto";
import { db } from "@/lib/db";
import { users } from "@/lib/schema";
import { isNotNull } from "drizzle-orm";
import { failure, service } from "@/lib/server";
export async function POST(r: Request) {
  const expected = process.env.DIGEST_JOB_SECRET;
  const actual = r.headers.get("authorization")?.replace(/^Bearer /, "") || "";
  if (
    !expected ||
    expected.length < 32 ||
    actual.length !== expected.length ||
    !timingSafeEqual(Buffer.from(actual), Buffer.from(expected))
  )
    return failure("Unauthorized.", 401);
  if (
    !process.env.RESEND_API_KEY ||
    !process.env.EMAIL_FROM ||
    !process.env.AUTH_URL
  )
    return failure("Email delivery is not configured.", 503);
  let delivered = 0,
    failed = 0;
  for (const user of await db()
    .select()
    .from(users)
    .where(isNotNull(users.emailVerified))) {
    if (!user.preferences?.emailAlerts) continue;
    try {
      await service(user.id, "home-feed");
      const response = await service(user.id, "email-outbox");
      if (!response.ok) {
        failed++;
        continue;
      }
      const data = await response.json();
      const entries = data.data as {
        key: string;
        value: { title: string; body: string };
      }[];
      if (!entries.length) continue;
      const digestKey = entries
        .map((e) => e.key)
        .sort()
        .join(",");
      const token = createHmac("sha256", process.env.AUTH_SECRET!)
        .update(`unsubscribe:${user.id}`)
        .digest("hex");
      const unsubscribe = `${process.env.AUTH_URL}/unsubscribe?user=${encodeURIComponent(user.id)}&token=${token}`;
      const sent = await fetch("https://api.resend.com/emails", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${process.env.RESEND_API_KEY}`,
          "Content-Type": "application/json",
          "Idempotency-Key": createHmac("sha256", expected)
            .update(`${user.id}:${digestKey}`)
            .digest("hex"),
        },
        body: JSON.stringify({
          from: process.env.EMAIL_FROM,
          to: [user.email],
          subject: "Your Folio research digest",
          text:
            entries
              .map((e) => `${e.value.title}\n${e.value.body}`)
              .join("\n\n") +
            `\n\nOpen your research: ${process.env.AUTH_URL}\nUnsubscribe: ${unsubscribe}`,
        }),
        signal: AbortSignal.timeout(10000),
      });
      if (!sent.ok) {
        failed++;
        continue;
      }
      for (const entry of entries) {
        const ack = await service(
          user.id,
          `email-outbox/${entry.key}/delivered`,
          { method: "POST" },
        );
        if (!ack.ok) failed++;
      }
      delivered++;
    } catch {
      failed++;
    }
  }
  return Response.json({ delivered, failed });
}
