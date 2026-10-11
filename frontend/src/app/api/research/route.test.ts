import { beforeEach, describe, expect, it, vi } from "vitest";

const { auth } = vi.hoisted(() => ({ auth: vi.fn() }));
vi.mock("@/auth", () => ({ auth }));

import { GET } from "./route";

describe("research route", () => {
  beforeEach(() => {
    auth.mockReset();
    vi.unstubAllGlobals();
    delete process.env.RESEARCH_API_URL;
  });

  it("forwards an authenticated live request to the v0 assessment boundary", async () => {
    auth.mockResolvedValue({ user: { id: "user-1" } });
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ symbol: "AAPL", data_mode: "live" }), {
        status: 200,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await GET(
      new Request(
        "http://localhost:3000/api/research?symbol=aapl&mode=live&horizon=7d&risk_profile=growth",
      ),
    );

    expect(response.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:8000/v0/research-assessments");
    expect(JSON.parse(init.body)).toEqual({
      symbol: "AAPL",
      mode: "live",
      preferences: { horizon: "7d", risk_profile: "growth" },
    });
  });

  it("does not forward live research without a session", async () => {
    auth.mockResolvedValue(null);
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const response = await GET(
      new Request("http://localhost:3000/api/research?symbol=AAPL&mode=live"),
    );

    expect(response.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
