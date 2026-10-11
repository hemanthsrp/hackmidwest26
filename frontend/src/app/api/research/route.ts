import { auth } from "@/auth";
import { failure, rateLimit, service } from "@/lib/server";
export async function GET(r: Request) {
  const url = new URL(r.url);
  const symbol = (url.searchParams.get("symbol") || "").trim().toUpperCase();
  if (!/^[A-Z]{1,5}$/.test(symbol))
    return failure("Enter a valid stock symbol.", 400, "invalid_symbol");
  const mode = url.searchParams.get("mode");
  if (mode === "sample") {
    try {
      if (process.env.PUBLIC_LIVE_RESEARCH === "true") {
        if (!(await rateLimit("public-live-research", 600, 60)))
          return failure(
            "The public research limit was reached. Please wait a minute and retry.",
            429,
            "rate_limited",
          );
        const response = await service(
          "public-beta-readonly",
          `stocks/${symbol}`,
        );
        return new Response(await response.text(), {
          status: response.status,
          headers: {
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
          },
        });
      }

      if (
        process.env.DEMO_LIVE_RESEARCH === "true" &&
        process.env.NODE_ENV !== "production"
      ) {
        const scraperUrl =
          process.env.SCRAPER_API_URL || "http://127.0.0.1:8002";
        const ingest = await fetch(
          `${scraperUrl}/ingest/run?symbol=${encodeURIComponent(symbol)}&live=true&fallback=false&tag=false&judge=false`,
          {
            method: "POST",
            cache: "no-store",
            signal: AbortSignal.timeout(120000),
          },
        );
        if (!ingest.ok)
          return new Response(await ingest.text(), {
            status: ingest.status,
            headers: {
              "Content-Type": "application/json",
              "Cache-Control": "no-store",
            },
          });

        const response = await service("local-live-demo", `stocks/${symbol}`);
        return new Response(await response.text(), {
          status: response.status,
          headers: {
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
          },
        });
      }

      const response = await fetch(
        `${process.env.RESEARCH_API_URL || "http://127.0.0.1:8000"}/v0/research-assessments`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ symbol, mode: "sample" }),
          cache: "no-store",
          signal: AbortSignal.timeout(10000),
        },
      );
      return new Response(await response.text(), {
        status: response.status,
        headers: {
          "Content-Type": "application/json",
          "Cache-Control": "no-store",
        },
      });
    } catch {
      return failure(
        "The research service is unavailable. Start the Research API and try again.",
        503,
        "research_service_unavailable",
      );
    }
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
