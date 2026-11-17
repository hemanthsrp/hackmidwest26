import { timingSafeEqual, createHmac } from "node:crypto";
import { db } from "@/lib/db";
import { users } from "@/lib/schema";
import { isNotNull } from "drizzle-orm";
import { failure, service } from "@/lib/server";
type Entry = { key: string; value: { title: string; body: string } };
// Best effort (sending -> pending): a release that fails is retried by the claim
// timeout in research-api, so it never needs to succeed here.
async function release(userId: string, entries: Entry[]) {
  for (const entry of entries) {
    try {
      await service(userId, `email-outbox/${entry.key}/pending`, {
        method: "POST",
      });
    } catch {
      /* the claim timeout returns it to the queue */
    }
  }
}
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
    const claimed: Entry[] = [];
    try {
      // This account's preference is the one that counts. Alerts queued while it was
      // off (research-api's copy can lag behind an unsubscribe) are cancelled, so
      // they can never go out later in one burst.
      if (!user.preferences?.emailAlerts) {
        await service(user.id, "email-outbox/cancel-pending", {
          method: "POST",
        });
        continue;
      }
      // Built before anything is claimed, so a configuration error cannot strand claims.
      const token = createHmac("sha256", process.env.AUTH_SECRET!)
        .update(`unsubscribe:${user.id}`)
        .digest("hex");
      const unsubscribe = `${process.env.AUTH_URL}/unsubscribe?user=${encodeURIComponent(user.id)}&token=${token}`;
      await service(user.id, "home-feed");
      const response = await service(user.id, "email-outbox");
      if (!response.ok) {
        failed++;
        continue;
      }
      const data = await response.json();
      // Claim each entry (pending -> sending) before mailing it: an entry whose
      // delivery cannot be acknowledged afterwards stays out of the queue instead
      // of being mailed again on the next run. research-api returns a claim older
      // than 15 minutes to the queue, so a run that dies here strands nothing.
      for (const entry of data.data as Entry[]) {
        const claim = await service(
          user.id,
          `email-outbox/${entry.key}/sending`,
          {
            method: "POST",
          },
        );
        if (claim.ok) claimed.push(entry);
        else failed++;
      }
      if (!claimed.length) continue;
      const digestKey = claimed
        .map((e) => e.key)
        .sort()
        .join(",");
      let sentOk = false;
      try {
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
              claimed
                .map((e) => `${e.value.title}\n${e.value.body}`)
                .join("\n\n") +
              `\n\nOpen your research: ${process.env.AUTH_URL}\nUnsubscribe: ${unsubscribe}`,
          }),
          signal: AbortSignal.timeout(10000),
        });
        sentOk = sent.ok;
      } catch {
        /* a network failure is a failed send */
      }
      if (!sentOk) {
        // Not sent: return the claimed entries to the queue (sending -> pending).
        await release(user.id, claimed.splice(0));
        failed++;
        continue;
      }
      // Sent: the claims are settled from here, even if an acknowledgement fails.
      const sentEntries = claimed.splice(0);
      for (const entry of sentEntries) {
        const ack = await service(
          user.id,
          `email-outbox/${entry.key}/delivered`,
          { method: "POST" },
        );
        if (!ack.ok) failed++;
      }
      delivered++;
    } catch {
      await release(user.id, claimed.splice(0));
      failed++;
    }
  }
  return Response.json({ delivered, failed });
}
