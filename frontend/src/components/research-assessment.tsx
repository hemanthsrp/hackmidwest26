"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, RefreshCw } from "lucide-react";
import { useApp } from "./shell";

type RecordMode = "live" | "cached" | "sample";
type Evidence = {
  id: string;
  title: string;
  summary?: string | null;
  source_name: string;
  source_type?: string;
  source_url?: string | null;
  published_at?: string | null;
  observed_at?: string | null;
  retrieved_at?: string | null;
  reporting_lag_days?: number | null;
  data_mode?: RecordMode;
};
type Signal = {
  id: string;
  name: string;
  value: number;
  unit: string;
  window?: string;
  as_of?: string;
  source?: string;
  data_mode?: RecordMode;
};
type ResearchResponse = {
  symbol: string;
  data_mode: RecordMode;
  snapshot?: { as_of?: string; retrieved_at?: string };
  freshness?: { as_of?: string | null; retrieved_at?: string | null; status: string; stale_after_seconds: number };
  assessment: {
    label: string;
    score?: number | null;
    horizon?: string;
    explanation: string;
    explanation_points?: { text: string; evidence_ids: string[] }[];
    reason_codes?: string[];
    uncertainty: string;
  };
  evidence: Evidence[];
  signals: Signal[];
  warnings?: { code: string; message: string; retryable: boolean }[];
};

export function readableDate(value?: string | null) {
  if (!value) return "Not recorded";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Not recorded" : date.toLocaleString();
}

export function sourceHref(value?: string | null) {
  if (!value) return null;
  try {
    const url = new URL(value);
    return ["https:", "http:"].includes(url.protocol) && url.hostname !== "example.invalid"
      ? url.href
      : null;
  } catch {
    return null;
  }
}

function recordId(kind: "evidence" | "signal", id: string) {
  return `${kind}-${encodeURIComponent(id)}`;
}

function Citations({ ids, evidence, signals }: { ids: string[]; evidence: Evidence[]; signals: Signal[] }) {
  if (!ids.length) return null;
  return (
    <span className="research-citations">
      {ids.map((id) => {
        const source = evidence.find((e) => e.id === id);
        const signal = signals.find((s) => s.id === id);
        return source || signal ? (
          <a key={id} href={`#${recordId(source ? "evidence" : "signal", id)}`}>
            {source?.source_name || signal?.source || id}
          </a>
        ) : (
          <span key={id} className="muted">{id.replaceAll("_", " ")}</span>
        );
      })}
    </span>
  );
}

