import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/auth", () => ({ auth: vi.fn() }));
import { auth } from "@/auth";
import { POST } from "./route";

const url = "http://localhost:3000/api/research/assessment";
const payload = { symbol: "AAPL", mode: "sample_decision", preferences: { horizon: "30d", risk_profile: "balanced" } };
function request(body: unknown, origin = "http://localhost:3000") {
  return new Request(url, { method: "POST", headers: { origin, "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

describe("v0 research same-origin bridge", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => vi.unstubAllGlobals());

  it("rejects foreign origin and unapproved modes without calling the service", async () => {
    expect((await POST(request(payload, "https://other.invalid"))).status).toBe(403);
    expect((await POST(request({ ...payload, mode: "failure" }))).status).toBe(400);
    expect((await POST(request({ ...payload, symbol: "AAPL/../" }))).status).toBe(400);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("requires sign-in for live but not for a labeled sample decision", async () => {
    vi.mocked(auth as unknown as () => Promise<null>).mockResolvedValue(null);
    expect((await POST(request({ ...payload, mode: "live" }))).status).toBe(401);
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ data_mode: "sample" }), { status: 200 }));
    const response = await POST(request(payload));
    expect(response.status).toBe(200);
    const [target, init] = vi.mocked(fetch).mock.calls[0];
    expect(target).toMatch(/\/v0\/research-assessments$/);
    expect(JSON.parse(String(init?.body))).toEqual(payload);
    expect(response.headers.get("Cache-Control")).toBe("no-store");
  });

  it("preserves backend stale/provider errors and does not substitute fixtures", async () => {
    vi.mocked(auth as unknown as () => Promise<unknown>).mockResolvedValue({ user: { id: "user" } });
    const error = { error: { code: "stale_data", message: "Evidence is stale.", retryable: false } };
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify(error), { status: 409 }));
    const result = await POST(request({ ...payload, mode: "live" }));
    expect(result.status).toBe(409);
    expect(await result.json()).toEqual(error);
  });
});
