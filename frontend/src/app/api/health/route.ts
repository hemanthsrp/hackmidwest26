import { sql } from "drizzle-orm";
import { db } from "@/lib/db";

/** Minimal readiness probe for the public app container. It returns no config details. */
export async function GET() {
  if (
    !process.env.DATABASE_URL ||
    !process.env.AUTH_SECRET ||
    !process.env.SERVICE_ASSERTION_SECRET ||
    process.env.SERVICE_ASSERTION_SECRET.length < 32
  ) {
    return Response.json(
      { status: "not_ready" },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }
  try {
    await db().execute(sql`select 1`);
    return Response.json(
      { status: "ok" },
      { headers: { "Cache-Control": "no-store" } },
    );
  } catch {
    return Response.json(
      { status: "not_ready" },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }
}
