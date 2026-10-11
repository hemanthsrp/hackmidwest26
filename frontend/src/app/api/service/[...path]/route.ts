import { auth } from "@/auth";
import { sameOrigin } from "@/lib/security";
import { failure, service } from "@/lib/server";
const allowed =
  /^(portfolio(\/refresh)?|home-feed|trending|industries(\/[a-z]+)?|stocks\/[A-Z]{1,5}|broker-connections(\/robinhood\/(start|callback)|\/[a-f0-9-]+)?|chat-memories|notifications(\/[a-f0-9-]+\/read)?|notification-preferences)$/;
async function proxy(
  r: Request,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const path = (await params).path.join("/");
  if (!allowed.test(path)) return failure("Not found.", 404);
  if (r.method !== "GET" && !sameOrigin(r))
    return failure("Invalid origin.", 403);
  const s = await auth();
  if (!s?.user?.id) return failure("Sign in required.", 401);
  try {
    const body = r.method === "GET" ? undefined : await r.text();
    const result = await service(s.user.id, path + new URL(r.url).search, {
      method: r.method,
      body: body || undefined,
    });
    return new Response(await result.text(), {
      status: result.status,
      headers: {
        "Content-Type": "application/json",
        "Cache-Control": "no-store",
      },
    });
  } catch {
    return failure(
      "This service is currently unavailable. Please try again.",
      503,
    );
  }
}
export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
