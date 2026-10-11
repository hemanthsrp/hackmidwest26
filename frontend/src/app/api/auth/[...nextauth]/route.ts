import { handlers } from "@/auth";
import type { NextRequest } from "next/server";
export async function GET(request: NextRequest) {
  if (!process.env.AUTH_SECRET || !process.env.DATABASE_URL) {
    const path = new URL(request.url).pathname;
    return Response.json(
      path.endsWith("/session")
        ? null
        : path.endsWith("/providers")
          ? {}
          : { error: "Account services are not configured." },
    );
  }
  return handlers.GET(request);
}
export async function POST(request: NextRequest) {
  if (!process.env.AUTH_SECRET || !process.env.DATABASE_URL)
    return Response.json(
      { error: "Account services are not configured." },
      { status: 503 },
    );
  return handlers.POST(request);
}
