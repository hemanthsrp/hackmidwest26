import { auth } from "@/auth";
import { failure } from "@/lib/server";
import { sameOrigin } from "@/lib/security";

const SYMBOL = /^[A-Z]{1,5}$/;
const HORIZONS = ["7d", "30d", "90d"];
const RISKS = ["conservative", "balanced", "growth"];

export async function POST(request: Request) {
  if (!sameOrigin(request)) return failure("Invalid origin.", 403);
  let input: unknown;
  try {
    input = await request.json();
  } catch {
    return failure("Invalid JSON request.", 400);
  }
  if (!input || typeof input !== "object" || Array.isArray(input))
    return failure("Invalid research request.", 400);
  const body = input as Record<string, unknown>;
  // Never pass an arbitrary mode or symbol through to the public v0 service.
  if (typeof body.symbol !== "string" || !SYMBOL.test(body.symbol))
    return failure("Enter a valid uppercase stock symbol.", 400, "invalid_symbol");
  if (body.mode !== "live" && body.mode !== "sample_decision")
    return failure("Invalid research mode.", 400, "invalid_mode");
  const preferences = body.preferences;
  if (!preferences || typeof preferences !== "object" || Array.isArray(preferences))
    return failure("Invalid research preferences.", 400);
  const p = preferences as Record<string, unknown>;
  if (!HORIZONS.includes(p.horizon as string) || !RISKS.includes(p.risk_profile as string))
    return failure("Invalid research preferences.", 400);
  if (body.mode === "live" && !(await auth())?.user?.id)
    return failure("Sign in to access live research.", 401);

  try {
    const response = await fetch(
      `${(process.env.RESEARCH_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "")}/v0/research-assessments`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol: body.symbol,
          mode: body.mode,
          preferences: { horizon: p.horizon, risk_profile: p.risk_profile },
        }),
        cache: "no-store",
        signal: AbortSignal.timeout(120000),
      },
    );
    return new Response(await response.text(), {
      status: response.status,
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
    });
  } catch {
    return failure("Research service is unavailable. Please try again.", 503, "research_unavailable");
  }
}
