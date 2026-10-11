import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

vi.mock("@tanstack/react-query", () => ({ useQuery: vi.fn() }));
vi.mock("./shell", () => ({ useApp: vi.fn() }));
import { useQuery } from "@tanstack/react-query";
import { useApp } from "./shell";
import { ResearchAssessment, readableDate, sourceHref } from "./research-assessment";

const data = {
  symbol: "AAPL", data_mode: "live", freshness: { as_of: "2026-10-10T00:00:00Z", retrieved_at: "2026-10-11T00:00:00Z", status: "fresh", stale_after_seconds: 604800 },
  assessment: { label: "hold", score: 50, horizon: "30d", explanation: "Mixed evidence.", explanation_points: [{ text: "Options price movement.", evidence_ids: ["iv-1"] }], reason_codes: ["e-1", "iv-1"], uncertainty: "Not a forecast." },
  evidence: [{ id: "e-1", title: "Filing", source_name: "SEC", source_type: "filing", source_url: "https://www.sec.gov/filing", published_at: "2026-10-09T00:00:00Z", observed_at: "2026-10-09T00:00:00Z", retrieved_at: "2026-10-10T00:00:00Z", data_mode: "cached" }],
  signals: [{ id: "iv-1", name: "ATM implied volatility", value: 31, unit: "percent_annualized", source: "Persisted options surface", as_of: "2026-10-10T00:00:00Z", data_mode: "live" }],
  warnings: [{ code: "quant_unavailable", message: "A separate provider was unavailable.", retryable: true }],
};

describe("research detail provenance", () => {
  it("shows source lifecycle, dated volatility citation, warning and score semantics", () => {
    vi.mocked(useApp).mockReturnValue({ demo: false, preferences: { horizon: "30d", risk: "balanced" } } as ReturnType<typeof useApp>);
    vi.mocked(useQuery).mockReturnValue({ data, isPending: false, isError: false, isFetching: false } as unknown as ReturnType<typeof useQuery>);
    const html = renderToStaticMarkup(<ResearchAssessment symbol="AAPL" />);
    expect(html).toContain("Heuristic score: 50/100");
    expect(html).toContain("not a probability");
    expect(html).toContain("Persisted options surface");
    expect(html).toContain('href="#signal-iv-1"');
    expect(html).toContain("Published");
    expect(html).toContain("Observed");
    expect(html).toContain("Retrieved");
    expect(html).toContain("cached");
    expect(html).toContain("quant_unavailable");
  });

  it("does not turn fixture or unsafe URLs into external source links", () => {
    expect(sourceHref("https://example.invalid/fixture")).toBeNull();
    expect(sourceHref("javascript:alert(1)")).toBeNull();
    expect(sourceHref("https://www.sec.gov/filing")).toBe("https://www.sec.gov/filing");
    expect(readableDate("bad-date")).toBe("Not recorded");
  });
});
