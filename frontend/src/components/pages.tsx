"use client";
import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowUpRight,
  ArrowRight,
  ChevronRight,
  Search,
  SlidersHorizontal,
  TrendingUp,
  Globe2,
  Link2,
  Layers3,
  RefreshCw,
} from "lucide-react";
import {
  AreaChart,
  Area,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  stocks,
  articles,
  industries,
  money,
  pct,
  type Stock,
  type Article,
} from "@/lib/market";
import { useApp } from "./shell";
function Badge({ stance }: { stance: string }) {
  return (
    <span className={`badge ${stance.toLowerCase()}`}>
      {stance === "buy"
        ? "Buy research"
        : stance === "sell"
          ? "Sell research"
          : stance === "hold"
            ? "Hold"
            : stance.replaceAll("_", " ")}
    </span>
  );
}
function Sparkline({
  stock,
  large = false,
}: {
  stock: Stock;
  large?: boolean;
}) {
  const values = stock.history;
  const min = Math.min(...values) - 2,
    max = Math.max(...values) + 2;
  const points = values
    .map(
      (v, i) =>
        `${(i / (values.length - 1)) * 110},${40 - ((v - min) / (max - min)) * 38}`,
    )
    .join(" ");
  return (
    <svg
      viewBox="0 0 110 42"
      className={`sparkline ${large ? "large" : ""}`}
      role="img"
      aria-label={`${stock.symbol} sample price trend`}
    >
      <polyline
        fill="none"
        stroke={stock.change >= 0 ? "var(--green)" : "var(--red)"}
        strokeWidth="1.7"
        points={points}
      />
    </svg>
  );
}
function StockLogo({ stock }: { stock: Stock }) {
  return (
    <span
      className="stock-logo"
      style={{ background: stock.color + "19", color: stock.color }}
    >
      {stock.symbol === "AAPL"
        ? "a"
        : stock.symbol === "MSFT"
          ? "▦"
          : stock.symbol === "NVDA"
            ? "◉"
            : stock.symbol.slice(0, 2)}
    </span>
  );
}
function PageHeader({
  eyebrow,
  title,
  description,
  children,
}: {
  eyebrow: string;
  title: string;
  description: string;
  children?: React.ReactNode;
}) {
  return (
    <header className="page-header">
      <div>
        <span className="eyebrow">{eyebrow}</span>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {children}
    </header>
  );
}
function SectionTitle({
  title,
  description,
  href,
}: {
  title: string;
  description?: string;
  href?: string;
}) {
  return (
    <div className="section-title">
      <div>
        <h2>{title}</h2>
        {description && <p>{description}</p>}
      </div>
      {href && (
        <Link href={href}>
          View all <ArrowRight size={14} />
        </Link>
      )}
    </div>
  );
}
export function Home() {
  const { demo, preferences, openSettings } = useApp();
  const [range, setRange] = useState("1M");
  const [search, setSearch] = useState("");
  const [showAll, setShowAll] = useState(false);
  const q = useQuery({
    queryKey: ["portfolio"],
    enabled: !demo,
    queryFn: async () => {
      const r = await fetch("/api/service/portfolio");
      if (!r.ok) throw new Error("Portfolio unavailable");
      return r.json();
    },
  });
  const positions = demo
    ? stocks.filter((s) => s.shares > 0)
    : q.data?.data?.positions || [];
  const total = demo
    ? positions.reduce((n: number, s: Stock) => n + s.price * s.shares, 0)
    : q.data?.data?.value || 0;
  return (
    <>
      <PageHeader
        eyebrow="YOUR MARKET, IN PERSPECTIVE"
        title={`Good to see you, ${preferences.name.split(" ")[0]}.`}
        description="Here’s what’s happening with your investments today."
      >
        <span className="date-chip">
          {demo
            ? "October 10, 2026"
            : new Date().toLocaleDateString("en-US", {
                month: "long",
                day: "numeric",
                year: "numeric",
              })}
        </span>
      </PageHeader>
      <section className="portfolio-card">
        <div className="portfolio-card-top">
          <div>
            <span className="label">
              Portfolio value{" "}
              <span className="tiny-tag">{demo ? "SAMPLE" : "USD"}</span>
            </span>
            <div className="portfolio-value">
              {!demo && !q.data?.data?.connected ? "—" : money(total)}
            </div>
            {demo ? (
              <span className="positive portfolio-change">
                ↗ $421.86 <span>(+1.66%) today</span>
              </span>
            ) : (
              <button className="text-button" onClick={openSettings}>
                <Link2 size={14} />
                {q.data?.data?.connected
                  ? "Refresh Robinhood portfolio"
                  : "Connect your Robinhood portfolio"}
              </button>
            )}
          </div>
          <span className="portfolio-badge">
            <span className="status-dot" />
            {demo
              ? "Demo portfolio"
              : q.data?.data?.connected
                ? "Connected"
                : "Not connected"}
          </span>
        </div>
        <div className="portfolio-chart">
          <ResponsiveContainer width="100%" height={145}>
            <AreaChart
              data={(demo ? stocks[0].history : [])
                .slice(
                  range === "1D"
                    ? -4
                    : range === "1W"
                      ? -6
                      : range === "1M"
                        ? -8
                        : range === "3M"
                          ? -10
                          : range === "1Y"
                            ? -12
                            : 0,
                )
                .map((v, i) => ({ value: total * (0.87 + v / 1000), day: i }))}
            >
              <YAxis hide domain={["dataMin - 100", "dataMax + 100"]} />
              <defs>
                <linearGradient id="portfolio-fill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#608873" stopOpacity={0.16} />
                  <stop offset="100%" stopColor="#608873" stopOpacity={0} />
                </linearGradient>
              </defs>
              <Tooltip
                formatter={(v) => money(Number(v))}
                labelFormatter={() => "Illustrative portfolio value"}
                contentStyle={{
                  background: "var(--card)",
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                }}
              />
              <Area
                type="monotone"
                dataKey="value"
                stroke="#5e8f77"
                strokeWidth={2}
                fill="url(#portfolio-fill)"
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
        <div className="chart-footer">
          <span>
            {demo
              ? "Illustrative performance · not historical returns"
              : "Connect an account to see your positions"}
          </span>
          <div className="range-tabs">
            {["1D", "1W", "1M", "3M", "1Y", "ALL"].map((r) => (
              <button
                key={r}
                className={range === r ? "selected" : ""}
                onClick={() => setRange(r)}
              >
                {r}
              </button>
            ))}
          </div>
        </div>
      </section>
      {!demo && q.isError && (
        <div role="alert" className="error-box">
          We couldn’t load your portfolio.
          <button className="text-button" onClick={() => void q.refetch()}>
            Retry
          </button>
        </div>
      )}
      <section>
        <SectionTitle
          title="Your positions"
          description={`${positions.length} assets · A closer look at what you own`}
        />
        <div className="positions panel">
          <div className="table-toolbar">
            <div className="search">
              <Search size={15} />
              <input
                aria-label="Search positions"
                placeholder="Find a position…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <button
              className="text-button"
              onClick={() => setShowAll(!showAll)}
            >
              <SlidersHorizontal size={14} />
              {showAll ? "Largest positions" : "All positions"}
            </button>
          </div>
          <table>
            <thead>
              <tr>
                <th>Asset</th>
                <th>Price</th>
                <th>Today</th>
                <th>7-day trend</th>
                <th>Position</th>
              </tr>
            </thead>
            <tbody>
              {positions
                .filter((s: Stock) =>
                  `${s.name} ${s.symbol}`
                    .toLowerCase()
                    .includes(search.toLowerCase()),
                )
                .slice(0, showAll ? 100 : 4)
                .map((s: Stock) => (
                  <tr key={s.symbol}>
                    <td>
                      <Link className="asset" href={`/stocks/${s.symbol}`}>
                        <StockLogo stock={s} />
                        <span>
                          <strong>{s.symbol}</strong>
                          <small>{s.name}</small>
                        </span>
                      </Link>
                    </td>
                    <td>{money(s.price)}</td>
                    <td className={s.change >= 0 ? "positive" : "negative"}>
                      {pct(s.change)}
                    </td>
                    <td>
                      <Sparkline stock={s} />
                    </td>
                    <td>
                      <strong>{money(s.price * s.shares)}</strong>
                      <small>{s.shares} shares</small>
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
          {!positions.length && (
            <div className="empty-state">
              <Layers3 size={26} />
              <h3>Your portfolio starts here</h3>
              <p>
                Connect an account in settings to bring your positions into
                focus.
              </p>
              <button className="primary-button" onClick={openSettings}>
                Connect portfolio <ArrowRight size={15} />
              </button>
            </div>
          )}
        </div>
      </section>
      <section>
        <SectionTitle
          title="On your radar"
          description="Research ideas connected to your portfolio"
          href="/trending"
        />
        <div className="suggestion-grid">
          {(demo
            ? stocks.filter((s) => ["NVDA", "GLD", "CMG"].includes(s.symbol))
            : []
          ).map((s) => (
            <Link
              href={`/stocks/${s.symbol}`}
              className="suggestion-card"
              key={s.symbol}
            >
              <div className="card-row">
                <StockLogo stock={s} />
                <Badge stance={s.stance} />
              </div>
              <h3>
                {s.name}
                <ArrowUpRight size={16} />
              </h3>
              <p>{s.reason}</p>
              <div className="suggestion-bottom">
                <span>{s.symbol}</span>
                <span className="positive">{pct(s.change)}</span>
              </div>
            </Link>
          ))}
        </div>
        {!demo && <LiveFeed endpoint="home-feed" />}
      </section>
      <section>
        <SectionTitle
          title="The stories behind your stocks"
          description="A little context goes a long way"
          href="/trending"
        />
        {demo ? (
          <ArticleList items={articles.slice(0, 3)} />
        ) : (
          <LiveFeed endpoint="home-feed" articlesOnly />
        )}
      </section>
    </>
  );
}
function ArticleList({ items }: { items: Article[] }) {
  return (
    <div className="article-list">
      {items.map((a, i) => (
        <Link href={`/stocks/${a.symbol}`} className="article-card" key={a.id}>
          <div className={`article-art art-${i % 3}`} aria-hidden="true">
            <div className="art-grid" />
            <span>{a.symbol}</span>
            <Globe2 size={40} />
          </div>
          <div className="article-content">
            <span className="eyebrow">{a.category}</span>
            <h3>{a.title}</h3>
            <p>{a.summary}</p>
            <div className="article-meta">
              <span>{a.source}</span>
              <span>Oct 10</span>
              <Badge stance={a.stance} />
            </div>
          </div>
          <ArrowUpRight size={18} />
        </Link>
      ))}
    </div>
  );
}
export function Trending() {
  const { demo } = useApp();
  const [section, setSection] = useState("All");
  const [query, setQuery] = useState("");
  const categories = [
    "All",
    "Buy",
    "Sell",
    "Hot in finance",
    "Hot in tech",
    "Hot in commodities",
  ];
  const filtered = stocks.filter(
    (s) =>
      (section === "All" ||
        (section === "Buy" && s.stance === "buy") ||
        (section === "Sell" && s.stance === "sell") ||
        (section === "Hot in finance" && s.industry === "Finance") ||
        (section === "Hot in tech" &&
          ["AI", "Technology"].includes(s.industry)) ||
        (section === "Hot in commodities" && s.industry === "Commodities")) &&
      `${s.symbol} ${s.name}`.toLowerCase().includes(query.toLowerCase()),
  );
  return (
    <>
      <PageHeader
        eyebrow="THE MARKET CONVERSATION"
        title="What’s moving. What matters."
        description="Explore the companies and stories capturing the market’s attention."
      />
      <div className="trending-hero">
        <div>
          <span className="eyebrow">IN FOCUS</span>
          <h2>
            The intelligence
            <br />
            behind the momentum.
          </h2>
          <p>Go beyond the ticker. Understand what’s shaping today’s market.</p>
          <Link href="/industries/ai">
            Explore AI & technology <ArrowUpRight size={16} />
          </Link>
        </div>
        <div className="hero-orbit">
          <div />
          <div />
          <div />
          <TrendingUp size={60} />
        </div>
      </div>
      <div className="filter-bar">
        {categories.map((c) => (
          <button
            key={c}
            className={section === c ? "selected" : ""}
            onClick={() => setSection(c)}
          >
            {c}
          </button>
        ))}
      </div>
      <div className="section-title">
        <h2>
          {section === "All"
            ? "Market watch"
            : section === "Buy"
              ? "Buy research"
              : section === "Sell"
                ? "Sell research"
                : section}
        </h2>
        <div className="search">
          <Search size={15} />
          <input
            aria-label="Search market"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search symbols…"
          />
        </div>
      </div>
      {demo ? (
        <>
          <div className="market-grid">
            {filtered.map((s) => (
              <StockCard stock={s} key={s.symbol} />
            ))}
          </div>
          {!filtered.length && (
            <div className="empty-state panel">
              No symbols match this filter.
            </div>
          )}
          <SectionTitle
            title="In the conversation"
            description="Fresh perspectives from across the market"
          />
          <ArticleList
            items={articles.filter(
              (a) =>
                section === "All" ||
                filtered.some((s) => s.symbol === a.symbol),
            )}
          />
        </>
      ) : (
        <LiveFeed
          endpoint={`trending?section=${({ All: "all", Buy: "buy", Sell: "sell", "Hot in finance": "finance", "Hot in tech": "technology", "Hot in commodities": "commodities" } as Record<string, string>)[section]}`}
          search={query}
        />
      )}
    </>
  );
}
function StockCard({ stock: s }: { stock: Stock }) {
  return (
    <Link className="stock-card panel" href={`/stocks/${s.symbol}`}>
      <div className="card-row">
        <div className="asset">
          <StockLogo stock={s} />
          <span>
            <strong>{s.symbol}</strong>
            <small>{s.name}</small>
          </span>
        </div>
        <ArrowUpRight size={16} />
      </div>
      <div className="stock-card-price">
        <strong>{money(s.price)}</strong>
        <span className={s.change >= 0 ? "positive" : "negative"}>
          {pct(s.change)}
        </span>
      </div>
      <Sparkline stock={s} large />
      <div className="card-row">
        <Badge stance={s.stance} />
        <span className="muted">{s.industry}</span>
      </div>
    </Link>
  );
}
const industryDescriptions: Record<string, string> = {
  AI: "The next wave of intelligence",
  Finance: "Capital, banking & payments",
  Technology: "Building a connected world",
  Education: "The future of learning",
  Food: "From everyday to extraordinary",
  Healthcare: "Investing in better outcomes",
  Energy: "Powering what comes next",
  Commodities: "The essentials of the economy",
};
export function Industries({ selected }: { selected?: string }) {
  const { demo } = useApp();
  const current = industries.find(
    (i) => i.toLowerCase() === selected?.toLowerCase(),
  );
  return (
    <>
      <PageHeader
        eyebrow="EXPLORE THE BIGGER PICTURE"
        title={current || "Every industry has a story."}
        description={
          current
            ? industryDescriptions[current]
            : "Find the themes, companies, and ideas shaping the world around you."
        }
      />
      {current ? (
        <>
          <Link className="back-link" href="/industries">
            ← All industries
          </Link>
          {demo ? (
            <>
              <div className="market-grid">
                {stocks
                  .filter((s) => s.industry === current)
                  .map((s) => (
                    <StockCard key={s.symbol} stock={s} />
                  ))}
              </div>
              <SectionTitle title="Industry perspectives" />
              <ArticleList
                items={articles.filter((a) =>
                  stocks.some(
                    (s) => s.symbol === a.symbol && s.industry === current,
                  ),
                )}
              />
            </>
          ) : (
            <LiveFeed endpoint={`industries/${selected}`} />
          )}
        </>
      ) : (
        <div className="industry-grid">
          {industries.map((name, i) => (
            <Link
              key={name}
              href={`/industries/${name.toLowerCase()}`}
              className="industry-card panel"
            >
              <span className={`industry-icon industry-${i % 4}`}>
                <Layers3 size={24} />
              </span>
              <span className="industry-index">0{i + 1}</span>
              <h2>{name}</h2>
              <p>{industryDescriptions[name]}</p>
              <div className="card-row">
                <span>
                  {demo
                    ? `${stocks.filter((s) => s.industry === name).length} sample companies`
                    : "Explore research"}
                </span>
                <ArrowUpRight size={18} />
              </div>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}
type ResearchItem = {
  symbol: string;
  name: string;
  industry: string;
  as_of: string;
  data_mode: string;
  rank_reason: string;
  assessment: { label: string; explanation: string };
  evidence: {
    id: string;
    title: string;
    summary: string;
    source_name: string;
    source_url?: string;
    published_at?: string;
  }[];
};
function LiveFeed({
  endpoint,
  search = "",
  articlesOnly = false,
}: {
  endpoint: string;
  search?: string;
  articlesOnly?: boolean;
}) {
  const q = useQuery({
    queryKey: ["feed", endpoint],
    queryFn: async () => {
      const r = await fetch(`/api/service/${endpoint}`);
      if (!r.ok) throw new Error("Research feed is unavailable.");
      return r.json();
    },
  });
  if (q.isPending)
    return (
      <div role="status" className="empty-state panel">
        Loading research…
      </div>
    );
  if (q.isError)
    return (
      <div className="error-box">
        {q.error.message}
        <button onClick={() => void q.refetch()} className="text-button">
          Retry
        </button>
      </div>
    );
  const items = (q.data?.data || []) as ResearchItem[];
  const filtered = items.filter((item) =>
    `${item.symbol} ${item.name}`.toLowerCase().includes(search.toLowerCase()),
  );
  if (filtered.length)
    return (
      <div className="article-list">
        {filtered.map((item) => (
          <div key={item.symbol} className="panel assessment">
            {!articlesOnly && (
              <>
                <div className="card-row">
                  <Link href={`/stocks/${item.symbol}`}>
                    <h3>
                      {item.name} · {item.symbol} <ArrowUpRight size={14} />
                    </h3>
                  </Link>
                  <Badge stance={item.assessment.label} />
                </div>
                <p>{item.assessment.explanation}</p>
                <p className="muted">
                  {item.rank_reason} · {item.data_mode} ·{" "}
                  {new Date(item.as_of).toLocaleString()}
                </p>
              </>
            )}
            {(articlesOnly ? item.evidence : item.evidence.slice(0, 1)).map(
              (e) => (
                <div key={e.id} className="evidence">
                  <strong>{e.title}</strong>
                  <p>{e.summary}</p>
                  <span className="muted">{e.source_name}</span>
                  {e.source_url && /^https?:\/\//.test(e.source_url) && (
                    <a target="_blank" rel="noreferrer" href={e.source_url}>
                      Read source <ArrowUpRight size={13} />
                    </a>
                  )}
                </div>
              ),
            )}
          </div>
        ))}
      </div>
    );
  return (
    <div className="empty-state panel">
      {q.data?.data?.length
        ? "Open a stock to explore its research."
        : "Fresh research is not available for this section yet."}
    </div>
  );
}
export function StockDetail({ symbol }: { symbol: string }) {
  const { demo } = useApp();
  const s = stocks.find((s) => s.symbol === symbol);
  const [range, setRange] = useState("1M");
  const q = useQuery({
    queryKey: ["research", symbol, demo],
    queryFn: async () => {
      const r = await fetch(
        `/api/research?symbol=${encodeURIComponent(symbol)}&mode=${demo ? "sample" : "live"}`,
      );
      const data = await r.json();
      if (!r.ok) throw new Error(data.error?.message || "Research unavailable");
      return data;
    },
  });
  return (
    <>
      <Link className="back-link" href="/">
        ← Back to overview
      </Link>
      <PageHeader
        eyebrow="STOCK RESEARCH"
        title={s ? `${s.name} · ${symbol}` : symbol}
        description={
          s
            ? `${s.industry} · ${q.data?.data_mode === "live" ? "Live source data" : demo ? "Sample market snapshot" : "Research snapshot"}`
            : "Source-backed market research"
        }
      >
        <button className="outline-button" onClick={() => void q.refetch()}>
          <RefreshCw size={14} /> Refresh
        </button>
      </PageHeader>
      {demo && s && q.data?.data_mode !== "live" && (
        <section className="panel detail-chart">
          <div className="card-row">
            <div>
              <div className="portfolio-value">{money(s.price)}</div>
              <span className={s.change >= 0 ? "positive" : "negative"}>
                {pct(s.change)} today
              </span>
            </div>
            <Badge stance={s.stance} />
          </div>
          <ResponsiveContainer width="100%" height={240}>
            <AreaChart
              data={s.history
                .slice(range === "1W" ? -7 : 0)
                .map((value, i) => ({ value, label: `Day ${i + 1}` }))}
            >
              <XAxis dataKey="label" hide />
              <YAxis hide domain={["dataMin - 2", "dataMax + 2"]} />
              <Tooltip formatter={(v) => money(Number(v))} />
              <Area
                dataKey="value"
                type="monotone"
                fill="#60887320"
                stroke="#608873"
                strokeWidth={2}
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
          <div className="chart-footer">
            <span>Illustrative prices · Oct 10, 2026</span>
            <div className="range-tabs">
              {["1W", "1M"].map((r) => (
                <button
                  className={range === r ? "selected" : ""}
                  onClick={() => setRange(r)}
                  key={r}
                >
                  {r}
                </button>
              ))}
            </div>
          </div>
        </section>
      )}
      <SectionTitle title="The research perspective" />
      {q.isPending ? (
        <div className="panel empty-state" role="status">
          Gathering research…
        </div>
      ) : q.isError ? (
        <div className="error-box" role="alert">
          {q.error.message}
          <button className="text-button" onClick={() => void q.refetch()}>
            Try again <RefreshCw size={14} />
          </button>
        </div>
      ) : (
        <div className="panel assessment">
          <div className="card-row">
            <Badge stance={q.data.assessment.label} />
            <span className="tiny-tag">
              {q.data.data_mode} ·{" "}
              {new Date(
                q.data.snapshot?.as_of || q.data.freshness?.as_of,
              ).toLocaleDateString()}
            </span>
          </div>
          <h3>{q.data.assessment.explanation}</h3>
          <p>{q.data.assessment.uncertainty}</p>
          {q.data.signals?.map(
            (v: { id: string; name: string; value: number; unit: string }) => (
              <div className="signal" key={v.id}>
                <span>{v.name}</span>
                <strong>
                  {v.value} {v.unit}
                </strong>
              </div>
            ),
          )}
          {q.data.evidence?.map(
            (e: {
              id: string;
              title: string;
              summary: string;
              source_name: string;
              source_url?: string;
            }) => (
              <div className="evidence" key={e.id}>
                <strong>{e.title}</strong>
                <p>{e.summary}</p>
                <span className="muted">{e.source_name}</span>
                {e.source_url &&
                  /^https?:\/\//i.test(e.source_url) &&
                  !e.source_url.includes("example.invalid") && (
                    <a href={e.source_url} target="_blank" rel="noreferrer">
                      Read source <ArrowUpRight size={14} />
                    </a>
                  )}
              </div>
            ),
          )}
        </div>
      )}
      {demo && q.data?.data_mode !== "live" && (
        <>
          <SectionTitle title="Related stories" />
          <ArticleList items={articles.filter((a) => a.symbol === symbol)} />
        </>
      )}
    </>
  );
}
