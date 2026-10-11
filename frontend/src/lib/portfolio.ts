export type PortfolioPosition = {
  symbol: string;
  shares: number;
  price: number | null;
  name?: string;
  change?: number;
  color?: string;
  history?: number[];
};

export function normalizePortfolioPositions(value: unknown): PortfolioPosition[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (!item || typeof item !== "object") return [];
    const position = item as Record<string, unknown>;
    const symbol = String(position.symbol ?? "").toUpperCase();
    const shares = Number(position.shares ?? position.quantity);
    const rawPrice = Number(position.price ?? position.current_price);
    const price = Number.isFinite(rawPrice) && rawPrice > 0 ? rawPrice : null;
    if (!/^[A-Z]{1,5}$/.test(symbol) || !Number.isFinite(shares)) {
      return [];
    }
    return [{ symbol, shares, price }];
  });
}
