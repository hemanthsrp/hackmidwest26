import { describe, expect, it } from "vitest";
import {
  accountStage,
  canSignInWithPassword,
  onPasswordReset,
  onVerified,
} from "./account";

const now = new Date("2026-11-17T00:00:00Z");
const pending = { emailVerified: null, passwordHash: null };
const active = { emailVerified: now, passwordHash: "scrypt$hash" };

describe("account stages", () => {
  it("is pending until the email is verified, and only an active account signs in", () => {
    expect(accountStage(pending)).toBe("pending_verification");
    expect(accountStage(active)).toBe("active");
    expect(canSignInWithPassword(pending)).toBe(false);
    expect(
      canSignInWithPassword({ ...pending, passwordHash: "someone-else" }),
    ).toBe(false);
    expect(canSignInWithPassword(active)).toBe(true);
    expect(canSignInWithPassword(undefined)).toBe(false);
  });

  it("applies the password from the verify link that was opened", () => {
    expect(onVerified("link-hash", now)).toEqual({
      emailVerified: now,
      passwordHash: "link-hash",
    });
    // Links issued before links carried a password keep the stored one.
    expect(onVerified(null, now)).toEqual({ emailVerified: now });
  });

  it("activates a pending account on password reset, so 'you can sign in' is true", () => {
    const after = { ...pending, ...onPasswordReset(pending, "new-hash", now) };
    expect(after).toEqual({ emailVerified: now, passwordHash: "new-hash" });
    expect(canSignInWithPassword(after)).toBe(true);
    const earlier = new Date("2026-01-01T00:00:00Z");
    expect(
      onPasswordReset({ ...active, emailVerified: earlier }, "h", now)
        .emailVerified,
    ).toBe(earlier);
  });
});
