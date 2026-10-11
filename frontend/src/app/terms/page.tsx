import Link from "next/link";

export default function TermsPage() {
  return (
    <main className="legal-page">
      <Link className="text-button" href="/">
        ← Back to Folio
      </Link>
      <p className="eyebrow">BETA USE</p>
      <h1>Using Folio</h1>
      <p className="legal-updated">Last updated October 11, 2026</p>

      <section>
        <h2>Research information only</h2>
        <p>
          Folio provides general market information and research context. Its
          assessments are rule-based research heuristics, not predictions,
          probabilities, personalized investment advice, or recommendations
          suited to your circumstances. Folio is not a broker and cannot place,
          change, or cancel trades.
        </p>
      </section>

      <section>
        <h2>Check the evidence</h2>
        <p>
          Source coverage may be partial, delayed, unavailable, or incorrect.
          Review source links, dates, freshness labels, warnings, and
          uncertainty before drawing conclusions. Sample information is
          illustrative and is labeled as such. Live source access does not
          establish that an assessment is accurate or predictive.
        </p>
      </section>

      <section>
        <h2>Beta service</h2>
        <p>
          Folio is under active development. Features, availability, and data
          coverage may change. Do not rely on the service as the sole basis for
          a financial decision. Never submit brokerage credentials or account
          numbers in a message. If you connect Robinhood, Folio receives
          limited portfolio data under your separate Robinhood authorization;
          this connection is read only in Folio and cannot place trades.
        </p>
      </section>

      <p className="legal-draft">
        This page states Folio’s intended beta use and product limits. The
        operator must review it for the final launch jurisdiction and hosting
        arrangement before public sign-up opens.
      </p>
    </main>
  );
}
