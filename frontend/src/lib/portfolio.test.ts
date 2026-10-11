import { describe, expect, it } from "vitest";
import { normalizePortfolioPositions } from "./portfolio";

describe("normalizePortfolioPositions", () => {
  it("keeps a Robinhood position renderable without sample-only fields", () => {
    expect(
      normalizePortfolioPositions([
        { symbol: "NVDA", quantity: 2, current_price: "123.45" },
      ]),
    ).toEqual([
      { symbol: "NVDA", shares: 2, price: 123.45 },
    ]);
  });
});