export function ResearchAssessment({ symbol }: { symbol: string }) {
  const { demo, preferences } = useApp();
  const mode = demo ? "sample_decision" : "live";
  const q = useQuery<ResearchResponse>({
    queryKey: ["v0-research", symbol, mode, preferences.horizon, preferences.risk],
    queryFn: async () => {
      const response = await fetch("/api/research/assessment", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol, mode, preferences: { horizon: preferences.horizon, risk_profile: preferences.risk } }),
      });
      const body = await response.json();
      if (!response.ok) {
        const error = body.error;
        throw new Error(error?.message || "Research is unavailable. Please try again.");
      }
      return body as ResearchResponse;
    },
    retry: false,
  });
  const result = q.data;
  const evidence = result?.evidence || [];
  const signals = result?.signals || [];
  const groups = evidence.reduce<Record<string, Evidence[]>>((byType, record) => {
    const type = record.source_type || "Other sources";
    (byType[type] ||= []).push(record);
    return byType;
  }, {});
  return (
    <section aria-label="Research assessment">
      <div className="section-title">
        <div><h2>The research perspective</h2><p>{demo ? "Packaged sample decision · not live market evidence" : "Live request · no sample fallback"}</p></div>
        <button className="outline-button" onClick={() => void q.refetch()} disabled={q.isFetching}>
          <RefreshCw size={14} /> {q.isFetching ? "Loading…" : "Refresh research"}
        </button>
      </div>
      {q.isPending ? (
        <div className="panel empty-state" role="status">Gathering {demo ? "sample" : "live"} research…</div>
      ) : q.isError ? (
        <div className="error-box" role="alert">
          {q.error.message}{!demo && " No sample decision has been substituted."}
          <button className="text-button" onClick={() => void q.refetch()}>Try again <RefreshCw size={14} /></button>
        </div>
      ) : result && (
        <div className="panel assessment research-detail">
          <div className="card-row">
            <span className={`badge ${result.assessment.label.toLowerCase()}`}>{result.assessment.label.replaceAll("_", " ")} research</span>
            <span className="tiny-tag">{result.data_mode.toUpperCase()} · {result.freshness?.status || "snapshot"}</span>
          </div>
          {result.data_mode !== "live" && <p role="status">{result.data_mode === "sample" ? "Illustrative fixture only; not current market research." : "Cached research; review timestamps before use."}</p>}
          <p className="muted">Evidence as of {readableDate(result.freshness?.as_of || result.snapshot?.as_of)} · Retrieved {readableDate(result.freshness?.retrieved_at || result.snapshot?.retrieved_at)}{result.assessment.horizon ? ` · Horizon ${result.assessment.horizon}` : ""}</p>
          {result.assessment.score != null && <p><strong>Heuristic score: {result.assessment.score}/100.</strong> 50 is neutral; this is not a probability or validated prediction.</p>}
          <h3>{result.assessment.explanation}</h3>
          {result.assessment.explanation_points?.length ? (
            <div aria-label="Explanation citations">
              {result.assessment.explanation_points.map((point, index) => (
                <p key={index}>{point.text} <Citations ids={point.evidence_ids} evidence={evidence} signals={signals} /></p>
              ))}
            </div>
          ) : null}
          <p>{result.assessment.uncertainty}</p>
          {result.assessment.reason_codes?.length ? <p>Decision references: <Citations ids={result.assessment.reason_codes} evidence={evidence} signals={signals} /></p> : null}
          {!!result.warnings?.length && <div role="alert" className="research-warnings">
            <strong>Research limitations</strong>
            {result.warnings.map((warning, index) => <p key={`${warning.code}-${index}`}>{warning.message} ({warning.code})</p>)}
          </div>}
          <h4>Signals and options math</h4>
          <p>Options-implied volatility describes priced movement, not the direction of a stock-price forecast. Signal rows are retained with their original source and observation time.</p>
          {signals.length ? signals.map((signal) => (
            <div className="signal research-record" key={signal.id} id={recordId("signal", signal.id)}>
              <span><strong>{signal.name}</strong><small>{signal.source || "Source not recorded"} · As of {readableDate(signal.as_of)}{signal.window ? ` · ${signal.window}` : ""} · {signal.data_mode || result.data_mode}</small><small>Signal ID: {signal.id}</small></span>
              <strong>{Number.isFinite(signal.value) ? signal.value : "—"} {signal.unit}</strong>
            </div>
          )) : <p>No dated signals were returned.</p>}
          <h4>Evidence and provenance</h4>
          {evidence.length ? Object.entries(groups).map(([type, records]) => (
            <div key={type}>
              <h5>{type.replaceAll("_", " ")}</h5>
              {records?.map((item) => <div className="evidence research-record" id={recordId("evidence", item.id)} key={item.id}>
                <strong>{item.title}</strong>
                {item.summary && <p>{item.summary}</p>}
                <p>{item.source_name} · {item.data_mode || result.data_mode} · Evidence ID: {item.id}</p>
                <p>Published {readableDate(item.published_at)} · Observed {readableDate(item.observed_at)} · Retrieved {readableDate(item.retrieved_at)}{item.reporting_lag_days != null ? ` · Reporting lag ${item.reporting_lag_days} days` : ""}</p>
                {sourceHref(item.source_url) && <a href={sourceHref(item.source_url)!} target="_blank" rel="noopener noreferrer">Read source <ArrowUpRight size={14} /></a>}
              </div>)}
            </div>
          )) : <p>No attributable evidence was returned for this symbol.</p>}
        </div>
      )}
    </section>
  );
}
