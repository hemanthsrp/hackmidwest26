import { sql } from "drizzle-orm";
import { db } from "./db";
import { assertion, tokenHash } from "./security";
export async function rateLimit(key: string, limit = 10, seconds = 900) {
  const hash = tokenHash(key);
  const result = await db().execute(
    sql`INSERT INTO rate_limits (key,count,expires) VALUES (${hash},1,now()+${seconds}*interval '1 second') ON CONFLICT (key) DO UPDATE SET count=CASE WHEN rate_limits.expires<now() THEN 1 ELSE rate_limits.count+1 END, expires=CASE WHEN rate_limits.expires<now() THEN now()+${seconds}*interval '1 second' ELSE rate_limits.expires END RETURNING count`,
  );
  return Number(result[0]?.count) <= limit;
}
export function failure(
  message: string,
  status = 400,
  code = "request_failed",
) {
  return Response.json(
    { error: { code, message, retryable: status >= 500 } },
    { status },
  );
}
export async function sendEmail(to: string, subject: string, text: string) {
  if (!process.env.RESEND_API_KEY || !process.env.EMAIL_FROM)
    throw new Error("Email delivery is not configured");
  const r = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${process.env.RESEND_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      from: process.env.EMAIL_FROM,
      to: [to],
      subject,
      text,
    }),
    signal: AbortSignal.timeout(10000),
  });
  if (!r.ok) throw new Error("Email delivery failed");
}
export async function service(
  userId: string,
  path: string,
  init: RequestInit = {},
) {
  return fetch(
    `${process.env.RESEARCH_API_URL || "http://127.0.0.1:8000"}/v1/${path}`,
    {
      ...init,
      cache: "no-store",
      headers: {
        ...init.headers,
        "Content-Type": "application/json",
        Authorization: `Bearer ${assertion(userId)}`,
      },
      signal: AbortSignal.timeout(30000),
    },
  );
}
