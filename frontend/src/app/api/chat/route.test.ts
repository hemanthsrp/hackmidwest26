import { afterEach, describe, expect, it, vi } from "vitest";

const { auth } = vi.hoisted(() => ({ auth: vi.fn() }));
vi.mock("@/auth", () => ({ auth }));
vi.mock("@/lib/db", () => ({
  db: () => ({ select: () => ({ from: () => ({ where: async () => [{ preferences: {} }] }) }) }),
}));
vi.mock("@/lib/server", async (original) => ({
  ...(await original<typeof import("@/lib/server")>()),
  rateLimit: vi.fn().mockResolvedValue(true),
}));

import { POST } from "./route";

describe("chat route", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    delete process.env.SERVICE_ASSERTION_SECRET;
  });

  it("gives the streamed answer longer than the 30 second default to finish", async () => {
    // fetch's timeout also aborts reading the body, so it must cover the whole stream.
    process.env.SERVICE_ASSERTION_SECRET = "s".repeat(32);
    auth.mockResolvedValue({ user: { id: "user-1" } });
    const timeout = vi.spyOn(AbortSignal, "timeout");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response("data: {}\n\n", { headers: { "Content-Type": "text/event-stream" } }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await POST(
      new Request("http://localhost:3000/api/chat", {
        method: "POST",
        headers: { origin: "http://localhost:3000" },
        body: JSON.stringify({ message: "How is my portfolio?", demo: false, context: [] }),
      }),
    );

    expect(response.status).toBe(200);
    expect(fetchMock.mock.calls[0][0]).toBe("http://127.0.0.1:8000/v1/chat/stream");
    expect(timeout).toHaveBeenCalledWith(120000);
    expect(timeout).not.toHaveBeenCalledWith(30000);
  });
});
