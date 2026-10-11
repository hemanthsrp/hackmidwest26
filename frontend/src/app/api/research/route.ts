import { auth } from "@/auth";
import { stocks, sampleAsOf } from "@/lib/market";
import { failure } from "@/lib/server";
export async function GET(r: Request) {
  const url = new URL(r.url);
  const symbol = (url.searchParams.get("symbol") || "").trim().toUpperCase();
  if (!/^[A-Z]{1,5}$/.test(symbol))
    return failure("Enter a valid stock symbol.", 400, "invalid_symbol");
  const mode = url.searchParams.get("mode");
  if (mode === "sample") {
    const s = stocks.find((s) => s.symbol === symbol);
    if (!s)
      return failure(
        "This symbol is not available in the demo.",
        400,
        "unsupported_symbol",
      );
    return Response.json({
      symbol,
      data_mode: "sample",
      snapshot: { as_of: sampleAsOf },
      assessment: {
        label: s.stance,
        explanation: s.reason,
        uncertainty:
          "Illustrative research only. This sample does not reflect current market conditions.",
        data_mode: "sample",
      },
      signals: [
        {
          id: `demo-${symbol}-change`,
          name: "Sample daily price change",
          value: s.change,
          unit: "percent",
        },
      ],
      evidence: [
        {
          id: `demo-${symbol}-evidence`,
          title: `${s.name} sample research`,
          summary: s.reason,
          source_name: "Folio illustrative dataset",
        },
      ],
    });
  }
  const session = await auth();
  if (!session?.user?.id)
    return failure("Sign in to access live research.", 401);
  const horizon = url.searchParams.get("horizon");
  const riskProfile = url.searchParams.get("risk_profile");
  if (horizon && !["7d", "30d", "90d"].includes(horizon))
    return failure("Choose a valid research horizon.", 400, "invalid_horizon");
  if (
    riskProfile &&
    !["conservative", "balanced", "growth"].includes(riskProfile)
  )
    return failure("Choose a valid risk profile.", 400, "invalid_risk_profile");
  try {
    const response = await fetch(
      `${process.env.RESEARCH_API_URL || "http://127.0.0.1:8000"}/v0/research-assessments`,
      {
        method: "POST",
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol,
          mode: "live",
          preferences: {
            horizon: horizon || "30d",
            risk_profile: riskProfile || "balanced",
          },
        }),
        signal: AbortSignal.timeout(75000),
      },
    );
    return new Response(await response.text(), {
      status: response.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch {
    return failure(
      "The research service is unavailable. Please try again.",
      503,
    );
  }
}
