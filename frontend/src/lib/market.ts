export type Stance = "buy" | "hold" | "sell" | "insufficient_data";
export type Stock = {
  symbol: string;
  name: string;
  industry: string;
  price: number;
  change: number;
  shares: number;
  color: string;
  stance: Stance;
  history: number[];
  reason: string;
};
export type Article = {
  id: string;
  symbol: string;
  source: string;
  title: string;
  summary: string;
  stance: "Bullish" | "Bearish" | "Neutral";
  category: string;
  time: string;
};
export const sampleAsOf = "2026-10-10T20:00:00Z";
// Synthetic display fixtures. They are never merged into a connected portfolio.
export const stocks: Stock[] = [
  {
    symbol: "NVDA",
    name: "NVIDIA",
    industry: "AI",
    price: 134.81,
    change: 2.84,
    shares: 45,
    color: "#78a848",
    stance: "buy",
    history: [
      92, 96, 94, 102, 99, 111, 108, 114, 110, 122, 118, 128, 124, 134.81,
    ],
    reason:
      "AI infrastructure demand supports the research thesis; valuation remains a risk.",
  },
  {
    symbol: "AAPL",
    name: "Apple",
    industry: "Technology",
    price: 228.22,
    change: 1.12,
    shares: 32,
    color: "#89919f",
    stance: "hold",
    history: [
      210, 213, 211, 217, 214, 220, 218, 219, 222, 220, 225, 224, 226, 228.22,
    ],
    reason: "Services growth balances a slower device replacement cycle.",
  },
  {
    symbol: "MSFT",
    name: "Microsoft",
    industry: "Technology",
    price: 426.32,
    change: 1.76,
    shares: 20,
    color: "#6b8bd6",
    stance: "buy",
    history: [
      392, 399, 397, 407, 402, 410, 406, 416, 412, 420, 415, 423, 421, 426.32,
    ],
    reason:
      "Recurring cloud revenue and enterprise adoption support the sample assessment.",
  },
  {
    symbol: "JPM",
    name: "JPMorgan Chase",
    industry: "Finance",
    price: 216.48,
    change: -0.64,
    shares: 24,
    color: "#8f7bc2",
    stance: "hold",
    history: [
      218, 217, 220, 219, 215, 216, 218, 213, 216, 214, 219, 215, 217, 216.48,
    ],
    reason:
      "Resilient earnings are offset by uncertainty around the rate outlook.",
  },
  {
    symbol: "TSLA",
    name: "Tesla",
    industry: "Technology",
    price: 238.77,
    change: -2.31,
    shares: 0,
    color: "#dc7478",
    stance: "sell",
    history: [
      263, 267, 262, 258, 260, 253, 256, 250, 254, 246, 248, 242, 245, 238.77,
    ],
    reason:
      "Margin pressure and uneven demand warrant a cautious research stance.",
  },
  {
    symbol: "XOM",
    name: "Exxon Mobil",
    industry: "Energy",
    price: 121.8,
    change: 0.94,
    shares: 0,
    color: "#c59554",
    stance: "hold",
    history: [
      114, 116, 115, 118, 116, 119, 117, 119, 118, 121, 119, 122, 120, 121.8,
    ],
    reason:
      "Cash generation remains strong, with sensitivity to commodity prices.",
  },
  {
    symbol: "CMG",
    name: "Chipotle",
    industry: "Food",
    price: 58.22,
    change: 1.42,
    shares: 0,
    color: "#b27b55",
    stance: "buy",
    history: [51, 52, 51, 54, 53, 55, 54, 56, 55, 57, 56, 58, 57, 58.22],
    reason:
      "Store growth and customer demand support the sample research thesis.",
  },
  {
    symbol: "DUOL",
    name: "Duolingo",
    industry: "Education",
    price: 289.32,
    change: 2.08,
    shares: 0,
    color: "#8aac5d",
    stance: "hold",
    history: [
      250, 260, 255, 270, 263, 274, 270, 281, 275, 285, 278, 289, 283, 289.32,
    ],
    reason: "Subscriber growth is balanced against an elevated valuation.",
  },
  {
    symbol: "UNH",
    name: "UnitedHealth",
    industry: "Healthcare",
    price: 589.2,
    change: -0.42,
    shares: 0,
    color: "#659eb0",
    stance: "hold",
    history: [
      598, 601, 596, 594, 597, 592, 595, 590, 593, 587, 590, 588, 592, 589.2,
    ],
    reason: "Defensive demand is offset by medical-cost uncertainty.",
  },
  {
    symbol: "GLD",
    name: "SPDR Gold Shares",
    industry: "Commodities",
    price: 243.68,
    change: 0.78,
    shares: 0,
    color: "#c5a153",
    stance: "buy",
    history: [
      230, 233, 232, 236, 234, 238, 235, 240, 237, 241, 239, 243, 241, 243.68,
    ],
    reason:
      "Diversification interest supports gold, while real yields remain a risk.",
  },
];
export const articles: Article[] = [
  {
    id: "demo-1",
    symbol: "NVDA",
    source: "Sample market brief",
    title: "The next chapter of AI is being built in the data center",
    summary:
      "Infrastructure spending puts semiconductor demand in focus. Explore what this could mean for your technology exposure.",
    stance: "Bullish",
    category: "AI & TECHNOLOGY",
    time: "2026-10-10T18:30:00Z",
  },
  {
    id: "demo-2",
    symbol: "JPM",
    source: "Sample finance brief",
    title: "Banks enter earnings season with a changing rate outlook",
    summary:
      "Net interest income and credit quality offer two different signals for financial stocks.",
    stance: "Neutral",
    category: "FINANCE",
    time: "2026-10-10T17:00:00Z",
  },
  {
    id: "demo-3",
    symbol: "AAPL",
    source: "Sample company brief",
    title: "Services take a bigger role in Apple’s growth story",
    summary:
      "Recurring revenue is increasingly important as investors look beyond the hardware cycle.",
    stance: "Bullish",
    category: "TECHNOLOGY",
    time: "2026-10-10T16:15:00Z",
  },
  {
    id: "demo-4",
    symbol: "TSLA",
    source: "Sample market brief",
    title: "EV competition brings margins back into the spotlight",
    summary:
      "Pricing and delivery trends raise questions about the next stage of demand.",
    stance: "Bearish",
    category: "TECHNOLOGY",
    time: "2026-10-10T15:00:00Z",
  },
  {
    id: "demo-5",
    symbol: "GLD",
    source: "Sample commodities brief",
    title: "Gold finds renewed attention in an uncertain market",
    summary:
      "Investors revisit the role of real assets as a source of portfolio diversification.",
    stance: "Bullish",
    category: "COMMODITIES",
    time: "2026-10-10T14:30:00Z",
  },
];
export const industries = [
  "AI",
  "Finance",
  "Technology",
  "Education",
  "Food",
  "Healthcare",
  "Energy",
  "Commodities",
];
export const money = (n: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(n);
export const pct = (n: number) => `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
export type Preferences = {
  name: string;
  risk: "conservative" | "balanced" | "growth";
  horizon: "7d" | "30d" | "90d";
  industries: string[];
  theme: "light" | "dark";
  memory: boolean;
  emailAlerts: boolean;
  inAppAlerts: boolean;
};
export const defaultPreferences: Preferences = {
  name: "Alex Morgan",
  risk: "balanced",
  horizon: "30d",
  industries: ["AI", "Technology", "Finance"],
  theme: "light",
  memory: false,
  emailAlerts: false,
  inAppAlerts: true,
};
