import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { service, rows } = vi.hoisted(() => ({
  service: vi.fn(),
  rows: [] as object[],
}));
vi.mock("@/lib/db", () => ({
  db: () => ({ select: () => ({ from: () => ({ where: async () => rows }) }) }),
}));
vi.mock("@/lib/server", async (original) => ({
  ...(await original<typeof import("@/lib/server")>()),
  service,
}));

import { POST } from "./route";

const SECRET = "d".repeat(32);
const run = () =>
  POST(
    new Request("http://localhost/api/jobs/digest", {
      method: "POST",
      headers: { authorization: `Bearer ${SECRET}` },
    }),
  );
const outbox = [
  { key: "k1", value: { title: "NVDA research changed to buy", body: "b" } },
  { key: "k2", value: { title: "AAPL research changed to sell", body: "b" } },
];
const paths = () => service.mock.calls.map((call) => call[1]);

describe("email digest job", () => {
  beforeEach(() => {
    Object.assign(process.env, {
      DIGEST_JOB_SECRET: SECRET,
      RESEND_API_KEY: "re_test",
      EMAIL_FROM: "folio@example.test",
      AUTH_URL: "http://localhost:3000",
      AUTH_SECRET: "a".repeat(32),
    });
    service.mockReset();
    service.mockImplementation(async (_user: string, path: string) =>
      path === "email-outbox"
        ? Response.json({ data: outbox })
        : Response.json({ ok: true }),
    );
    rows.length = 0;
  });
  afterEach(() => vi.unstubAllGlobals());

  it("cancels the queue of a user who turned email alerts off, and sends nothing", async () => {
    rows.push({
      id: "u1",
      email: "u1@example.test",
      preferences: { emailAlerts: false },
    });
    const resend = vi.fn();
    vi.stubGlobal("fetch", resend);

    await run();

    expect(paths()).toEqual(["email-outbox/cancel-pending"]);
    expect(resend).not.toHaveBeenCalled();
  });

  it("claims entries before sending and marks them delivered after", async () => {
    rows.push({
      id: "u1",
      email: "u1@example.test",
      preferences: { emailAlerts: true },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("{}", { status: 200 })),
    );

    const body = await (await run()).json();

    expect(body).toEqual({ delivered: 1, failed: 0 });
    expect(paths()).toEqual([
      "home-feed",
      "email-outbox",
      "email-outbox/k1/sending",
      "email-outbox/k2/sending",
      "email-outbox/k1/delivered",
      "email-outbox/k2/delivered",
    ]);
  });

  it("returns claimed entries to the queue when the send fails or throws", async () => {
    rows.push({
      id: "u1",
      email: "u1@example.test",
      preferences: { emailAlerts: true },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("network down")),
    );

    const body = await (await run()).json();

    expect(body).toEqual({ delivered: 0, failed: 1 });
    expect(paths().slice(-2)).toEqual([
      "email-outbox/k1/pending",
      "email-outbox/k2/pending",
    ]);
    expect(paths()).not.toContain("email-outbox/k1/delivered");
  });

  it("releases what it claimed when a later step throws, so nothing is stranded", async () => {
    rows.push({
      id: "u1",
      email: "u1@example.test",
      preferences: { emailAlerts: true },
    });
    service.mockImplementation(async (_user: string, path: string) => {
      if (path === "email-outbox") return Response.json({ data: outbox });
      if (path === "email-outbox/k2/sending")
        throw new TypeError("research-api down");
      return Response.json({ ok: true });
    });
    const resend = vi.fn();
    vi.stubGlobal("fetch", resend);

    const body = await (await run()).json();

    expect(body).toEqual({ delivered: 0, failed: 1 });
    expect(resend).not.toHaveBeenCalled();
    expect(paths().slice(-1)).toEqual(["email-outbox/k1/pending"]);
  });
});
