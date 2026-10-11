import { describe, it, expect } from "vitest";
import {
  hashPassword,
  verifyPassword,
  sameOrigin,
  assertion,
} from "./security";
describe("credential and request boundaries", () => {
  it("uses independent salts and validates passwords without accepting malformed hashes", async () => {
    const a = await hashPassword("a sufficiently long password");
    const b = await hashPassword("a sufficiently long password");
    expect(a).not.toBe(b);
    expect(await verifyPassword("a sufficiently long password", a)).toBe(true);
    expect(await verifyPassword("incorrect", a)).toBe(false);
    expect(await verifyPassword("password", "scrypt$2$1$1$salt$invalid")).toBe(
      false,
    );
  });
  it("rejects absent and cross-origin mutation requests", () => {
    expect(sameOrigin(new Request("http://localhost:3000/api/account"))).toBe(
      false,
    );
    expect(
      sameOrigin(
        new Request("http://localhost:3000/api/account", {
          headers: { origin: "https://evil.invalid" },
        }),
      ),
    ).toBe(false);
    expect(
      sameOrigin(
        new Request("http://localhost:3000/api/account", {
          headers: { origin: "http://localhost:3000" },
        }),
      ),
    ).toBe(true);
  });
  it("fails closed without a signing key", () => {
    const previous = process.env.SERVICE_ASSERTION_SECRET;
    delete process.env.SERVICE_ASSERTION_SECRET;
    expect(() => assertion("user")).toThrow();
    process.env.SERVICE_ASSERTION_SECRET = previous;
  });
});
