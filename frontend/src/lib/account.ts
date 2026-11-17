// The stages a local (email + password) account moves through, in one place.
//
//   (no account) --register--> pending_verification --verify link--> active
//                                     |                                 |
//                                     +-------- reset link -------------+--> active
//
// An account has no usable password until its email is proven: the password chosen
// at sign-up travels on the verify link (actionTokens.passwordHash) and is only
// written to the account when that link is opened. So whoever controls the inbox
// decides the password, never whoever typed the address first.
export type AccountStage = "pending_verification" | "active";

type AccountRow = { emailVerified: Date | null; passwordHash: string | null };

export function accountStage(user: AccountRow): AccountStage {
  return user.emailVerified ? "active" : "pending_verification";
}

/** Only an active account with a password can sign in with email and password. */
export function canSignInWithPassword(user: AccountRow | undefined): boolean {
  return !!user && accountStage(user) === "active" && !!user.passwordHash;
}

/** What opening a verify link writes: the account becomes active, with the
 * password from that link when it carries one (links issued before this field
 * existed keep the account's stored password). */
export function onVerified(linkPasswordHash: string | null, now = new Date()) {
  return linkPasswordHash
    ? { emailVerified: now, passwordHash: linkPasswordHash }
    : { emailVerified: now };
}

/** What opening a reset link writes. The link reached the inbox, which proves the
 * email just as a verify link does, so a pending account becomes active too. */
export function onPasswordReset(
  user: AccountRow,
  passwordHash: string,
  now = new Date(),
) {
  return { passwordHash, emailVerified: user.emailVerified ?? now };
}
