import { auth } from "@/auth";
import { z } from "zod";
import { sameOrigin } from "@/lib/security";
import { failure, service, rateLimit } from "@/lib/server";
import { db } from "@/lib/db";
import { users } from "@/lib/schema";
import { eq } from "drizzle-orm";
export async function POST(r: Request) {
  if (!sameOrigin(r)) return failure("Invalid origin.", 403);
  const p = z
    .object({
      message: z.string().trim().min(1).max(4000),
      demo: z.boolean(),
      context: z
        .array(
          z.object({
            role: z.enum(["user", "assistant"]),
            content: z.string().max(8000),
          }),
        )
        .max(10),
    })
    .safeParse(await r.json());
  if (!p.success) return failure("Enter a shorter message.");
  if (p.data.demo) {
    const text = p.data.message.toLowerCase();
    const concentration = /concentrat|risk|divers/.test(text);
    return Response.json({
      reply: concentration
        ? "In the sample portfolio, NVIDIA, Apple, and Microsoft make up most of the equity exposure. That creates a shared sensitivity to technology spending and valuations. Comparing other industries can help you understand that concentration.\n\nThis is a scripted demo response using illustrative holdings."
        : /trade|place.*order|buy.*shares|sell.*shares/.test(text)
          ? "Folio can help you review a research thesis and the evidence behind it. It cannot place or modify trades. Any investment action happens separately in your brokerage."
          : "The sample research points to AI infrastructure spending as a common theme for NVIDIA and Microsoft, while Apple’s services business offers a different source of growth. Valuation and concentration are worth examining alongside the positive signals.\n\nThis is a scripted demo response. Sign in and configure the research service for source-backed conversations.",
      citations: [
        { symbol: "NVDA", label: "NVDA research" },
        { symbol: "MSFT", label: "MSFT research" },
      ],
    });
  }
  const s = await auth();
  if (!s?.user?.id) return failure("Sign in to use research chat.", 401);
  if (!(await rateLimit(`chat:${s.user.id}`, 20, 60)))
    return failure("Please wait a moment before sending another message.", 429);
  const [user] = await db()
    .select({ preferences: users.preferences })
    .from(users)
    .where(eq(users.id, s.user.id));
  try {
    const res = await service(s.user.id, "chat/turn", {
      method: "POST",
      body: JSON.stringify({ ...p.data, preferences: user?.preferences || {} }),
    });
    return new Response(await res.text(), {
      status: res.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch {
    return failure(
      "The research assistant is unavailable. Your message was not saved.",
      503,
    );
  }
}
