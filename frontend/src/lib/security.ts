import {
  randomBytes,
  scrypt,
  timingSafeEqual,
  createHash,
  createHmac,
} from "node:crypto";
const derive = (
  password: string,
  salt: string,
  length: number,
  options: { N: number; r: number; p: number; maxmem: number },
) =>
  new Promise<Buffer>((resolve, reject) =>
    scrypt(password, salt, length, options, (err, key) =>
      err ? reject(err) : resolve(key),
    ),
  );
export async function hashPassword(password: string) {
  const salt = randomBytes(16).toString("hex");
  const key = (await derive(password, salt, 64, {
    N: 131072,
    r: 8,
    p: 1,
    maxmem: 256 * 1024 * 1024,
  })) as Buffer;
  return `scrypt$131072$8$1$${salt}$${key.toString("hex")}`;
}
export async function verifyPassword(password: string, encoded: string) {
  const [algorithm, n, r, p, salt, digest] = encoded.split("$");
  if (
    algorithm !== "scrypt" ||
    n !== "131072" ||
    r !== "8" ||
    p !== "1" ||
    !salt ||
    !/^[a-f0-9]{128}$/.test(digest || "")
  )
    return false;
  const key = (await derive(password, salt, 64, {
    N: Number(n),
    r: Number(r),
    p: Number(p),
    maxmem: 256 * 1024 * 1024,
  })) as Buffer;
  return timingSafeEqual(key, Buffer.from(digest, "hex"));
}
export const tokenHash = (token: string) =>
  createHash("sha256").update(token).digest("hex");
export function sameOrigin(request: Request) {
  return (
    request.headers.get("origin") ===
    new URL(process.env.AUTH_URL || request.url).origin
  );
}
export function assertion(userId: string) {
  const secret = process.env.SERVICE_ASSERTION_SECRET;
  if (!secret || secret.length < 32)
    throw new Error("Service authentication is not configured");
  const payload = Buffer.from(
    JSON.stringify({
      sub: userId,
      exp: Math.floor(Date.now() / 1000) + 60,
      aud: "research-api",
    }),
  ).toString("base64url");
  return `${payload}.${createHmac("sha256", secret).update(payload).digest("base64url")}`;
}
