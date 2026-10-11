import { auth } from "@/auth";
import { service } from "@/lib/server";

function resultPage(title: string, message: string, status = 200) {
  const html = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${title} · Folio</title><style>body{margin:0;background:#101712;color:#edf3ed;font:16px system-ui,sans-serif;display:grid;min-height:100vh;place-items:center}.card{max-width:460px;margin:24px;padding:32px;border:1px solid #34483b;border-radius:18px;background:#17231b}a{color:#b4e49c}p{line-height:1.6;color:#bdc8bf}</style></head><body><main class="card"><h1>${title}</h1><p>${message}</p><a href="/">Continue to Folio</a></main></body></html>`;
  return new Response(html, {
    status,
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "no-store",
      "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
      "Referrer-Policy": "no-referrer",
    },
  });
}

export async function GET(request: Request) {
  const session = await auth();
  if (!session?.user?.id)
    return resultPage(
      "Reconnect to Folio",
      "Your Folio session expired before Robinhood returned. Sign in again and restart the connection.",
      401,
    );

  const query = new URL(request.url).searchParams;
  if (query.has("error"))
    return resultPage(
      "Connection cancelled",
      "Robinhood did not authorize the connection. No brokerage data was saved.",
    );
  const code = query.get("code") || "";
  const state = query.get("state") || "";
  const issuer = query.get("iss");
  if (!code || !state)
    return resultPage(
      "Connection incomplete",
      "Robinhood returned an incomplete authorization response. Start again from Settings → Connected accounts.",
      400,
    );
  if (issuer && issuer !== "https://agent.robinhood.com/mcp/trading")
    return resultPage(
      "Connection not completed",
      "The authorization response came from an unexpected provider. No connection was stored.",
      400,
    );

  try {
    const completed = await service(
      session.user.id,
      "broker-connections/robinhood/callback",
      { method: "POST", body: JSON.stringify({ code, state }) },
    );
    if (!completed.ok)
      return resultPage(
        "Connection not completed",
        "Folio could not validate Robinhood's response. No connection was stored; please restart from Settings.",
        completed.status,
      );
    let refreshed = false;
    try {
      const portfolio = await service(session.user.id, "portfolio/refresh", {
        method: "POST",
        body: "{}",
      });
      refreshed = portfolio.ok;
    } catch {
      // Keep the successful OAuth connection even when the first portfolio
      // read is temporarily unavailable. The user can refresh from Settings.
    }
    return resultPage(
      "Robinhood connected",
      refreshed
        ? "Folio connected through Robinhood's official authorization and loaded your portfolio in read-only mode. Folio cannot place or change trades."
        : "Folio connected through Robinhood's official authorization. The first portfolio refresh was unavailable; you can retry it from Settings. Folio cannot place or change trades.",
    );
  } catch {
    return resultPage(
      "Connection unavailable",
      "Folio could not finish the connection right now. No token or account data was sent to the browser; please try again.",
      503,
    );
  }
}
